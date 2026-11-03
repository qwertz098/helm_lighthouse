from ..templates import templates
import asyncio
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from ..config import get_config
from ..services.lighthouse_client import push_dashboard as _push_dashboard
from ..services.dashboard_store import (
    add_entry,
    delete_entry,
    load,
    reorder,
    save_raw,
    update_entry,
)

router = APIRouter(prefix="/dashboard")

_OG_MAX_ENTRIES = 256
_OG_TTL_OK = 24 * 3600
_OG_TTL_FAIL = 300           # retry unreachable devices after 5 min
_og_cache: dict[str, tuple[float, str]] = {}   # page URL -> (expiry, cached preview path or "")


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


class _PreviewImages(HTMLParser):
    """Collect preview image candidates from a page's <meta>/<link> tags, best first."""

    def __init__(self):
        super().__init__()
        self.meta: list[str] = []
        self.touch: list[str] = []
        self.icons: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta" and (a.get("property") or a.get("name", "")).lower() in ("og:image", "twitter:image"):
            if a.get("content"):
                self.meta.append(a["content"])
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower().split()
            if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
                self.touch.append(a["href"])
            elif "icon" in rel:
                size = max((int(x) for x in a.get("sizes", "").replace("x", " ").split() if x.isdigit()), default=0)
                self.icons.append((size, a["href"]))

    def candidates(self) -> list[str]:
        return self.meta + self.touch + [h for _, h in sorted(self.icons, reverse=True)]


async def _preview_candidates(url: str) -> list[str]:
    """Image URLs worth trying for a link tile, best first; the device's favicon.ico last."""
    found = []
    try:
        # verify=False: device web UIs usually have self-signed certificates
        async with httpx.AsyncClient(timeout=5, follow_redirects=True, verify=False,
                                     headers={"User-Agent": "Helm/1.0"}) as client:
            async with client.stream("GET", url) as resp:
                base = str(resp.url)
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= 65536:
                        break
        parser = _PreviewImages()
        parser.feed(b"".join(chunks).decode("utf-8", errors="ignore"))
        found = [urljoin(base, c) for c in parser.candidates()]
    except Exception:
        base = url
    p = urlsplit(base)
    found.append(f"{p.scheme}://{p.netloc}/favicon.ico")
    return [c for c in dict.fromkeys(found) if c.lower().startswith(("http://", "https://"))]


def _first_image(candidates: list[str]) -> str:
    from ..services.image_cache import get_or_fetch
    for c in candidates:
        if path := get_or_fetch(c, preview=True):
            return str(path)
    return ""


@router.get("/og-image")
async def og_image(url: str):
    """Preview for a link tile, fetched and cached by Helm (the browser may not reach the device)."""
    if not url.lower().startswith(("http://", "https://")) or url not in _known_urls("url"):
        raise HTTPException(404)
    now = time.monotonic()
    hit = _og_cache.get(url)
    if hit is None or now >= hit[0]:
        candidates = await _preview_candidates(url)
        path = await asyncio.get_running_loop().run_in_executor(None, _first_image, candidates)
        if len(_og_cache) >= _OG_MAX_ENTRIES:
            _og_cache.pop(next(iter(_og_cache)))
        _og_cache[url] = (now + (_OG_TTL_OK if path else _OG_TTL_FAIL), path)
    path = _og_cache[url][1]
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


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


def _entry(entry_id: str) -> dict | None:
    return next((e for e in load(_path())[0] if e["id"] == entry_id), None)


@router.get("/bg/{name}")
async def uploaded_bg(name: str):
    """A tile background picture uploaded through the UI."""
    from ..services.image_cache import upload_path
    if not (path := upload_path(name)):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@router.post("/entries/{entry_id}/bg", response_class=HTMLResponse)
async def upload_bg(request: Request, entry_id: str, file: UploadFile = File(...)):
    from ..services.image_cache import MAX_BYTES, delete_upload, save_upload
    if not (e := _entry(entry_id)):
        raise HTTPException(404)
    data = await file.read(MAX_BYTES + 1)
    try:
        bg = await asyncio.get_running_loop().run_in_executor(None, save_upload, data)
    except ValueError as err:
        raise HTTPException(400, str(err))
    delete_upload(e.get("bg_image", ""))
    entries = update_entry(_path(), entry_id, {"bg_image": bg})
    _schedule_push()
    return _tiles(request, entries)


@router.delete("/entries/{entry_id}", response_class=HTMLResponse)
async def remove_entry(request: Request, entry_id: str):
    from ..services.image_cache import delete_upload
    if e := _entry(entry_id):
        delete_upload(e.get("bg_image", ""))
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
    from ..services.image_cache import delete_upload, invalidate
    if (e := _entry(entry_id)) and e.get("bg_image") and e["bg_image"] != bg_image:
        invalidate(e["bg_image"])
        delete_upload(e["bg_image"])
    updates = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                   username=username, password=password,
                   remarks=remarks, group=group, chart_views=chart_views,
                   enabled=(enabled.lower() == "true"))
    entries = update_entry(_path(), entry_id, updates)
    _schedule_push()
    return _tiles(request, entries)


class _OrderItem(BaseModel):
    id: str
    group: str


@router.post("/order", status_code=204)
async def save_order(items: list[_OrderItem]):
    """Persist drag & drop order; the page already shows it, so nothing is re-rendered."""
    reorder(_path(), [(i.id, i.group) for i in items])
    _schedule_push()
    return Response(status_code=204)
