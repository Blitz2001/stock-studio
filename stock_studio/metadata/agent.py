"""Metadata agent: title, ranked keywords, category and AI/fictional flags.

Adobe Stock gives the first keywords the most weight, so keywords are ranked by
relevance. Everything is compliance-scanned; blocked keywords are dropped automatically,
a blocked title or prompt stops the asset.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import Settings
from ..llm.base import LLMProvider
from ..models import ADOBE_CATEGORIES, Asset, Lane
from .compliance import ComplianceResult, default_scanner

METADATA_PROMPT = """You write metadata for a stock {kind} that will be sold on Adobe Stock and Freepik.
Context from the producer: {context}
Topic: {topic}
Seed keywords: {seeds}

Rules:
- Title: one natural, descriptive English sentence, max 70 characters. Say what is shown, where,
  and the mood/concept. No keyword lists, no quotes{title_rule}.
- Keywords: 45-49 English keywords ranked by importance. The first 10 must be the most specific,
  most-searched terms (subject, action, setting). Then concepts, mood, colours, composition terms
  (e.g. "copy space", "nobody", "top view"), and broader categories. Single words or 2-word phrases.
- Never use brand names, product names, real people's names, artist names, copyrighted characters,
  camera/AI tool names, or "in the style of".
- Category: the best Adobe Stock category id from: {categories}
Return JSON only: {{"title": "...", "keywords": ["..."], "category": <int>,
"people_present": true|false, "property_present": true|false}}"""

GENERIC = {
    Lane.MY_PHOTOS: ["photography", "real", "authentic", "travel", "culture", "lifestyle", "outdoors",
                     "sri lanka", "south asia", "asia", "tropical", "color image", "horizontal", "daytime"],
    Lane.CODE_VECTORS: ["vector", "illustration", "graphic", "design element", "flat design", "editable",
                        "modern", "simple", "collection", "set", "isolated", "template", "background",
                        "web", "app", "symbol", "sign", "minimal", "creative", "layout"],
    Lane.AI_IMAGES: ["concept", "modern", "lifestyle", "people", "realistic", "copy space", "background",
                     "colorful", "bright", "professional"],
}

KEYWORD_CATEGORY_HINTS = [
    (8, {"pattern", "seamless", "icon", "vector", "template", "infographic", "background"}),
    (7, {"food", "curry", "rice", "fruit", "spices", "meal", "breakfast", "kottu", "hoppers"}),
    (4, {"tea", "coffee", "drink", "juice", "coconut water"}),
    (3, {"business", "office", "meeting", "team", "finance", "entrepreneur", "startup"}),
    (15, {"festival", "temple", "religion", "vesak", "ritual", "lantern", "christmas", "eid", "deepavali"}),
    (11, {"landscape", "mountain", "beach", "plantation", "valley", "sunset", "sunrise"}),
    (1, {"elephant", "bird", "animal", "wildlife", "peacock", "dog", "cat"}),
    (21, {"travel", "tourism", "vacation", "tourist"}),
    (19, {"technology", "smartphone", "laptop", "digital", "data"}),
    (13, {"people", "woman", "man", "family", "portrait", "child"}),
]


def guess_category(keywords: list[str], lane: Lane) -> int:
    kws = {k.lower() for k in keywords}
    for cat, hints in KEYWORD_CATEGORY_HINTS:
        if kws & hints:
            return cat
    return 8 if lane == Lane.CODE_VECTORS else 12


def normalise_keywords(raw: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for k in raw:
        k = re.sub(r"[^\w\s\-']", " ", str(k).lower()).strip()
        k = " ".join(k.split())
        if not k or len(k) > 40 or len(k.split()) > 3 or k in seen:
            continue
        seen.add(k)
        out.append(k)
        if len(out) >= limit:
            break
    return out


def trim_title(title: str, limit: int) -> str:
    title = " ".join(str(title).replace('"', "").split()).strip(" .,;")
    if len(title) <= limit:
        return title
    return title[:limit].rsplit(" ", 1)[0].rstrip(",;:-")


@dataclass
class MetadataResult:
    title: str
    keywords: list[str]
    category: int
    ai_generated: bool
    fictional: bool
    compliance: ComplianceResult
    removed_keywords: list[str] = field(default_factory=list)
    source: str = "template"

    @property
    def blocked(self) -> bool:
        return not self.compliance.ok


class MetadataAgent:
    def __init__(self, settings: Settings, llm: LLMProvider):
        self.settings, self.llm = settings, llm
        self.scanner = default_scanner()
        self.max_keywords = min(settings.get("platforms.adobe.max_keywords", 49),
                                settings.get("platforms.freepik.max_keywords", 50))
        self.max_title = min(settings.get("platforms.adobe.max_title_chars", 200),
                             settings.get("platforms.freepik.max_title_chars", 100))

    def _seeds(self, a: Asset) -> list[str]:
        from ..scout.demand import seed_keywords
        return seed_keywords(a.topic, a.prompt)

    def _from_llm(self, a: Asset) -> dict:
        kind = {Lane.MY_PHOTOS: "video" if a.is_video else "photo",
                Lane.CODE_VECTORS: "vector illustration", Lane.AI_IMAGES: "AI-generated image"}[a.lane]
        prompt = METADATA_PROMPT.format(
            kind=kind, context=(a.prompt or "none")[:500], topic=a.topic or "unknown",
            seeds=", ".join(self._seeds(a)),
            title_rule=", do not call it a photo or photograph" if a.lane == Lane.AI_IMAGES else "",
            categories="; ".join(f"{k}={v}" for k, v in ADOBE_CATEGORIES.items()),
        )
        return self.llm.complete_json(prompt, image_path=a.raster_path if self.llm.has_vision else None)

    def _from_template(self, a: Asset) -> dict:
        seeds = self._seeds(a)
        if a.lane == Lane.CODE_VECTORS:
            title = a.prompt.split(":")[0] if a.prompt else f"{a.topic} vector"
        else:
            title = a.prompt.split(".")[0] if a.prompt else (a.topic or "untitled")
        title = title.strip()
        return {"title": title[:1].upper() + title[1:], "keywords": [a.topic] + seeds + GENERIC[a.lane],
                "category": None}

    def run(self, a: Asset) -> MetadataResult:
        source = "template"
        data: dict = {}
        if self.llm.name != "offline":
            try:
                data = self._from_llm(a)
                source = self.llm.name
            except Exception as e:
                print(f"[metadata] LLM failed for {a.id}, using template: {e}")
        if not data.get("title") or not data.get("keywords"):
            data = self._from_template(a)
            source = "template"

        keywords = normalise_keywords(list(data.get("keywords", [])), 80)
        kept, removed = self.scanner.clean_keywords(keywords)
        kept = kept[: self.max_keywords]
        title = trim_title(data.get("title", ""), min(self.max_title, 100))
        cat = data.get("category")
        if not isinstance(cat, int) or cat not in ADOBE_CATEGORIES:
            cat = guess_category(kept, a.lane)

        ai = a.lane == Lane.AI_IMAGES
        # For AI images every person and place is invented, so "people and property are fictional"
        # is always true. It must never be set on your real photos.
        fictional = ai
        compliance = self.scanner.scan_asset_fields(prompt=a.prompt, title=title, keywords=kept)
        return MetadataResult(title=title, keywords=kept, category=cat, ai_generated=ai, fictional=fictional,
                              compliance=compliance, removed_keywords=removed, source=source)
