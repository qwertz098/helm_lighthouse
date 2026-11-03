"""Download remote images, downscale, and cache them on disk.

Used for dashboard link-tile background images: the user supplies a URL,
we fetch it once, shrink it to a sane size, and serve the local copy.
"""
import hashlib
import io
import ssl
import time
import urllib.request
from pathlib import Path

from PIL import Image

MAX_WIDTH = 800          # downscale anything wider than this
MAX_BYTES = 8 * 1024 * 1024   # refuse to download more than 8 MB
JPEG_QUALITY = 80
ICON_MAX = 200           # images narrower than this are icons, not pictures
ICON_CANVAS = (480, 270)
ICON_BG = (241, 245, 249)   # #f1f5f9, the tile preview background


def _cache_dir() -> Path:
    from ..config import get_config
    d = get_config().dashboard_file.parent / "tile_bg"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def cached_path_for(url: str) -> Path:
    return _cache_dir() / f"{_key(url)}.jpg"


def get_or_fetch(url: str, *, preview: bool = False) -> Path | None:
    """Return the local cached (resized) image path, downloading if needed.

    preview=True is for automatic link-tile previews: devices often use self-signed
    certificates, icons are centred on a canvas instead of being blown up, and the
    copy is refreshed after a day.
    """
    # urllib would also open file:// and ftp:// URLs
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    dest = cached_path_for(url)
    if dest.exists() and not (preview and time.time() - dest.stat().st_mtime > 24 * 3600):
        return dest
    try:
        ctx = ssl._create_unverified_context() if preview else None
        req = urllib.request.Request(url, headers={"User-Agent": "Helm/1.0"})
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return None

        img = Image.open(io.BytesIO(data))
        img.load()
        # Flatten transparency / palette onto white (onto the tile colour for icons)
        icon = preview and img.width < ICON_MAX
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, ICON_BG if icon else (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")

        if icon:
            side = min(96, img.width * 2)
            img = img.resize((side, round(img.height * side / img.width)), Image.LANCZOS)
            canvas = Image.new("RGB", ICON_CANVAS, ICON_BG)
            canvas.paste(img, ((ICON_CANVAS[0] - img.width) // 2, (ICON_CANVAS[1] - img.height) // 2))
            img = canvas
        elif img.width > MAX_WIDTH:
            h = round(img.height * MAX_WIDTH / img.width)
            img = img.resize((MAX_WIDTH, h), Image.LANCZOS)

        img.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return dest
    except Exception:
        return None


def invalidate(url: str) -> None:
    try:
        p = cached_path_for(url)
        if p.exists():
            p.unlink()
    except Exception:
        pass
