import re
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_document, update_document

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.post("/document/{doc_id}/edit", response_class=HTMLResponse)
async def edit_document(
    request: Request,
    doc_id: int,
    tags: str = Form(default=""),
    date: str = Form(default=""),
    due_date: str = Form(default=""),
    paid: str = Form(default=""),
    original_filename: str = Form(default=""),
) -> HTMLResponse:
    doc = await get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404)

    raw_tags = [t.strip().lower() for t in re.split(r"[,\s]+", tags) if t.strip()]
    clean_tags = [re.sub(r"[^a-z0-9-]", "", t) for t in raw_tags]
    clean_tags = [t for t in clean_tags if t] or doc.tags

    clean_due = due_date.strip() or None
    clean_date = date.strip() or doc.date
    clean_filename = original_filename.strip() or doc.original_filename

    if paid == "on" and not doc.is_paid:
        new_paid_at: str | None = datetime.now().isoformat()
    elif paid != "on":
        new_paid_at = None
    else:
        new_paid_at = doc.paid_at

    await update_document(
        doc_id,
        tags=clean_tags,
        date=clean_date,
        due_date=clean_due,
        paid_at=new_paid_at,
        original_filename=clean_filename,
    )

    updated_doc = await get_document(doc_id)
    return templates.TemplateResponse(
        "partials/doc_edit_result.html",
        {"request": request, "doc": updated_doc},
    )
