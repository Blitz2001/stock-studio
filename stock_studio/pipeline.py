"""Orchestrates the agent steps: QC -> duplicate guard -> metadata -> human review."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .dedupe.guard import DuplicateGuard, make_embedder
from .llm import get_provider
from .llm.base import LLMProvider
from .metadata.agent import MetadataAgent
from .metadata.compliance import default_scanner
from .models import Asset, Lane, Status
from .qc.agent import QCAgent
from .store import Store


@dataclass
class ProcessReport:
    checked: int = 0
    qc_failed: int = 0
    deferred: int = 0
    duplicates: int = 0
    compliance_failed: int = 0
    ready_for_review: int = 0
    notes: list[str] = field(default_factory=list)


class Studio:
    """One object holding settings, store and agents; used by the CLI and the dashboard."""

    def __init__(self, settings: Settings, llm: LLMProvider | None = None, embedder=None):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.llm = llm or get_provider(settings)
        self._embedder = embedder

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = make_embedder(self.settings.env_value("EMBEDDER", "clip"))
        return self._embedder

    def dedupe_threshold(self) -> float:
        key = "dedupe.clip_threshold" if self.embedder.name == "clip" else "dedupe.phash_threshold"
        return float(self.settings.get(key, 0.92))

    def guard(self) -> DuplicateGuard:
        return DuplicateGuard(self.store, self.embedder, self.dedupe_threshold())

    def process(self, limit: int | None = None) -> ProcessReport:
        rep = ProcessReport()
        new = self.store.list(Status.NEW)[: limit or None]
        qc, meta = QCAgent(self.settings, self.llm), MetadataAgent(self.settings, self.llm)
        passed: list[Asset] = []
        for a in new:
            rep.checked += 1
            r = qc.check(a)
            a.qc.update(r.data)
            a.qc["qc_warnings"] = r.warnings
            if r.upscale_to:
                a.qc["upscale_to"] = r.upscale_to
            if r.deferred:
                rep.deferred += 1
                self.store.upsert(a)
                continue
            if not r.passed:
                a.status = Status.QC_FAILED
                a.reasons = r.reasons + a.reasons
                rep.qc_failed += 1
                self.store.upsert(a)
                continue
            if a.lane == Lane.MY_PHOTOS and (r.people_present or r.property_present):
                a.needs_release = True
            a.reasons += [f"WARN {w}" for w in r.warnings]
            self.store.upsert(a)
            passed.append(a)

        if passed:
            hits = self.guard().check(passed)
            for a in passed:
                if a.id in hits:
                    h = hits[a.id]
                    a.status = Status.DUPLICATE
                    a.reasons.insert(0, f"near-duplicate of {h.duplicate_of} (similarity {h.similarity})")
                    rep.duplicates += 1
                    self.store.upsert(a)
            passed = [a for a in passed if a.id not in hits]

        for a in passed:
            m = meta.run(a)
            a.title, a.keywords, a.category = m.title, m.keywords, m.category
            a.ai_generated, a.fictional = m.ai_generated, m.fictional
            a.qc["metadata_source"] = m.source
            if m.removed_keywords:
                a.reasons.append(f"WARN removed banned keywords: {', '.join(m.removed_keywords)}")
            a.reasons += [f"WARN {w}" for w in m.compliance.warnings]
            if m.blocked:
                a.status = Status.COMPLIANCE_FAILED
                a.reasons = [f"compliance: {b}" for b in m.compliance.blocks] + a.reasons
                rep.compliance_failed += 1
            else:
                a.status = Status.PENDING_REVIEW
                rep.ready_for_review += 1
            self.store.upsert(a)
        return rep

    # ---- human decisions --------------------------------------------------------
    def approve(self, asset_id: str, title: str | None = None, keywords: list[str] | None = None,
                category: int | None = None, needs_release: bool | None = None) -> list[str]:
        """Approve after (optional) edits. Returns blocking problems; empty list = approved."""
        a = self.store.get(asset_id)
        if a is None:
            return ["unknown asset"]
        if title is not None:
            a.title = title.strip()
        if keywords is not None:
            a.keywords = keywords
        if category is not None:
            a.category = category
        if needs_release is not None:
            a.needs_release = needs_release
        res = default_scanner().scan_asset_fields(prompt=a.prompt, title=a.title, keywords=a.keywords)
        problems = [str(b) for b in res.blocks]
        max_kw = self.settings.get("platforms.adobe.max_keywords", 49)
        if len(a.keywords) > max_kw:
            problems.append(f"{len(a.keywords)} keywords; the limit is {max_kw}")
        if not a.title:
            problems.append("title is empty")
        if not problems:
            a.status = Status.APPROVED
        self.store.upsert(a)
        return problems

    def reject(self, asset_id: str, reason: str = "rejected in review") -> None:
        a = self.store.get(asset_id)
        if a:
            a.status = Status.REJECTED
            a.reasons.insert(0, reason)
            self.store.upsert(a)

    def requeue(self, asset_id: str) -> None:
        """Send a failed/deferred asset back through the pipeline (e.g. after adding an API key)."""
        a = self.store.get(asset_id)
        if a:
            a.status = Status.NEW
            a.reasons = [r for r in a.reasons if r.startswith("WARN") and "face" in r]
            self.store.upsert(a)
