from ..templates import templates
import asyncio
import base64
import json
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..config import get_config
from ..db import get_db
from ..services import issue_store as store
from ..services.lighthouse_client import push_issue, push_delete
from ..services.issue_index import (
    delete_issue_from_index,
    query_issues,
    sync_index,
    upsert_issue,
)

router = APIRouter(prefix="/issues")


def _zip_path(issue_id: str) -> Path:
    if not store.is_safe_id(issue_id):
        raise HTTPException(404)
    cfg = get_config()
    return cfg.issues_dir / f"issue-{issue_id}.zip"


# ─── Autocomplete (for @mention) — must be before /{issue_id} ────────────────

@router.get("/autocomplete", response_class=JSONResponse)
async def autocomplete(q: str = ""):
    db = await get_db()
    issues = await query_issues(db, search=q or None, sort="modified", order="desc")
    return [{"id": i["id"], "title": i["title"] or "(untitled)"} for i in issues[:20]]


# ─── List ────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def list_issues(
    request: Request,
    status: str = "",
    priority: str = "",
    tag: str = "",
    search: str = "",
    due_from: str = "",
    due_to: str = "",
    site: str = "",
    type: str = "",
    sort: str = "modified",
    order: str = "desc",
):
    db = await get_db()
    issues = await query_issues(
        db,
        status=status or None,
        priority=priority or None,
        tag=tag or None,
        search=search or None,
        due_from=due_from or None,
        due_to=due_to or None,
        origin_site=site or None,
        type=type or None,
        sort=sort,
        order=order,
    )

    # Collect sites for the filter dropdown (only relevant in lighthouse mode)
    cfg = get_config()
    sites: list[dict] = []
    if cfg.mode == "lighthouse":
        async with db.execute(
            "SELECT site_name, site_id FROM sync_instances WHERE revoked = 0 ORDER BY site_name"
        ) as cur:
            sites = [{"name": r[0], "id": r[1]} for r in await cur.fetchall()]

    from ..services.report_store import load_templates as _load_tpl
    report_templates = _load_tpl(cfg.report_templates_file)

    ctx = {
        "issues": issues,
        "today": date.today().isoformat(),
        "sites": sites,
        "report_templates": report_templates,
        "filters": {
            "status": status,
            "priority": priority,
            "tag": tag,
            "search": search,
            "due_from": due_from,
            "due_to": due_to,
            "site": site,
            "type": type,
            "sort": sort,
            "order": order,
        },
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "issues/_issue_list.html", ctx)
    return templates.TemplateResponse(request, "issues/list.html", ctx)


# ─── New ─────────────────────────────────────────────────────────────────────

@router.post("/new", response_class=HTMLResponse)
async def create_issue(request: Request, template_id: str = Form(""), report: str = Form("")):
    from fastapi.responses import RedirectResponse
    cfg = get_config()

    if template_id:
        from ..services.report_store import get_template
        tpl = get_template(cfg.report_templates_file, template_id)
        if tpl:
            meta = store.new_issue_meta(title=tpl["name"], issue_type="report")
            meta["tags"] = tpl.get("tags") or []
            meta["priority"] = tpl.get("priority", "medium")
            body = tpl.get("body", "")
        else:
            meta = store.new_issue_meta(issue_type="report")
            body = ""
    elif report:
        meta = store.new_issue_meta(issue_type="report")
        body = ""
    else:
        meta = store.new_issue_meta()
        body = ""

    zip_path = store.create_issue_zip(cfg.issues_dir, meta, body)
    db = await get_db()
    await upsert_issue(db, meta, str(zip_path))
    await db.commit()
    return RedirectResponse(f"/issues/{meta['id']}", status_code=303)


# ─── Detail / Editor ─────────────────────────────────────────────────────────

@router.get("/{issue_id}", response_class=HTMLResponse)
async def issue_detail(request: Request, issue_id: str):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404, "Issue not found")
    meta, body = store.read_issue(zip_path)
    attachments = store.list_attachments(zip_path)

    cfg = get_config()
    sites: list[dict] = []
    if cfg.mode == "lighthouse":
        db = await get_db()
        async with db.execute(
            "SELECT site_name, site_id FROM sync_instances WHERE revoked = 0 ORDER BY site_name"
        ) as cur:
            sites = [{"name": r[0], "id": r[1]} for r in await cur.fetchall()]

    signature_b64 = None
    if meta.get("type") == "report" and meta.get("signed_at"):
        import base64 as _b64
        sig = store.get_signature(zip_path)
        if sig:
            signature_b64 = _b64.b64encode(sig).decode()

    return templates.TemplateResponse(
        request,
        "issues/detail.html",
        {
            "meta": meta,
            "body": body,
            "attachments": attachments,
            "issue_id": issue_id,
            "sites": sites,
            "signature_b64": signature_b64,
        },
    )


# ─── Print / PDF export ──────────────────────────────────────────────────────


@router.get("/{issue_id}/pdf")
async def export_pdf(issue_id: str):
    from ..services.pdf_export import build_issue_pdf
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404, "Issue not found")
    meta, body = store.read_issue(zip_path)
    sig = store.get_signature(zip_path) if meta.get("signed_at") else None
    pdf_bytes = build_issue_pdf(meta, body, sig, get_config().site_name)
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in (meta.get("title") or "issue")).strip() or "issue"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe}.pdf"'},
    )


