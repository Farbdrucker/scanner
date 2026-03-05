from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.jobs import job_queue
from app.pdf import images_to_pdf

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
router = APIRouter()
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.post("/upload", response_class=HTMLResponse)
async def upload(
    request: Request, files: list[UploadFile] = File(default=[])
) -> HTMLResponse:
    if not files:
        return templates.TemplateResponse(
            "partials/upload_result.html",
            {
                "request": request,
                "success": False,
                "filename": None,
                "preview_b64": "",
                "error": "No file received.",
            },
        )
    if len(files) == 1:
        file_bytes = await files[0].read()
        original_filename = files[0].filename or "upload.bin"
    else:
        try:
            image_bytes_list = [await f.read() for f in files]
            file_bytes = images_to_pdf(image_bytes_list)
        except Exception as exc:
            return templates.TemplateResponse(
                "partials/upload_result.html",
                {
                    "request": request,
                    "success": False,
                    "filename": None,
                    "preview_b64": "",
                    "error": str(exc),
                },
            )
        original_filename = "scan.pdf"
    job_queue.enqueue(file_bytes, original_filename)
    display_name = original_filename if len(files) == 1 else f"{len(files)}-page scan"
    return templates.TemplateResponse(
        "partials/upload_result.html",
        {
            "request": request,
            "success": True,
            "filename": display_name,
            "preview_b64": "",
            "error": None,
        },
    )
