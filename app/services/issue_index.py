"""Build and maintain the SQLite index for issues."""
import json
from pathlib import Path

import aiosqlite

from ..services.issue_store import read_issue


async def sync_index(db: aiosqlite.Connection, issues_dir: Path) -> tuple[int, int]:
    """Scan issues_dir, sync index. Returns (added_or_updated, removed)."""
    zips = {p.stem: p for p in issues_dir.glob("issue-*.zip")}

    # Remove index entries for ZIPs no longer present
    async with db.execute("SELECT id, zip_path FROM issues") as cur:
        rows = await cur.fetchall()
    removed = 0
    for row in rows:
        if not Path(row["zip_path"]).exists():
            await db.execute("DELETE FROM issues WHERE id = ?", (row["id"],))
            removed += 1

    # Add/update entries
    added = 0
    for stem, zip_path in zips.items():
        issue_id = stem.removeprefix("issue-")
        meta, _ = read_issue(zip_path)
        if not meta.get("id"):
            continue
        await upsert_issue(db, meta, str(zip_path))
        added += 1

    await db.commit()
    return added, removed


async def upsert_issue(db: aiosqlite.Connection, meta: dict, zip_path: str):
    await db.execute(
        """
        INSERT INTO issues (id, title, status, priority, tags, due, created, modified, zip_path, origin_site, origin_id, type, signed_at)
        VALUES (:id, :title, :status, :priority, :tags, :due, :created, :modified, :zip_path, :origin_site, :origin_id, :type, :signed_at)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, status=excluded.status, priority=excluded.priority,
            tags=excluded.tags, due=excluded.due, modified=excluded.modified,
            zip_path=excluded.zip_path, origin_site=excluded.origin_site, origin_id=excluded.origin_id,
            type=excluded.type, signed_at=excluded.signed_at
        """,
        {
            "id": meta.get("id"),
            "title": meta.get("title", ""),
            "status": meta.get("status", "open"),
            "priority": meta.get("priority", "medium"),
            "tags": json.dumps(meta.get("tags") or [], ensure_ascii=False),
            "due": meta.get("due"),
            "created": meta.get("created", ""),
            "modified": meta.get("modified", ""),
            "zip_path": zip_path,
            "origin_site": meta.get("origin_site", ""),
            "origin_id": meta.get("origin_id", ""),
            "type": meta.get("type", "standard"),
            "signed_at": meta.get("signed_at"),
        },
    )


async def delete_issue_from_index(db: aiosqlite.Connection, issue_id: str):
    await db.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
    await db.commit()


async def query_issues(
    db: aiosqlite.Connection,
    *,
    status: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    origin_site: str | None = None,
    type: str | None = None,
    sort: str = "modified",
    order: str = "desc",
) -> list[dict]:
    conditions = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if tag:
        conditions.append("tags LIKE ?")
        params.append(f'%"{tag}"%')
    if search:
        conditions.append("title LIKE ?")
        params.append(f"%{search}%")
    if due_from:
        conditions.append("due >= ?")
        params.append(due_from)
    if due_to:
        conditions.append("due <= ?")
        params.append(due_to)
    if origin_site:
        conditions.append("origin_site = ?")
        params.append(origin_site)
    if type:
        conditions.append("type = ?")
        params.append(type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    allowed_sorts = {"modified", "created", "due", "priority", "title"}
    sort_col = sort if sort in allowed_sorts else "modified"
    sort_dir = "ASC" if order == "asc" else "DESC"

    sql = f"SELECT * FROM issues {where} ORDER BY {sort_col} {sort_dir}"
    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    result = []
    for row in rows:
        d = dict(row)
        try:
            d["tags"] = json.loads(d["tags"])
        except Exception:
            d["tags"] = []
        result.append(d)
    return result
