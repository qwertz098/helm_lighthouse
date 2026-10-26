import re

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
    if url.lower().startswith(("http://", "https://")):
        return url
    # any other scheme (javascript:, data:, vbscript:) — but "host:8080" is a port
    if not url or re.match(r"[a-z][a-z0-9+.-]*:(?!\d)", url, re.I):
        return "about:blank"
    return "https://" + url

templates.env.filters["safe_url"] = _safe_url
templates.env.globals["site_name"] = _site_name
templates.env.globals["app_mode"] = _app_mode
