import aiosqlite
from .config import get_config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        cfg = get_config()
        _db = await aiosqlite.connect(str(cfg.db_path))
        _db.row_factory = aiosqlite.Row
        await _init_schema(_db)
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def _init_schema(db: aiosqlite.Connection):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            priority TEXT NOT NULL DEFAULT 'medium',
            tags TEXT NOT NULL DEFAULT '[]',
            due TEXT,
            created TEXT NOT NULL,
            modified TEXT NOT NULL,
            zip_path TEXT NOT NULL,
            origin_site TEXT NOT NULL DEFAULT '',
            origin_id TEXT NOT NULL DEFAULT ''
        )
    """)
    # Migrate: add columns if missing (existing DBs)
    for col, defval in [
        ("origin_site", "TEXT NOT NULL DEFAULT ''"),
        ("origin_id",   "TEXT NOT NULL DEFAULT ''"),
        ("type",        "TEXT NOT NULL DEFAULT 'standard'"),
        ("signed_at",   "TEXT"),
    ]:
        try:
            await db.execute(f"ALTER TABLE issues ADD COLUMN {col} {defval}")
        except Exception:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS sync_instances (
            site_name TEXT PRIMARY KEY,
            site_id TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            token_hash TEXT NOT NULL,
            created TEXT NOT NULL,
            last_seen TEXT,
            revoked INTEGER NOT NULL DEFAULT 0,
            read_only INTEGER NOT NULL DEFAULT 0
        )
    """)
    for col, defval in [
        ("read_only", "INTEGER NOT NULL DEFAULT 0"),
        ("site_id",   "TEXT NOT NULL DEFAULT ''"),
    ]:
        try:
            await db.execute(f"ALTER TABLE sync_instances ADD COLUMN {col} {defval}")
        except Exception:
            pass
    await db.commit()
