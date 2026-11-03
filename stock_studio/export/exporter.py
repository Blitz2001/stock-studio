"""Batch export: upload-ready files + metadata CSVs, capped per platform per ISO week.

Only assets YOU approved in the dashboard are exported. Nothing is uploaded: you upload
the batch folder yourself (Adobe Stock contributor portal / Freepik), then tick the AI and
release boxes listed in CHECKLIST.md.
"""
from __future__ import annotations

import csv
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageFilter

from ..config import Settings
from ..models import Asset, Lane, Status
from ..qc.agent import required_upscale
from ..store import Store

PLATFORMS = ("adobe", "freepik")
GPS_TAG = 0x8825


def iso_week(d: date | None = None) -> str:
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def safe_name(a: Asset) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (a.title or a.topic or "asset").lower()).strip("-")[:50].strip("-")
    return f"{s or 'asset'}-{a.id[:8]}"


def prepare_raster(src: str, dst: Path, settings: Settings, strip_gps: bool) -> Path:
    with Image.open(src) as im:
        exif = im.getexif()
        im = im.convert("RGB")
        factor = required_upscale(*im.size, settings)
        if factor > 1.0:
            if factor > settings.get("export.max_upscale_factor", 2.0):
                raise ValueError(f"{src} needs {factor:.2f}x upscale - over the limit")
            new = (round(im.width * factor) + 1, round(im.height * factor) + 1)
            im = im.resize(new, Image.Resampling.LANCZOS).filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=40, threshold=2))
        if strip_gps and GPS_TAG in exif:
            del exif[GPS_TAG]
        dst = dst.with_suffix(".jpg")
        im.save(dst, "JPEG", quality=95, subsampling=0, exif=exif.tobytes())
    return dst


@dataclass
class ExportReport:
    platform: str
    week: str
    exported: list[str] = field(default_factory=list)
    batches: list[str] = field(default_factory=list)
    deferred: int = 0                # approved but over this week's cap
    errors: list[tuple[str, str]] = field(default_factory=list)
    remaining_cap: int = 0


class Exporter:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store

    def candidates(self, platform: str) -> list[Asset]:
        done = self.store.exported_ids(platform)
        pool = self.store.list(Status.APPROVED) + self.store.list(Status.EXPORTED)
        return [a for a in pool if a.id not in done]

    def remaining(self, platform: str, week: str | None = None) -> int:
        cap = int(self.settings.get("export.weekly_cap", 100))
        return max(0, cap - self.store.exported_count(platform, week or iso_week()))

    def export(self, platform: str, today: date | None = None) -> ExportReport:
        assert platform in PLATFORMS
        week = iso_week(today)
        rep = ExportReport(platform, week)
        todo = self.candidates(platform)
        room = self.remaining(platform, week)
        rep.deferred = max(0, len(todo) - room)
        todo = todo[:room]
        size = int(self.settings.get("export.batch_size", 50))
        week_dir = self.settings.dir(f"exports/{week}/{platform}")
        existing = len([p for p in week_dir.iterdir() if p.is_dir()])
        for b in range(0, len(todo), size):
            chunk = todo[b : b + size]
            bdir = week_dir / f"batch_{existing + b // size + 1:02d}"
            bdir.mkdir(parents=True, exist_ok=True)
            rows = []
            for a in chunk:
                try:
                    fname = self._write_files(a, bdir, platform)
                except Exception as e:
                    rep.errors.append((a.id, str(e)))
                    continue
                rows.append((a, fname))
                self.store.record_export(a.id, platform, week, bdir.name, fname)
                if a.status != Status.EXPORTED:
                    a.status = Status.EXPORTED
                a.exported_batch = f"{week}/{platform}/{bdir.name}"
                self.store.upsert(a)
                rep.exported.append(a.id)
            if rows:
                (self._adobe_csv if platform == "adobe" else self._freepik_csv)(rows, bdir)
                self._checklist(rows, bdir, platform)
                rep.batches.append(str(bdir))
        rep.remaining_cap = self.remaining(platform, week)
        return rep

    # -- files ----------------------------------------------------------------------
    def _write_files(self, a: Asset, bdir: Path, platform: str) -> str:
        stem = bdir / safe_name(a)
        if a.lane == Lane.CODE_VECTORS:
            eps = Path(a.qc["eps"])
            shutil.copy(eps, stem.with_suffix(".eps"))
            shutil.copy(a.preview_path, stem.with_suffix(".jpg"))
            if platform == "freepik":     # Freepik takes vectors as a ZIP of EPS + JPG preview
                z = stem.with_suffix(".zip")
                with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(stem.with_suffix(".eps"), stem.with_suffix(".eps").name)
                    zf.write(stem.with_suffix(".jpg"), stem.with_suffix(".jpg").name)
                stem.with_suffix(".eps").unlink()
                stem.with_suffix(".jpg").unlink()
                return z.name
            return stem.with_suffix(".eps").name
        if a.is_video:
            dst = stem.with_suffix(Path(a.path).suffix.lower())
            shutil.copy(a.path, dst)
            return dst.name
        strip = self.settings.get("export.strip_gps", True)
        return prepare_raster(a.path, stem, self.settings, strip).name

    # -- metadata -------------------------------------------------------------------
    def _adobe_csv(self, rows: list[tuple[Asset, str]], bdir: Path) -> None:
        with open(bdir / "adobe_stock_metadata.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])
            for a, fname in rows:
                w.writerow([fname, a.title, ", ".join(a.keywords), a.category or "", ""])

    def _freepik_csv(self, rows: list[tuple[Asset, str]], bdir: Path) -> None:
        cols = self.settings.get("platforms.freepik.csv_columns",
                                 ["Filename", "Title", "Keywords", "Prompt", "Model"])
        delim = self.settings.get("platforms.freepik.csv_delimiter", ";")
        with open(bdir / "freepik_metadata.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=delim)
            w.writerow(cols)
            for a, fname in rows:
                values = {"filename": fname, "title": a.title, "keywords": ", ".join(a.keywords),
                          "prompt": a.prompt if a.ai_generated else "",
                          "model": a.qc.get("generator", "") if a.ai_generated else ""}
                w.writerow([values.get(c.lower().replace(" ", ""), values.get(c.lower(), "")) for c in cols])

    def _checklist(self, rows: list[tuple[Asset, str]], bdir: Path, platform: str) -> None:
        ai = [f for a, f in rows if a.ai_generated]
        fict = [f for a, f in rows if a.fictional]
        rel = [f for a, f in rows if a.needs_release]
        lines = [f"# Upload checklist - {bdir.parent.parent.name} / {platform} / {bdir.name}", "",
                 f"{len(rows)} files. Upload the files, then import the metadata CSV.", ""]
        if platform == "adobe":
            lines += ["The Adobe CSV has no column for the AI flags, so set them in the upload form:", ""]
        lines += ["## Tick 'Created using generative AI tools'"] + ([f"- [ ] {f}" for f in ai] or ["- none"]) + [""]
        lines += ["## Tick 'People and property are fictional'"] + ([f"- [ ] {f}" for f in fict] or ["- none"]) + [""]
        lines += ["## Attach a model/property release (or submit as editorial / don't submit)"]
        lines += ([f"- [ ] {f}" for f in rel] or ["- none"]) + [""]
        (bdir / "CHECKLIST.md").write_text("\n".join(lines))
