from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import get_document, query_documents
from app.jobs import job_queue

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/files", response_class=HTMLResponse)
async def file_list(
    request: Request,
    q: str = Query(default=""),
    date: str = Query(default=""),
    offset: int = Query(default=0),
) -> HTMLResponse:
    docs, has_more = await query_documents(q=q.strip(), date=date.strip(), offset=offset)
    active_jobs = job_queue.get_active()
    return templates.TemplateResponse(
        "partials/file_list.html",
        {
            "request": request,
            "docs": docs,
            "active_jobs": active_jobs,
            "q": q,
            "date": date,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + 10,
        },
    )


@router.get("/file/{doc_id}")
async def serve_file(doc_id: int) -> FileResponse:
    doc = await get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = settings.doc_dir / doc.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from disk")
    return FileResponse(
        path,
        media_type=doc.content_type or None,
        headers={"Content-Disposition": f'inline; filename="{doc.stored_filename}"'},
    )
