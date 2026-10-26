from ..templates import templates
import asyncio
import re
import time
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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

_OG_MAX_ENTRIES = 256
_OG_TTL_OK = 24 * 3600
_OG_TTL_FAIL = 300           # retry unreachable devices after 5 min
_og_cache: dict[str, tuple[float, str]] = {}

_OG_RE = (
    re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I),
)


def _path():
    return get_config().dashboard_file


def _known_urls(field: str) -> set[str]:
    """Only URLs configured on a tile may be fetched server-side (no open SSRF proxy)."""
    entries, _ = load(_path())
    urls = set()
    for e in entries:
        u = e.get(field) or ""
        if field == "url" and u and "://" not in u:
            u = "https://" + u
        urls.add(u)
    return urls


async def _fetch_og_image(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True,
                                     headers={"User-Agent": "Helm/1.0"}) as client:
            async with client.stream("GET", url) as resp:
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= 65536:
                        break
        html = b"".join(chunks).decode("utf-8", errors="ignore")
        for rx in _OG_RE:
            if m := rx.search(html):
                return urljoin(url, m.group(1))
    except Exception:
        pass
    return ""


@router.get("/og-image")
async def og_image(url: str):
    if not url.lower().startswith(("http://", "https://")) or url not in _known_urls("url"):
        raise HTTPException(404)
    now = time.monotonic()
    hit = _og_cache.get(url)
    if hit is None or now >= hit[0]:
        img = await _fetch_og_image(url)
        if len(_og_cache) >= _OG_MAX_ENTRIES:
            _og_cache.pop(next(iter(_og_cache)))
        _og_cache[url] = (now + (_OG_TTL_OK if img else _OG_TTL_FAIL), img)
    img = _og_cache[url][1]
    if img.lower().startswith(("http://", "https://")):
        return RedirectResponse(img, status_code=302)
    raise HTTPException(404)


@router.get("/tile-bg")
async def tile_bg(url: str):
    """Serve a locally cached + downscaled copy of a tile background image."""
    from ..services.image_cache import get_or_fetch
    if not url or url not in _known_urls("bg_image"):
        raise HTTPException(404)
    path = await asyncio.get_running_loop().run_in_executor(None, get_or_fetch, url)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


def _schedule_push():
    cfg = get_config()
    if cfg.lighthouses:
        asyncio.create_task(_push_dashboard(cfg))


def _group(entries: list[dict]) -> dict[str, list]:
    groups: dict[str, list] = {}
    for e in entries:
        if e.get("enabled", True):
            groups.setdefault(e.get("group") or "General", []).append(e)
    return groups


def _tiles(request: Request, entries: list[dict]) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard/_tiles.html", {"groups": _group(entries)})


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    entries, raw = load(_path())
    return templates.TemplateResponse(
        request, "dashboard/dashboard.html",
        {"groups": _group(entries), "raw": raw, "entry_count": len(entries)},
    )


@router.get("/raw", response_class=HTMLResponse)
async def get_raw(request: Request):
    _, raw = load(_path())
    return templates.TemplateResponse(request, "dashboard/_raw.html", {"raw": raw})


@router.post("/raw", response_class=HTMLResponse)
async def post_raw(request: Request, raw: str = Form(...)):
    try:
        entries = save_raw(_path(), raw)
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    _schedule_push()
    return _tiles(request, entries)


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
    return _tiles(request, entries)


@router.delete("/entries/{entry_id}", response_class=HTMLResponse)
async def remove_entry(request: Request, entry_id: str):
    entries = delete_entry(_path(), entry_id)
    _schedule_push()
    return _tiles(request, entries)


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
    from ..services.image_cache import invalidate
    for e in load(_path())[0]:
        if e["id"] == entry_id:
            if e.get("bg_image") and e["bg_image"] != bg_image:
                invalidate(e["bg_image"])
            break
    updates = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                   username=username, password=password,
                   remarks=remarks, group=group, chart_views=chart_views,
                   enabled=(enabled.lower() == "true"))
    entries = update_entry(_path(), entry_id, updates)
    _schedule_push()
    return _tiles(request, entries)
