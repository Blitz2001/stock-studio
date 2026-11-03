"""Sales feedback loop.

Import the sales/download CSV exports from Adobe Stock and Freepik, match each sale back
to the asset that made it, report which topics, styles and lanes earn most, and write
weights.json that the demand scout uses to lean the next batch toward what sells.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from ..config import Settings
from ..models import Status
from ..store import Store

# Column names differ between platforms and change over time; first match wins.
# Override with --map field=Column on the CLI if your export uses something else.
COLUMN_CANDIDATES = {
    "sale_date": ["date", "sale date", "download date", "license date", "created"],
    "filename": ["original filename", "original name", "filename", "file name", "file"],
    "title": ["title", "asset title", "file title", "content title", "name"],
    "earnings": ["royalty", "earnings", "your earnings", "revenue", "amount", "commission", "usd", "royalty (usd)"],
    "downloads": ["downloads", "quantity", "count", "licenses"],
}

PRIOR_ASSETS = 3.0    # smoothing: a topic needs a few assets before its weight moves much


def _pick(columns: list[str], wanted: list[str]) -> str | None:
    lower = {c.lower().strip(): c for c in columns}
    for w in wanted:
        if w in lower:
            return lower[w]
    return None


def read_sales_csv(path: str | Path, platform: str, mapping: dict[str, str] | None = None) -> list[dict]:
    p = Path(path)
    sep = ";" if p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()[0].count(";") > 1 else ","
    df = pd.read_csv(p, sep=sep, encoding="utf-8-sig")
    cols = {f: (mapping or {}).get(f) or _pick(list(df.columns), cands) for f, cands in COLUMN_CANDIDATES.items()}
    if not cols["filename"] and not cols["title"]:
        raise ValueError(f"Can't find a filename or title column in {p.name}: {list(df.columns)}. "
                         "Use --map filename=<column>.")
    rows = []
    for i, r in df.iterrows():
        def val(field):
            c = cols[field]
            v = r[c] if c else None
            return None if v is None or (isinstance(v, float) and pd.isna(v)) else v
        earnings = val("earnings")
        if isinstance(earnings, str):
            earnings = float(re.sub(r"[^0-9.\-]", "", earnings) or 0)
        row = {"platform": platform, "sale_date": str(val("sale_date") or ""),
               "filename": str(val("filename") or ""), "title": str(val("title") or ""),
               "earnings": float(earnings or 0), "downloads": int(val("downloads") or 1)}
        row["import_key"] = hashlib.sha1(f"{platform}|{p.name}|{i}|{json.dumps(row, sort_keys=True)}".encode()).hexdigest()
        rows.append(row)
    return rows


def match_assets(rows: list[dict], store: Store) -> list[dict]:
    by_file = store.filename_index()
    assets = {a.id: a for a in store.list()}
    by_title = {a.title.lower().strip(): a.id for a in assets.values() if a.title}
    by_short = {a.id[:8]: a.id for a in assets.values()}
    for r in rows:
        fn = Path(r["filename"]).name
        aid = by_file.get(fn)
        if not aid:
            m = re.search(r"-([0-9a-f]{8})\.\w+$", fn)
            aid = by_short.get(m.group(1)) if m else None
        if not aid and r["title"]:
            aid = by_title.get(r["title"].lower().strip())
        r["asset_id"] = aid
    return rows


def import_sales(path: str | Path, platform: str, store: Store, mapping: dict[str, str] | None = None) -> tuple[int, int]:
    rows = match_assets(read_sales_csv(path, platform, mapping), store)
    added = store.add_sales(rows)
    matched = sum(1 for r in rows if r["asset_id"])
    return added, matched


def performance(store: Store) -> dict[str, pd.DataFrame]:
    """Earnings per lane/topic/style, normalised by how many assets you exported there."""
    assets = pd.DataFrame([{"asset_id": a.id, "lane": a.lane.value, "topic": a.topic or "(none)",
                            "style": a.style or "(none)"} for a in store.list(Status.EXPORTED)])
    sales = pd.DataFrame(store.sales())
    out: dict[str, pd.DataFrame] = {}
    if assets.empty:
        return out
    if sales.empty:
        sales = pd.DataFrame(columns=["asset_id", "earnings", "downloads", "platform"])
    per_asset = sales.dropna(subset=["asset_id"]).groupby("asset_id")[["earnings", "downloads"]].sum()
    df = assets.merge(per_asset, left_on="asset_id", right_index=True, how="left").fillna(
        {"earnings": 0.0, "downloads": 0})
    for dim in ("lane", "topic", "style"):
        g = df.groupby(dim).agg(assets=("asset_id", "count"), downloads=("downloads", "sum"),
                                earnings=("earnings", "sum"))
        g["earnings_per_asset"] = (g["earnings"] / g["assets"]).round(3)
        g["downloads_per_asset"] = (g["downloads"] / g["assets"]).round(3)
        out[dim] = g.sort_values("earnings_per_asset", ascending=False)
    out["top_assets"] = df.sort_values("earnings", ascending=False).head(20)
    out["unmatched_sales"] = sales[sales["asset_id"].isna()] if "asset_id" in sales else sales
    return out


def compute_weights(perf: dict[str, pd.DataFrame]) -> dict:
    """Smoothed ratio of each group's earnings-per-asset to the portfolio average, clipped 0.5-2.0."""
    weights: dict[str, dict[str, float]] = {}
    for dim, key in (("topic", "topics"), ("lane", "lanes"), ("style", "styles")):
        g = perf.get(dim)
        if g is None or g.empty:
            continue
        overall = g["earnings"].sum() / max(1, g["assets"].sum())
        if overall <= 0:
            continue
        smoothed = (g["earnings"] + PRIOR_ASSETS * overall) / (g["assets"] + PRIOR_ASSETS)
        weights[key] = {str(k).lower(): round(float(min(2.0, max(0.5, v / overall))), 3)
                        for k, v in smoothed.items()}
    return weights


def update_weights(settings: Settings, store: Store) -> dict:
    weights = compute_weights(performance(store))
    p = settings.dir("analytics") / "weights.json"
    p.write_text(json.dumps(weights, indent=2))
    return weights
