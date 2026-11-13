from ..templates import templates
import asyncio
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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
_icon_cache: dict[str, tuple[float, bytes, str]] = {}   # page URL -> (expiry, icon bytes, media type)
_ICON_MAX_BYTES = 512 * 1024


def _valid_area(area: str) -> str:
    from ..services.areas import KEYS
    return area if area in KEYS else ""


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


class _PageImages(HTMLParser):
    """Collect image references from a page's <meta>/<link> tags."""

    def __init__(self):
        super().__init__()
        self.meta: list[str] = []
        self.touch: list[str] = []
        self.icons: list[tuple[int, str]] = []   # (declared size, href); SVG counts as large

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
                svg = "svg" in a.get("type", "").lower() or a["href"].lower().split("?")[0].endswith(".svg")
                size = max((int(x) for x in a.get("sizes", "").replace("x", " ").split() if x.isdigit()), default=0)
                self.icons.append((1024 if svg else size, a["href"]))


async def _page_images(url: str) -> tuple[str, _PageImages]:
    """Fetch the start of a tile's page; returns its final URL and the image references in it."""
    import httpx   # loaded on first use: not needed by installations without link tiles
    parser = _PageImages()
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
        parser.feed(b"".join(chunks).decode("utf-8", errors="ignore"))
    except Exception:
        base = url
    return base, parser


def _absolute(base: str, refs: list[str]) -> list[str]:
    urls = (urljoin(base, r) for r in refs)
    return [u for u in dict.fromkeys(urls) if u.lower().startswith(("http://", "https://"))]


def _first_preview(candidates: list[str]) -> str:
    from ..services.image_cache import get_preview
    for c in candidates:
        if path := get_preview(c):
            return str(path)
    return ""


@router.get("/og-image")
async def og_image(url: str):
    """Preview for a link tile, fetched and cached by Helm (the browser may not reach the device).

    Only a page's preview image or a large icon makes a preview; for anything else the
    tile shows the icon of its area instead of a blown-up favicon.
    """
    if not url.lower().startswith(("http://", "https://")) or url not in _known_urls("url"):
        raise HTTPException(404)
    now = time.monotonic()
    hit = _og_cache.get(url)
    if hit is None or now >= hit[0]:
        base, page = await _page_images(url)
        large_icons = [h for size, h in sorted(page.icons, reverse=True) if size >= 120]
        candidates = _absolute(base, page.meta + page.touch + large_icons)
        path = await asyncio.get_running_loop().run_in_executor(None, _first_preview, candidates)
        if len(_og_cache) >= _OG_MAX_ENTRIES:
            _og_cache.pop(next(iter(_og_cache)))
        _og_cache[url] = (now + (_OG_TTL_OK if path else _OG_TTL_FAIL), path)
    path = _og_cache[url][1]
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


async def _fetch_icon(candidates: list[str]) -> tuple[bytes, str]:
    import httpx
    async with httpx.AsyncClient(timeout=5, follow_redirects=True, verify=False,
                                 headers={"User-Agent": "Helm/1.0"}) as client:
        for c in candidates:
            try:
                resp = await client.get(c)
            except Exception:
                continue
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if resp.status_code == 200 and ctype.startswith("image/") and 0 < len(resp.content) <= _ICON_MAX_BYTES:
                return resp.content, ctype
    return b"", ""


@router.get("/favicon")
async def tile_favicon(url: str):
    """Icon for a link tile's header: the icon the page announces (SVG or the largest),
    else /favicon.ico. Fetched by Helm, so self-signed certificates and devices the
    browser cannot reach directly work too."""
    if not url.lower().startswith(("http://", "https://")) or url not in _known_urls("url"):
        raise HTTPException(404)
    now = time.monotonic()
    hit = _icon_cache.get(url)
    if hit is None or now >= hit[0]:
        base, page = await _page_images(url)
        p = urlsplit(base)
        refs = [h for _, h in sorted(page.icons, reverse=True)] + page.touch + [f"{p.scheme}://{p.netloc}/favicon.ico"]
        data, ctype = await _fetch_icon(_absolute(base, refs))
        if len(_icon_cache) >= _OG_MAX_ENTRIES:
            _icon_cache.pop(next(iter(_icon_cache)))
        _icon_cache[url] = (now + (_OG_TTL_OK if data else _OG_TTL_FAIL), data, ctype)
    _, data, ctype = _icon_cache[url]
    if not data:
        raise HTTPException(404)
    # served from Helm's origin: keep a device's SVG from running script if opened directly
    return Response(data, media_type=ctype, headers={"Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"})


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
    area: str = Form(""),
    chart_views: str = Form(""),
):
    entry = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                 username=username, password=password,
                 remarks=remarks, group=group, area=_valid_area(area), chart_views=chart_views, enabled=True)
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
    area: str = Form(""),
    enabled: str = Form("true"),
    chart_views: str = Form(""),
):
    from ..services.image_cache import delete_upload, invalidate
    if (e := _entry(entry_id)) and e.get("bg_image") and e["bg_image"] != bg_image:
        invalidate(e["bg_image"])
        delete_upload(e["bg_image"])
    updates = dict(name=name, url=url, type=type, icon=icon, bg_image=bg_image,
                   username=username, password=password,
                   remarks=remarks, group=group, area=_valid_area(area), chart_views=chart_views,
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
