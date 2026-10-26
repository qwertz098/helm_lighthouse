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

templates.env.globals["site_name"] = _site_name
templates.env.globals["app_mode"] = _app_mode
