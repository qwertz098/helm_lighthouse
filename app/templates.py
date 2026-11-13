import os
import re
import subprocess
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .config import get_config

templates = Jinja2Templates(directory="templates")

def _site_name() -> str:
    try:
        return get_config().site_name
    except Exception:
        return "Helm"

def _app_mode() -> str:
    try:
        return get_config().mode
    except Exception:
        return "helm"

def _safe_url(url: str) -> str:
    """Blocks javascript:/data: etc. in href/src; scheme-less hosts get https://."""
    url = (url or "").strip()
    # "/path" (same host, e.g. a reverse-proxied stream) and "//host/path" are http(s) too
    if url.lower().startswith(("http://", "https://", "/")):
        return url
    # any other scheme (javascript:, data:, vbscript:) — but "host:8080" is a port
    if not url or re.match(r"[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):
        return "about:blank"
    return "https://" + url

templates.env.filters["safe_url"] = _safe_url



def _release_version() -> str:
    """Release shown in the UI: APP_RELEASE (set at image build time), else
    `git describe` for a source checkout, else "dev"."""
    release = os.environ.get("APP_RELEASE", "").strip()
    if release:
        return release
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=2,
        )
        return out.stdout.strip() or "dev"
    except Exception:
        return "dev"


templates.env.globals["app_release"] = _release_version()
templates.env.globals["site_name"] = _site_name
templates.env.globals["app_mode"] = _app_mode


def _tile_area(tile: dict) -> str:
    from .services.areas import area_of
    return area_of(tile, get_config().tile_areas)

templates.env.globals["tile_area"] = _tile_area

from .services.areas import LABELS as _AREA_LABELS
templates.env.globals["area_labels"] = _AREA_LABELS