# ─── Save ────────────────────────────────────────────────────────────────────

@router.post("/{issue_id}/save")
async def save_issue(
    request: Request,
    issue_id: str,
    title: str = Form(""),
    status: str = Form("open"),
    priority: str = Form("medium"),
    tags: str = Form(""),
    due: str = Form(""),
    body: str = Form(""),
    origin_site: str = Form(""),
    report_data: str = Form(""),
):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404)

    meta, _ = store.read_issue(zip_path)

    if meta.get("signed_at"):
        raise HTTPException(403, "Issue is signed and locked")

    meta["title"] = title
    meta["status"] = status
    meta["priority"] = priority
    meta["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    meta["due"] = due or None
    if origin_site:
        meta["origin_site"] = origin_site
    if report_data:
        import json as _json
        try:
            meta["report"] = _json.loads(report_data)
        except Exception:
            pass

    store.write_issue(zip_path, meta, body)

    db = await get_db()
    await upsert_issue(db, meta, str(zip_path))
    await db.commit()

    asyncio.create_task(push_issue(get_config(), zip_path))

    if request.headers.get("HX-Request"):
        return HTMLResponse('<span class="save-ok">Gespeichert ✓</span>', status_code=200)
    return JSONResponse({"ok": True})


# ─── Images ──────────────────────────────────────────────────────────────────

@router.post("/{issue_id}/images")
async def upload_image(issue_id: str, data: str = Form(...), filename: str = Form(...)):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404)

    if "," in data:
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)

    ext = Path(filename).suffix or ".png"
    name = f"img-{uuid.uuid4().hex[:8]}{ext}"
    store.add_image(zip_path, name, raw)

    return JSONResponse({"url": f"/issues/{issue_id}/images/{name}"})


@router.get("/{issue_id}/images/{filename}")
async def serve_image(issue_id: str, filename: str):
    zip_path = _zip_path(issue_id)
    try:
        data = store.get_file_from_zip(zip_path, f"images/{filename}")
    except Exception:
        raise HTTPException(404)
    ext = Path(filename).suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
    return Response(content=data, media_type=mime)


# ─── Attachments ─────────────────────────────────────────────────────────────

@router.post("/{issue_id}/attachments", response_class=HTMLResponse)
async def add_attachment(request: Request, issue_id: str, file: UploadFile = File(...)):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404)
    data = await file.read()
    store.add_attachment(zip_path, file.filename, data)
    attachments = store.list_attachments(zip_path)
    return templates.TemplateResponse(
        request,
        "issues/_attachments.html",
        {"issue_id": issue_id, "attachments": attachments},
    )


@router.delete("/{issue_id}/attachments/{filename}", response_class=HTMLResponse)
async def delete_attachment(request: Request, issue_id: str, filename: str):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404)
    store.remove_attachment(zip_path, filename)
    attachments = store.list_attachments(zip_path)
    return templates.TemplateResponse(
        request,
        "issues/_attachments.html",
        {"issue_id": issue_id, "attachments": attachments},
    )


@router.get("/{issue_id}/attachments/{filename}")
async def download_attachment(issue_id: str, filename: str):
    zip_path = _zip_path(issue_id)
    try:
        data = store.get_file_from_zip(zip_path, f"attachments/{filename}")
    except Exception:
        raise HTTPException(404)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Delete Issue ─────────────────────────────────────────────────────────────

@router.post("/{issue_id}/sign")
async def sign_issue(request: Request, issue_id: str):
    zip_path = _zip_path(issue_id)
    if not zip_path.exists():
        raise HTTPException(404)
    meta, _ = store.read_issue(zip_path)
    if meta.get("signed_at"):
        raise HTTPException(403, "Already signed")
    if meta.get("type") != "report":
        raise HTTPException(400, "Only report issues can be signed")

    png_bytes = await request.body()
    if not png_bytes:
        raise HTTPException(400, "No signature data")

    from datetime import datetime, timezone
    meta["signed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.save_signature(zip_path, png_bytes)

    _, body = store.read_issue(zip_path)
    store.write_issue(zip_path, meta, body)

    # add_attachment overwrites an existing report.pdf; user-attached PDFs stay
    try:
        from ..services.pdf_export import build_issue_pdf
        pdf_bytes = build_issue_pdf(meta, body, png_bytes, get_config().site_name)
        store.add_attachment(zip_path, "report.pdf", pdf_bytes)
    except Exception:
        pass

    db = await get_db()
    await upsert_issue(db, meta, str(zip_path))
    await db.commit()
    asyncio.create_task(push_issue(get_config(), zip_path))
    return JSONResponse({"ok": True, "signed_at": meta["signed_at"]})


@router.delete("/{issue_id}")
async def delete_issue(issue_id: str):
    zip_path = _zip_path(issue_id)
    if zip_path.exists():
        meta, _ = store.read_issue(zip_path)
        if meta.get("type") == "report":
            raise HTTPException(403, "Report issues cannot be deleted")
        archive_dir = zip_path.parent / "archive"
        archive_dir.mkdir(exist_ok=True)
        zip_path.rename(archive_dir / zip_path.name)
    db = await get_db()
    await delete_issue_from_index(db, issue_id)
    asyncio.create_task(push_delete(get_config(), issue_id))
    return HTMLResponse("")

