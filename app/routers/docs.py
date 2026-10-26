from ..templates import templates
import markdown
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from ..config import get_config
from ..services.doc_store import (
    create_folder,
    delete_path,
    extract_zip,
    get_file,
    list_dir,
    save_file,
)

router = APIRouter(prefix="/files")

PREVIEW_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".md", ".txt"}


@router.get("", response_class=HTMLResponse)
async def browse(request: Request, path: str = ""):
    cfg = get_config()
    try:
        info = list_dir(cfg.docs_dir, path)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    ctx = {"info": info, "preview_extensions": PREVIEW_EXTENSIONS}
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "docs/_file_list.html", ctx)
    return templates.TemplateResponse(request, "docs/browser.html", ctx)


@router.get("/raw")
async def raw_file(path: str = ""):
    cfg = get_config()
    try:
        data, mime = get_file(cfg.docs_dir, path)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404)
    return Response(content=data, media_type=mime)


@router.get("/preview", response_class=HTMLResponse)
async def preview(request: Request, path: str = ""):
    cfg = get_config()
    try:
        data, mime = get_file(cfg.docs_dir, path)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404)

    filename = path.split("/")[-1]
    suffix = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""

    rendered_md = None
    if suffix == ".md":
        rendered_md = markdown.markdown(data.decode("utf-8"), extensions=["fenced_code", "tables"])
    elif suffix == ".txt":
        rendered_md = data.decode("utf-8")

    return templates.TemplateResponse(
        request,
        "docs/preview.html",
        {
            "path": path,
            "filename": filename,
            "mime": mime,
            "suffix": suffix,
            "rendered_md": rendered_md,
        },
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, path: str = Form(""), file: UploadFile = File(...)):
    cfg = get_config()
    data = await file.read()
    try:
        save_file(cfg.docs_dir, path, file.filename, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    info = list_dir(cfg.docs_dir, path)
    return templates.TemplateResponse(request, "docs/_file_list.html", {"info": info, "preview_extensions": PREVIEW_EXTENSIONS})


@router.post("/upload-zip", response_class=HTMLResponse)
async def upload_zip(request: Request, path: str = Form(""), file: UploadFile = File(...)):
    cfg = get_config()
    data = await file.read()
    try:
        extract_zip(cfg.docs_dir, path, data)
    except (ValueError, Exception) as e:
        raise HTTPException(400, str(e))
    info = list_dir(cfg.docs_dir, path)
    return templates.TemplateResponse(request, "docs/_file_list.html", {"info": info, "preview_extensions": PREVIEW_EXTENSIONS})


@router.post("/mkdir", response_class=HTMLResponse)
async def mkdir(request: Request, path: str = Form(""), name: str = Form(...)):
    cfg = get_config()
    try:
        create_folder(cfg.docs_dir, path, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    info = list_dir(cfg.docs_dir, path)
    return templates.TemplateResponse(request, "docs/_file_list.html", {"info": info, "preview_extensions": PREVIEW_EXTENSIONS})


@router.delete("/delete", response_class=HTMLResponse)
async def delete(request: Request, path: str = "", current_dir: str = ""):
    cfg = get_config()
    try:
        delete_path(cfg.docs_dir, path)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))
    info = list_dir(cfg.docs_dir, current_dir)
    return templates.TemplateResponse(request, "docs/_file_list.html", {"info": info, "preview_extensions": PREVIEW_EXTENSIONS})

