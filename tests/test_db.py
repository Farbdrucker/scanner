"""Tests for app/db.py — uses a tmp_path-scoped SQLite DB."""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db import (
    Document,
    _AI_FILENAME_RE,
    _FALLBACK_FILENAME_RE,
    get_document,
    init_db,
    insert_document,
    query_documents,
)


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    """Point settings.db_path and settings.doc_dir at tmp_path for every test."""
    from app import db as db_module
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "doc_dir", tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    # Patch the module-level settings reference used in db.py
    monkeypatch.setattr(db_module, "settings", settings)


async def _init() -> None:
    await init_db()


# ---------------------------------------------------------------------------
# Filename regex helpers
# ---------------------------------------------------------------------------


def test_ai_filename_regex_matches():
    assert _AI_FILENAME_RE.match("2024-03-01_invoice-acme.pdf")
    assert _AI_FILENAME_RE.match("2023-12-31_receipt.jpg")


def test_ai_filename_regex_groups():
    m = _AI_FILENAME_RE.match("2024-03-01_invoice-acme.pdf")
    assert m is not None
    assert m.group(1) == "2024-03-01"
    assert m.group(2) == "invoice-acme"


def test_fallback_filename_regex_matches():
    assert _FALLBACK_FILENAME_RE.match("2024-03-01T14-05-30_document.pdf")


def test_fallback_filename_regex_no_match_on_ai():
    assert not _FALLBACK_FILENAME_RE.match("2024-03-01_invoice-acme.pdf")


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_creates_table(tmp_path):
    await init_db()
    import aiosqlite
    from app.config import settings

    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
        ) as cur:
            row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_init_db_idempotent():
    """Calling init_db twice must not raise."""
    await init_db()
    await init_db()


# ---------------------------------------------------------------------------
# insert_document / get_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_and_get(tmp_path):
    await init_db()
    doc_id = await insert_document(
        stored_filename="2024-03-01_invoice-acme.pdf",
        original_filename="scan001.pdf",
        date="2024-03-01",
        tags=["invoice", "acme"],
        extracted_text="Invoice total $100",
        file_size=1024,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    assert doc_id > 0

    doc = await get_document(doc_id)
    assert doc is not None
    assert doc.stored_filename == "2024-03-01_invoice-acme.pdf"
    assert doc.original_filename == "scan001.pdf"
    assert doc.date == "2024-03-01"
    assert doc.tags == ["invoice", "acme"]
    assert doc.file_size == 1024
    assert doc.is_fallback is False


@pytest.mark.asyncio
async def test_get_document_missing():
    await init_db()
    assert await get_document(99999) is None


@pytest.mark.asyncio
async def test_insert_duplicate_ignored():
    """INSERT OR IGNORE — second insert with same stored_filename returns 0."""
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_invoice.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=[],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    doc_id2 = await insert_document(
        stored_filename="2024-03-01_invoice.pdf",  # same unique key
        original_filename="b.pdf",
        date="2024-03-01",
        tags=[],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    assert doc_id2 == 0


# ---------------------------------------------------------------------------
# Document properties
# ---------------------------------------------------------------------------


def test_size_display_bytes():
    doc = Document(1, "x.pdf", "x.pdf", "2024-01-01", [], "", 512, "application/pdf", False, "", None, "")
    assert doc.size_display == "512 B"


def test_size_display_kb():
    doc = Document(1, "x.pdf", "x.pdf", "2024-01-01", [], "", 2048, "application/pdf", False, "", None, "")
    assert doc.size_display == "2.0 KB"


def test_ext_property():
    doc = Document(1, "file.PDF", "file.PDF", "2024-01-01", [], "", 0, "", False, "", None, "")
    assert doc.ext == "PDF"


# ---------------------------------------------------------------------------
# query_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_empty():
    await init_db()
    results, _ = await query_documents()
    assert results == []


@pytest.mark.asyncio
async def test_query_all():
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_invoice.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=["invoice"],
        extracted_text="total $100",
        file_size=100,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    results, _ = await query_documents()
    assert len(results) == 1
    assert results[0].stored_filename == "2024-03-01_invoice.pdf"


@pytest.mark.asyncio
async def test_query_by_tag():
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_invoice.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=["invoice"],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    await insert_document(
        stored_filename="2024-04-01_receipt.pdf",
        original_filename="b.pdf",
        date="2024-04-01",
        tags=["receipt"],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    results, _ = await query_documents(q="invoice")
    assert len(results) == 1
    assert results[0].tags == ["invoice"]


@pytest.mark.asyncio
async def test_query_by_text():
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_doc.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=[],
        extracted_text="confidential report",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    results, _ = await query_documents(q="confidential")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_query_by_date_prefix():
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_doc.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=[],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    await insert_document(
        stored_filename="2024-04-01_doc.pdf",
        original_filename="b.pdf",
        date="2024-04-01",
        tags=[],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    results, _ = await query_documents(date="2024-03")
    assert len(results) == 1
    assert results[0].date == "2024-03-01"


@pytest.mark.asyncio
async def test_query_no_match():
    await init_db()
    await insert_document(
        stored_filename="2024-03-01_doc.pdf",
        original_filename="a.pdf",
        date="2024-03-01",
        tags=["invoice"],
        extracted_text="",
        file_size=0,
        content_type="application/pdf",
        is_fallback=False,
        due_date=None,
    )
    results, _ = await query_documents(q="zzznomatch")
    assert results == []


# ---------------------------------------------------------------------------
# Backfill from filesystem
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_ai_named_file(tmp_path):
    from app.config import settings

    doc_file = settings.doc_dir / "2024-03-01_invoice-acme.pdf"
    doc_file.write_bytes(b"fake pdf content")

    await init_db()
    results, _ = await query_documents()
    assert len(results) == 1
    doc = results[0]
    assert doc.date == "2024-03-01"
    assert doc.tags == ["invoice", "acme"]
    assert doc.is_fallback is False


@pytest.mark.asyncio
async def test_backfill_fallback_named_file(tmp_path):
    from app.config import settings

    doc_file = settings.doc_dir / "2024-03-01T14-05-30_document.pdf"
    doc_file.write_bytes(b"fake pdf content")

    await init_db()
    results, _ = await query_documents()
    assert len(results) == 1
    doc = results[0]
    assert doc.date == "2024-03-01"
    assert doc.is_fallback is True


@pytest.mark.asyncio
async def test_backfill_skips_md_files(tmp_path):
    from app.config import settings

    (settings.doc_dir / "2024-03-01_invoice.pdf").write_bytes(b"pdf")
    (settings.doc_dir / "2024-03-01_invoice.md").write_text("extracted text")

    await init_db()
    results, _ = await query_documents()
    assert len(results) == 1  # only the pdf, not the .md


@pytest.mark.asyncio
async def test_backfill_reads_companion_md(tmp_path):
    from app.config import settings

    (settings.doc_dir / "2024-03-01_invoice.pdf").write_bytes(b"pdf")
    (settings.doc_dir / "2024-03-01_invoice.md").write_text("invoice text content")

    await init_db()
    results, _ = await query_documents()
    assert results[0].extracted_text == "invoice text content"


@pytest.mark.asyncio
async def test_backfill_idempotent(tmp_path):
    """Running init_db twice must not duplicate rows."""
    from app.config import settings

    (settings.doc_dir / "2024-03-01_invoice.pdf").write_bytes(b"pdf")

    await init_db()
    await init_db()
    results, _ = await query_documents()
    assert len(results) == 1
