"""Compliance scan: banned names, brands, artists and style-copying phrases.

Runs on generation prompts *before* any image is generated, and again on titles and
keywords before anything is approved. Blocks are hard stops; warnings go to human review.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import DATA_DIR


@dataclass(frozen=True)
class Hit:
    term: str
    category: str
    field: str
    severity: str  # "block" | "warn"

    def __str__(self) -> str:
        return f"{self.field}: '{self.term}' ({self.category})"


@dataclass
class ComplianceResult:
    blocks: list[Hit] = field(default_factory=list)
    warnings: list[Hit] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocks

    def extend(self, other: "ComplianceResult") -> None:
        self.blocks.extend(other.blocks)
        self.warnings.extend(other.warnings)

    def summary(self) -> list[str]:
        return [f"BLOCK {h}" for h in self.blocks] + [f"WARN {h}" for h in self.warnings]


def normalise(text: str) -> str:
    """Lower-case, strip accents, drop possessives, turn punctuation into spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("’", "'").replace("`", "'")
    text = re.sub(r"'s\b", "", text)
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _token_variants(tok: str) -> set[str]:
    out = {tok}
    if tok.endswith("es") and len(tok) > 4:
        out.add(tok[:-2])
    if tok.endswith("s") and len(tok) > 3:
        out.add(tok[:-1])
    return out


class ComplianceScanner:
    def __init__(self, terms_path: Path | None = None, extra_block: list[str] | None = None):
        data = yaml.safe_load(Path(terms_path or DATA_DIR / "banned_terms.yaml").read_text())
        self._terms: list[tuple[tuple[str, ...], str, str]] = []  # (tokens, category, severity)
        for category, terms in (data.get("block") or {}).items():
            for t in terms or []:
                self._add(t, category, "block")
        for t in extra_block or []:
            self._add(t, "custom", "block")
        for t in data.get("warn") or []:
            self._add(t, "ambiguous_brand", "warn")
        self._patterns = [re.compile(p) for p in data.get("patterns") or []]

    def _add(self, term: str, category: str, severity: str) -> None:
        toks = tuple(normalise(term).split())
        if toks:
            self._terms.append((toks, category, severity))

    def scan_text(self, text: str, field_name: str = "text") -> ComplianceResult:
        res = ComplianceResult()
        norm = normalise(text or "")
        if not norm:
            return res
        tokens = norm.split()
        seen: set[str] = set()
        for toks, category, severity in self._terms:
            if self._matches(tokens, toks):
                name = " ".join(toks)
                if name in seen:
                    continue
                seen.add(name)
                hit = Hit(name, category, field_name, severity)
                (res.blocks if severity == "block" else res.warnings).append(hit)
        for pat in self._patterns:
            m = pat.search(norm)
            if m:
                res.blocks.append(Hit(m.group(0), "style_copying_phrase", field_name, "block"))
        # A word matched only as a warning but also as a block (e.g. "apple" inside a
        # blocked phrase) should not be reported twice.
        blocked = {h.term for h in res.blocks}
        res.warnings = [w for w in res.warnings if w.term not in blocked]
        return res

    @staticmethod
    def _matches(tokens: list[str], term: tuple[str, ...]) -> bool:
        n = len(term)
        joined_term = "".join(term)
        for i in range(len(tokens)):
            # 1) same token sequence, allowing a plural/possessive on the last word
            window = tokens[i : i + n]
            if len(window) == n and list(window[:-1]) == list(term[:-1]) and term[-1] in _token_variants(window[-1]):
                return True
            # 2) joined spelling: "cocacola", "spider-man" -> "spiderman" vs "spider man"
            for span in (1, 2, 3):
                if span == n and n == 1:
                    continue  # identical to case 1
                chunk = tokens[i : i + span]
                if len(chunk) != span:
                    continue
                if joined_term in _token_variants("".join(chunk)):
                    return True
        return False

    def scan_asset_fields(self, prompt: str = "", title: str = "",
                          keywords: list[str] | None = None) -> ComplianceResult:
        res = ComplianceResult()
        res.extend(self.scan_text(prompt, "prompt"))
        res.extend(self.scan_text(title, "title"))
        for kw in keywords or []:
            res.extend(self.scan_text(kw, "keyword"))
        return res

    def clean_keywords(self, keywords: list[str]) -> tuple[list[str], list[str]]:
        """Drop blocked keywords. Returns (kept, removed)."""
        kept, removed = [], []
        for kw in keywords:
            (removed if not self.scan_text(kw, "keyword").ok else kept).append(kw)
        return kept, removed


@lru_cache(maxsize=1)
def default_scanner() -> ComplianceScanner:
    return ComplianceScanner()
