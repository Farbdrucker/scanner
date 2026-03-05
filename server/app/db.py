import json
import logging
import random
import re
import string
from dataclasses import dataclass
from datetime import date as _date, datetime
from pathlib import Path

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# Matches the AI-generated filename pattern: YYYY-MM-DD_tags.ext
_AI_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)\.[^.]+$")
# Matches the fallback timestamp pattern: YYYY-MM-DDTHH-MM-SS_document.ext
_FALLBACK_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T[\d-]+_document\.[^.]+$")


def _generate_short_code() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=5))


async def _unique_short_code(db: aiosqlite.Connection) -> str:
    """Generate a code not yet in the DB (collision extremely unlikely)."""
    while True:
        code = _generate_short_code()
        async with db.execute("SELECT 1 FROM documents WHERE short_code = ?", (code,)) as cur:
            if await cur.fetchone() is None:
                return code


@dataclass
class Document:
    id: int
    stored_filename: str
    original_filename: str
    date: str
    tags: list[str]
    extracted_text: str
    file_size: int
    content_type: str
    is_fallback: bool
    uploaded_at: str
    due_date: str | None
    paid_at: str | None
    short_code: str

    @property
    def is_paid(self) -> bool:
        return self.paid_at is not None

    @property
    def size_display(self) -> str:
        if self.file_size < 1024:
            return f"{self.file_size} B"
        return f"{self.file_size / 1024:.1f} KB"

    @property
    def ext(self) -> str:
        return Path(self.stored_filename).suffix.lstrip(".").upper()

    @property
    def due_status(self) -> str | None:
        if not self.due_date:
            return None
        from datetime import timedelta  # noqa: F401 (timedelta unused but import kept for clarity)
        due = _date.fromisoformat(self.due_date)
        delta = (due - _date.today()).days
        if delta < 0:
            return "overdue"
        if delta <= 7:
            return "urgent"
        if delta <= 30:
            return "soon"
        return "future"


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                stored_filename   TEXT    NOT NULL UNIQUE,
                original_filename TEXT    NOT NULL,
                date              TEXT    NOT NULL,
                tags              TEXT    NOT NULL DEFAULT '[]',
                extracted_text    TEXT    NOT NULL DEFAULT '',
                file_size         INTEGER NOT NULL DEFAULT 0,
                content_type      TEXT    NOT NULL DEFAULT '',
                is_fallback       INTEGER NOT NULL DEFAULT 0,
                uploaded_at       TEXT    NOT NULL
            )
        """)
        await db.commit()
        # Migrate: add columns if they don't exist yet
        for col_ddl in [
            "ALTER TABLE documents ADD COLUMN due_date TEXT",
            "ALTER TABLE documents ADD COLUMN short_code TEXT",
            "ALTER TABLE documents ADD COLUMN paid_at TEXT",
        ]:
            try:
                await db.execute(col_ddl)
                await db.commit()
            except aiosqlite.OperationalError:
                pass  # column already exists
    # Filesystem backfill runs first so its rows exist before we assign codes
    await _backfill_from_filesystem()
    # Backfill short_code for any rows still missing one (new or filesystem-inserted)
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute("SELECT id FROM documents WHERE short_code IS NULL") as cur:
            rows = await cur.fetchall()
        for (doc_id,) in rows:
            code = await _unique_short_code(db)
            await db.execute("UPDATE documents SET short_code = ? WHERE id = ?", (code, doc_id))
        await db.commit()


async def _backfill_from_filesystem() -> None:
    """Add files already in doc_dir to DB if they are not there yet."""
    doc_dir = settings.doc_dir
    if not doc_dir.exists():
        return
    for path in doc_dir.iterdir():
        if path.suffix == ".md" or not path.is_file():
            continue
        name = path.name
        m_ai = _AI_FILENAME_RE.match(name)
        m_fb = _FALLBACK_FILENAME_RE.match(name)
        if m_ai:
            date = m_ai.group(1)
            tags = m_ai.group(2).split("-")
            is_fallback = False
        elif m_fb:
            date = m_fb.group(1)
            tags = []
            is_fallback = True
        else:
            date = _date.today().isoformat()
            tags = []
            is_fallback = True
        md_path = path.with_suffix(".md")
        extracted_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        file_size = path.stat().st_size
        mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        async with aiosqlite.connect(settings.db_path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO documents
                   (stored_filename, original_filename, date, tags, extracted_text,
                    file_size, content_type, is_fallback, uploaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, name, date, json.dumps(tags), extracted_text,
                 file_size, "", int(is_fallback), mtime),
            )
            await db.commit()


async def insert_document(
    *,
    stored_filename: str,
    original_filename: str,
    date: str,
    tags: list[str],
    extracted_text: str,
    file_size: int,
    content_type: str,
    is_fallback: bool,
    due_date: str | None,
) -> int:
    async with aiosqlite.connect(settings.db_path) as db:
        short_code = await _unique_short_code(db)
        cursor = await db.execute(
            """INSERT OR IGNORE INTO documents
               (stored_filename, original_filename, date, tags, extracted_text,
                file_size, content_type, is_fallback, uploaded_at, due_date, short_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (stored_filename, original_filename, date, json.dumps(tags),
             extracted_text, file_size, content_type, int(is_fallback),
             datetime.now().isoformat(), due_date, short_code),
        )
        await db.commit()
        return cursor.lastrowid or 0


async def query_documents(
    q: str = "", date: str = "", limit: int = 10, offset: int = 0
) -> tuple[list[Document], bool]:
    """
    q      — searches tags + extracted_text + original_filename (LIKE)
    date   — YYYY-MM prefix filter (from <input type="month">)
    limit  — max rows to return
    offset — rows to skip (for pagination)

    Returns (docs, has_more) where has_more indicates another page exists.
    """
    sql = """
        SELECT id, stored_filename, original_filename, date, tags, extracted_text,
               file_size, content_type, is_fallback, uploaded_at, due_date, paid_at, short_code
        FROM documents
        WHERE (? = '' OR tags LIKE '%' || ? || '%'
                      OR extracted_text LIKE '%' || ? || '%'
                      OR original_filename LIKE '%' || ? || '%'
                      OR short_code = ?)
          AND (? = '' OR date LIKE ? || '%')
        ORDER BY uploaded_at DESC
        LIMIT ? OFFSET ?
    """
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, (q, q, q, q, q, date, date, limit + 1, offset)) as cursor:
            rows = await cursor.fetchall()
    has_more = len(rows) > limit
    return [_row_to_doc(r) for r in rows[:limit]], has_more


async def get_document(doc_id: int) -> Document | None:
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_doc(row) if row else None


async def update_document(
    doc_id: int,
    *,
    tags: list[str],
    date: str,
    due_date: str | None,
    paid_at: str | None,
    original_filename: str,
) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """UPDATE documents
               SET tags=?, date=?, due_date=?, paid_at=?, original_filename=?
               WHERE id=?""",
            (json.dumps(tags), date, due_date, paid_at, original_filename, doc_id),
        )
        await db.commit()


def _row_to_doc(row: aiosqlite.Row) -> Document:
    return Document(
        id=row["id"],
        stored_filename=row["stored_filename"],
        original_filename=row["original_filename"],
        date=row["date"],
        tags=json.loads(row["tags"]),
        extracted_text=row["extracted_text"],
        file_size=row["file_size"],
        content_type=row["content_type"],
        is_fallback=bool(row["is_fallback"]),
        uploaded_at=row["uploaded_at"],
        due_date=row["due_date"],
        paid_at=row["paid_at"],
        short_code=row["short_code"] or "",
    )
