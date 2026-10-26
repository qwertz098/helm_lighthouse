"""Helm-side client: push issues to Lighthouse, pull back edits."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_STATE_FILE = "data/.lighthouse_state.json"


def _state_path() -> Path:
    return Path(_STATE_FILE)


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _push_issue_to(target, site_id: str, zip_path: Path) -> None:
    try:
        import httpx
        url = target.url.rstrip("/") + "/api/sync/issues"
        async with httpx.AsyncClient(timeout=10) as client:
            with open(zip_path, "rb") as f:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {target.token}"},
                    files={"zip_file": (zip_path.name, f, "application/zip")},
                    data={"site_id": site_id},
                )
        if resp.status_code not in (200, 201):
            log.warning("Lighthouse '%s' push failed: %s", target.name or target.url, resp.status_code)
    except Exception as e:
        log.debug("Lighthouse '%s' push error: %s", target.name or target.url, e)


async def push_issue(cfg, zip_path: Path) -> None:
    """POST a ZIP to all configured Lighthouse instances."""
    for target in cfg.lighthouses:
        if target.url and target.token:
            await _push_issue_to(target, cfg.site_id, zip_path)


async def push_delete(cfg, issue_id: str) -> None:
    """Notify all Lighthouses that an issue was archived."""
    try:
        import httpx
        for target in cfg.lighthouses:
            if not target.url or not target.token:
                continue
            url = target.url.rstrip("/") + f"/api/sync/issues/{issue_id}"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.delete(
                    url,
                    headers={"Authorization": f"Bearer {target.token}"},
                    params={"site": cfg.site_id},
                )
    except Exception as e:
        log.debug("Lighthouse delete notify error: %s", e)


async def push_dashboard(cfg) -> None:
    """Push dashboard.yaml to all configured Lighthouse instances as a backup."""
    dashboard_path = Path(cfg.dashboard_file)
    if not dashboard_path.exists():
        return
    content = dashboard_path.read_text(encoding="utf-8")
    try:
        import httpx
        for target in cfg.lighthouses:
            if not target.url or not target.token:
                continue
            url = target.url.rstrip("/") + "/api/sync/dashboard"
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {target.token}"},
                        data={"site_id": cfg.site_id, "content": content},
                    )
                if resp.status_code not in (200, 201):
                    log.warning("Lighthouse '%s' dashboard push failed: %s", target.name or target.url, resp.status_code)
            except Exception as e:
                log.debug("Lighthouse '%s' dashboard push error: %s", target.name or target.url, e)
    except Exception as e:
        log.debug("Dashboard push error: %s", e)


async def pull_changes(cfg, db, issues_dir: Path) -> None:
    """Pull issues changed on all Lighthouses since last pull, apply locally."""
    if not cfg.lighthouses:
        return
    try:
        import httpx
        from ..services.issue_index import upsert_issue
        from ..services.issue_store import is_safe_id, read_issue, rewrite_issue_meta

        state = _load_state()

        for target in cfg.lighthouses:
            if not target.url or not target.token:
                continue
            base = target.url.rstrip("/")
            since_key = f"last_pull_{target.url}"
            since = state.get(since_key, "1970-01-01T00:00:00+00:00")
            headers = {"Authorization": f"Bearer {target.token}"}

            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                resp = await client.get(
                    base + "/api/sync/issues",
                    params={"site": cfg.site_id, "since": since},
                )
                if resp.status_code != 200:
                    continue

                for item in resp.json():
                    issue_id = str(item.get("id", ""))
                    lh_local_id = str(item.get("local_id", ""))
                    # both end up in a file name / URL path
                    if not is_safe_id(issue_id) or not is_safe_id(lh_local_id):
                        continue
                    lh_modified = item.get("modified", "")

                    local_zip = issues_dir / f"issue-{issue_id}.zip"
                    if local_zip.exists():
                        meta, _ = read_issue(local_zip)
                        if meta.get("modified", "") >= lh_modified:
                            continue

                    # Build the URL ourselves so the token only goes to the configured host
                    dl = await client.get(f"{base}/api/sync/issues/{lh_local_id}/zip")
                    if dl.status_code != 200:
                        continue

                    local_zip.write_bytes(dl.content)
                    # The Lighthouse copy carries its own local id; restore ours
                    meta = rewrite_issue_meta(local_zip, {"id": issue_id}, remove=("origin_site", "origin_id"))
                    await upsert_issue(db, meta, str(local_zip))

            state[since_key] = _now_iso()

        await db.commit()
        _save_state(state)
    except Exception as e:
        log.debug("Lighthouse pull error: %s", e)
