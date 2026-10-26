from ..templates import templates
import asyncio
import re
import urllib.request

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..config import get_config
from ..services.lighthouse_client import push_dashboard as _push_dashboard
from ..services.dashboard_store import (
    add_entry,
    delete_entry,
    load,
    save_raw,
    update_entry,
)

router = APIRouter(prefix="/dashboard")

# simple in-process cache: url → og_image_url | ""
_og_cache: dict[str, str] = {}



def _fetch_og_image(url: str) -> str:
    """Synchronously fetch a URL and extract og:image. Returns "" on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Helm/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read(65536).decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
        return m.group(1) if m else ""
    except Exception:
        return ""


@router.get("/og-image")
async def og_image(url: str):
    if url not in _og_cache:
        _og_cache[url] = await asyncio.get_event_loop().run_in_executor(None, _fetch_og_image, url)
    img = _og_cache.get(url, "")
    if img:
        return RedirectResponse(img, status_code=302)
    raise HTTPException(404)


@router.get("/tile-bg")
async def tile_bg(url: str):
    """Serve a locally cached + downscaled copy of a tile background image."""
    from fastapi.responses import FileResponse
    from ..services.image_cache import get_or_fetch
    path = await asyncio.get_event_loop().run_in_executor(None, get_or_fetch, url)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


def _path():
    return get_config().dashboard_file


def _schedule_push():
    cfg = get_config()
    if cfg.lighthouses:
        asyncio.create_task(_push_dashboard(cfg))


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    entries, raw = load(_path())
    groups: dict[str, list] = {}
    for e in entries:
        if not e.get("enabled", True):
            continue
        g = e.get("group") or "General"
        groups.setdefault(g, []).append(e)
    return templates.TemplateResponse(
        request, "dashboard/dashboard.html",
        {"groups": groups, "raw": raw, "entry_count": len(entries)},
    )


@router.get("/raw", response_class=HTMLResponse)
async def get_raw(request: Request):
    _, raw = load(_path())
    return templates.TemplateResponse(
        request, "dashboard/_raw.html", {"raw": raw},
    )


@router.post("/raw", response_class=HTMLResponse)
async def post_raw(request: Request, raw: str = Form(...)):
    try:
        entries = save_raw(_path(), raw)
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    _schedule_push()
    groups: dict[str, list] = {}
    for e in entries:
        if not e.get("enabled", True):
            continue
        g = e.get("group") or "General"
        groups.setdefault(g, []).append(e)
    return templates.TemplateResponse(
        request, "dashboard/_tiles.html",
        {"groups": groups},
    )


@router.post("/entries", response_class=HTMLResponse)
async def create_entry(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    type: str = Form("link"),
    icon: str = Form(""),
    bg_image: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    remarks: str = Form(""),
    group: str = Form(""),
    chart_views: str = Form(""),
):
    entry = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                 username=username, password=password,
                 remarks=remarks, group=group, chart_views=chart_views, enabled=True)
    entries = add_entry(_path(), entry)
    _schedule_push()
    groups: dict[str, list] = {}
    for e in entries:
        if not e.get("enabled", True):
            continue
        g = e.get("group") or "General"
        groups.setdefault(g, []).append(e)
    return templates.TemplateResponse(request, "dashboard/_tiles.html", {"groups": groups})


@router.delete("/entries/{entry_id}", response_class=HTMLResponse)
async def remove_entry(request: Request, entry_id: str):
    entries = delete_entry(_path(), entry_id)
    _schedule_push()
    groups: dict[str, list] = {}
    for e in entries:
        if not e.get("enabled", True):
            continue
        g = e.get("group") or "General"
        groups.setdefault(g, []).append(e)
    return templates.TemplateResponse(request, "dashboard/_tiles.html", {"groups": groups})


@router.put("/entries/{entry_id}", response_class=HTMLResponse)
async def edit_entry(
    request: Request,
    entry_id: str,
    name: str = Form(...),
    url: str = Form(...),
    type: str = Form("link"),
    icon: str = Form(""),
    bg_image: str = Form(""),
    username: str = Form(""),
    password: str = Form(""),
    remarks: str = Form(""),
    group: str = Form(""),
    enabled: str = Form("true"),
    chart_views: str = Form(""),
):
    # If the background URL changed, drop the stale cached copy
    try:
        for _e in load(_path())[0]:
            if _e["id"] == entry_id and _e.get("bg_image") and _e.get("bg_image") != bg_image:
                from ..services.image_cache import invalidate
                invalidate(_e["bg_image"])
            break
    except Exception:
        pass
    updates = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                   username=username, password=password,
                   remarks=remarks, group=group, chart_views=chart_views,
                   enabled=(enabled.lower() == "true"))
    entries = update_entry(_path(), entry_id, updates)
    _schedule_push()
    groups: dict[str, list] = {}
    for e in entries:
        if not e.get("enabled", True):
            continue
        g = e.get("group") or "General"
        groups.setdefault(g, []).append(e)
    return templates.TemplateResponse(request, "dashboard/_tiles.html", {"groups": groups})


