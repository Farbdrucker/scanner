import re
from datetime import datetime
from typing import Any

import aiosqlite
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.db import (
    Document,
    get_document_by_short_code,
    query_documents,
    update_document,
)
from app.jobs import JobStatus, job_queue
from app.pdf import images_to_pdf

router = APIRouter(prefix="/api")


def _doc_to_dict(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "short_code": doc.short_code,
        "stored_filename": doc.stored_filename,
        "original_filename": doc.original_filename,
        "date": doc.date,
        "tags": doc.tags,
        "file_size": doc.file_size,
        "size_display": doc.size_display,
        "ext": doc.ext,
        "content_type": doc.content_type,
        "is_fallback": doc.is_fallback,
        "uploaded_at": doc.uploaded_at,
        "due_date": doc.due_date,
        "due_status": doc.due_status,
        "paid_at": doc.paid_at,
        "is_paid": doc.is_paid,
    }


@router.post("/upload")
async def api_upload(files: list[UploadFile] = File(default=[])) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No file received.")
    if len(files) == 1:
        file_bytes = await files[0].read()
        original_filename = files[0].filename or "upload.bin"
    else:
        try:
            image_bytes_list = [await f.read() for f in files]
            file_bytes = images_to_pdf(image_bytes_list)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        original_filename = "scan.pdf"

    job = job_queue.enqueue(file_bytes, original_filename)
    return JSONResponse({"job_id": job.id, "original_filename": original_filename})


@router.get("/jobs/{job_id}")
async def api_job_status(job_id: str) -> JSONResponse:
    job = job_queue._jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    short_code = None
    if job.status == JobStatus.done and job.filename:
        async with aiosqlite.connect(settings.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT short_code FROM documents WHERE stored_filename = ?",
                (job.filename,),
            ) as cur:
                row = await cur.fetchone()
            if row:
                short_code = row["short_code"]

    return JSONResponse(
        {
            "status": job.status.value,
            "filename": job.filename,
            "short_code": short_code,
            "error": job.error,
        }
    )


@router.get("/documents")
async def api_list_documents(
    q: str = "",
    date: str = "",
    offset: int = 0,
    limit: int = 10,
) -> JSONResponse:
    docs, has_more = await query_documents(q=q, date=date, limit=limit, offset=offset)
    return JSONResponse(
        {
            "documents": [_doc_to_dict(d) for d in docs],
            "has_more": has_more,
        }
    )


@router.get("/documents/{short_code}")
async def api_get_document(short_code: str) -> JSONResponse:
    doc = await get_document_by_short_code(short_code)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return JSONResponse(_doc_to_dict(doc))


class EditBody(BaseModel):
    tags: str | None = None
    date: str | None = None
    due_date: str | None = None
    original_filename: str | None = None
    paid: bool | None = None


@router.post("/documents/{short_code}")
async def api_edit_document(short_code: str, body: EditBody) -> JSONResponse:
    doc = await get_document_by_short_code(short_code)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    if body.tags is not None:
        raw_tags = [
            t.strip().lower() for t in re.split(r"[,\s]+", body.tags) if t.strip()
        ]
        clean_tags = [re.sub(r"[^a-z0-9-]", "", t) for t in raw_tags]
        clean_tags = [t for t in clean_tags if t] or doc.tags
    else:
        clean_tags = doc.tags

    clean_date = (body.date or "").strip() or doc.date
    clean_due: str | None = (
        (body.due_date or "").strip() or None
        if body.due_date is not None
        else doc.due_date
    )
    clean_filename = (body.original_filename or "").strip() or doc.original_filename

    if body.paid is not None:
        if body.paid and not doc.is_paid:
            new_paid_at: str | None = datetime.now().isoformat()
        elif not body.paid:
            new_paid_at = None
        else:
            new_paid_at = doc.paid_at
    else:
        new_paid_at = doc.paid_at

    await update_document(
        doc.id,
        tags=clean_tags,
        date=clean_date,
        due_date=clean_due,
        paid_at=new_paid_at,
        original_filename=clean_filename,
    )

    updated = await get_document_by_short_code(short_code)
    assert updated is not None
    return JSONResponse(_doc_to_dict(updated))
