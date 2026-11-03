"""SQLite registry of every asset, embedding, export and sale."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import numpy as np

from .models import Asset, Lane, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    lane TEXT NOT NULL,
    status TEXT NOT NULL,
    preview_path TEXT,
    topic TEXT DEFAULT '',
    style TEXT DEFAULT '',
    set_id TEXT DEFAULT '',
    prompt TEXT DEFAULT '',
    title TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    category INTEGER,
    ai_generated INTEGER DEFAULT 0,
    fictional INTEGER DEFAULT 0,
    needs_release INTEGER DEFAULT 0,
    is_video INTEGER DEFAULT 0,
    reasons TEXT DEFAULT '[]',
    qc TEXT DEFAULT '{}',
    exported_batch TEXT DEFAULT '',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS embeddings (
    key TEXT PRIMARY KEY,          -- asset id, or 'history:<path>' for past uploads
    embedder TEXT NOT NULL,
    vector BLOB NOT NULL,
    source TEXT NOT NULL           -- 'asset' | 'history'
);
CREATE TABLE IF NOT EXISTS exports (
    asset_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    iso_week TEXT NOT NULL,
    batch TEXT NOT NULL,
    filename TEXT NOT NULL,
    exported_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, platform)
);
CREATE TABLE IF NOT EXISTS sales (
    platform TEXT NOT NULL,
    sale_date TEXT,
    filename TEXT,
    title TEXT,
    downloads INTEGER DEFAULT 1,
    earnings REAL DEFAULT 0,
    asset_id TEXT,
    import_key TEXT UNIQUE
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---- assets -------------------------------------------------------
    def upsert(self, a: Asset) -> None:
        if not a.created_at:
            a.created_at = now_iso()
        with self.conn() as c:
            c.execute(
                """INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET path=excluded.path, lane=excluded.lane,
                status=excluded.status, preview_path=excluded.preview_path, topic=excluded.topic,
                style=excluded.style, set_id=excluded.set_id, prompt=excluded.prompt,
                title=excluded.title, keywords=excluded.keywords, category=excluded.category,
                ai_generated=excluded.ai_generated, fictional=excluded.fictional,
                needs_release=excluded.needs_release, is_video=excluded.is_video,
                reasons=excluded.reasons, qc=excluded.qc, exported_batch=excluded.exported_batch""",
                (
                    a.id, a.path, a.lane.value, a.status.value, a.preview_path, a.topic, a.style,
                    a.set_id, a.prompt, a.title, json.dumps(a.keywords), a.category,
                    int(a.ai_generated), int(a.fictional), int(a.needs_release), int(a.is_video),
                    json.dumps(a.reasons), json.dumps(a.qc), a.exported_batch, a.created_at,
                ),
            )

    def get(self, asset_id: str) -> Asset | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return _row_to_asset(row) if row else None

    def list(self, status: Status | None = None, lane: Lane | None = None) -> list[Asset]:
        q, args = "SELECT * FROM assets WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status.value)
        if lane:
            q += " AND lane=?"
            args.append(lane.value)
        q += " ORDER BY created_at, id"
        with self.conn() as c:
            return [_row_to_asset(r) for r in c.execute(q, args).fetchall()]

    def counts(self) -> dict[str, int]:
        with self.conn() as c:
            rows = c.execute("SELECT status, COUNT(*) n FROM assets GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ---- embeddings ---------------------------------------------------
    def put_embedding(self, key: str, embedder: str, vec: np.ndarray, source: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                (key, embedder, np.asarray(vec, dtype=np.float32).tobytes(), source),
            )

    def embeddings(self, embedder: str, keys: list[str] | None = None,
                   source: str | None = None) -> dict[str, np.ndarray]:
        q, args = "SELECT key, vector FROM embeddings WHERE embedder=?", [embedder]
        if source:
            q += " AND source=?"
            args.append(source)
        with self.conn() as c:
            rows = c.execute(q, args).fetchall()
        out = {r["key"]: np.frombuffer(r["vector"], dtype=np.float32) for r in rows}
        if keys is not None:
            wanted = set(keys)
            out = {k: v for k, v in out.items() if k in wanted}
        return out

    # ---- exports ------------------------------------------------------
    def record_export(self, asset_id: str, platform: str, iso_week: str, batch: str, filename: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO exports VALUES (?,?,?,?,?,?)",
                (asset_id, platform, iso_week, batch, filename, now_iso()),
            )

    def exported_count(self, platform: str, iso_week: str) -> int:
        with self.conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM exports WHERE platform=? AND iso_week=?", (platform, iso_week)
            ).fetchone()[0]

    def exported_ids(self, platform: str) -> set[str]:
        with self.conn() as c:
            return {r[0] for r in c.execute("SELECT asset_id FROM exports WHERE platform=?", (platform,))}

    def filename_index(self) -> dict[str, str]:
        """Exported filename -> asset id, for matching sales reports back to assets."""
        with self.conn() as c:
            rows = c.execute("SELECT filename, asset_id FROM exports").fetchall()
        return {r["filename"]: r["asset_id"] for r in rows}

    # ---- sales --------------------------------------------------------
    def add_sales(self, rows: list[dict]) -> int:
        added = 0
        with self.conn() as c:
            for r in rows:
                cur = c.execute(
                    "INSERT OR IGNORE INTO sales VALUES (?,?,?,?,?,?,?,?)",
                    (r["platform"], r.get("sale_date"), r.get("filename"), r.get("title"),
                     int(r.get("downloads") or 1), float(r.get("earnings") or 0),
                     r.get("asset_id"), r["import_key"]),
                )
                added += cur.rowcount
        return added

    def sales(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM sales").fetchall()]


def _row_to_asset(r: sqlite3.Row) -> Asset:
    return Asset(
        id=r["id"], path=r["path"], lane=Lane(r["lane"]), status=Status(r["status"]),
        preview_path=r["preview_path"], topic=r["topic"], style=r["style"], set_id=r["set_id"],
        prompt=r["prompt"], title=r["title"], keywords=json.loads(r["keywords"]),
        category=r["category"], ai_generated=bool(r["ai_generated"]), fictional=bool(r["fictional"]),
        needs_release=bool(r["needs_release"]), is_video=bool(r["is_video"]),
        reasons=json.loads(r["reasons"]), qc=json.loads(r["qc"]),
        exported_batch=r["exported_batch"], created_at=r["created_at"],
    )
