import base64
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import load_config, get_config
from .db import get_db, close_db
from .routers import issues, docs, settings
from .services.issue_index import sync_index
from .services.notifier import start_scheduler


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Protect all web UI routes with HTTP Basic Auth.
    /api/sync/* is always exempt — it uses per-instance Bearer tokens instead.
    Auth is skipped entirely if admin_user / admin_password are not configured.
    """
    async def dispatch(self, request: Request, call_next):
        try:
            cfg = get_config()
        except Exception:
            return await call_next(request)
        if not cfg.admin_user or not cfg.admin_password:
            return await call_next(request)

        # Sync API stays open — protected by per-instance tokens
        if request.url.path.startswith("/api/sync"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="replace")
                username, _, password = decoded.partition(":")
                ok = (
                    secrets.compare_digest(username, cfg.admin_user)
                    and secrets.compare_digest(password, cfg.admin_password)
                )
                if ok:
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{cfg.site_name}"'},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    db = await get_db()
    await sync_index(db, cfg.issues_dir)

    if cfg.mode == "helm" and cfg.lighthouses:
        from .services.lighthouse_client import pull_changes, push_dashboard
        await pull_changes(cfg, db, cfg.issues_dir)
        await push_dashboard(cfg)

    scheduler = None
    if not cfg.disable_notifications:
        scheduler = start_scheduler(get_db, get_config)

    yield

    if scheduler:
        scheduler.cancel()
    await close_db()


import os as _os
_cfg_path = _os.environ.get("APP_CONFIG", "config.yaml")
try:
    import yaml as _yaml
    from pathlib import Path as _Path
    _raw = _yaml.safe_load(_Path(_cfg_path).read_text(encoding="utf-8")) if _Path(_cfg_path).exists() else {}
except Exception:
    _raw = {}

_is_lighthouse = (_raw or {}).get("mode") == "lighthouse"

app = FastAPI(title="Helm", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(issues.router)
app.include_router(docs.router)
app.include_router(settings.router)

if not _is_lighthouse:
    from .routers import dashboard as _dashboard
    app.include_router(_dashboard.router)
else:
    from .routers import sync as _sync
    app.include_router(_sync.router)


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    try:
        cfg = get_config()
        if cfg.mode == "lighthouse":
            return RedirectResponse("/issues")
    except Exception:
        pass
    return RedirectResponse("/dashboard")

