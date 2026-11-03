"""Demand scout: decides what to make this week.

Scores three sources of topics:
  * seasonal events 30-120 days out (buyers search ahead), with a bonus for Sri Lankan
    and South Asian events where good supply is thin,
  * evergreen business concepts,
  * underserved South Asian subjects,
then multiplies by what has actually sold for you (analytics/weights.json) and writes a
shot list / generation brief per topic and lane.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ..config import Settings, load_data_yaml
from ..metadata.compliance import default_scanner

REGION_BONUS = {"sri_lanka": 1.5, "south_asia": 1.3, "global": 1.0}
SOURCE_BASE = {"event": 1.0, "underserved": 0.9, "evergreen": 0.6}
IDEAL_LEAD_DAYS = 60


@dataclass
class Brief:
    id: str
    topic: str
    lane: str
    source: str                 # event | evergreen | underserved
    why: str
    shots: list[str]
    score: float
    seed_keywords: list[str] = field(default_factory=list)
    event_date: str | None = None
    date_is_approx: bool = False
    upload_by: str | None = None
    ai_prompts: list[str] = field(default_factory=list)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def next_occurrence(month: int, day: int, today: date) -> date:
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def lead_factor(days: int) -> float:
    return max(0.2, 1.0 - abs(days - IDEAL_LEAD_DAYS) / 90)


def load_weights(settings: Settings) -> dict:
    p = settings.workspace / "analytics" / "weights.json"
    return json.loads(p.read_text()) if p.exists() else {}


def ai_prompt_for(shot: str, topic: str) -> str:
    """A buyer-oriented, compliance-safe prompt. No names, brands or 'style of'."""
    context = "Sri Lanka" if "sri lank" in topic.lower() or "sri lank" in shot.lower() else ""
    place = f", set in {context}" if context else ""
    return (
        f"{shot}{place}. Authentic candid stock photograph, natural light, realistic skin "
        f"and hands, everyday clothing, uncluttered background with copy space, sharp focus, "
        f"no text, no logos, no watermarks, no brand names"
    )


def seed_keywords(topic: str, shot: str) -> list[str]:
    words = re.findall(r"[a-z]+(?:-[a-z]+)?", f"{topic} {shot}".lower())
    stop = {"and", "the", "a", "an", "of", "in", "on", "at", "with", "for", "to", "no", "by", "set", "without",
            "one", "consistent", "style", "filled", "outline", "duotone", "options", "from", "into", "your"}
    out: list[str] = []
    for w in words:
        if w not in stop and len(w) > 2 and w not in out:
            out.append(w)
    return out[:15]


class DemandScout:
    def __init__(self, settings: Settings, llm=None):
        self.settings = settings
        self.llm = llm
        self.calendar = load_data_yaml("calendar.yaml")["events"]
        topics = load_data_yaml("topics.yaml")
        self.evergreen = topics["evergreen"]
        self.underserved = topics["underserved"]
        self.weights = load_weights(settings)
        self.scanner = default_scanner()

    def _weight(self, topic: str, lane: str) -> float:
        tw = self.weights.get("topics", {}).get(topic.lower(), 1.0)
        lw = self.weights.get("lanes", {}).get(lane, 1.0)
        return float(tw) * float(lw)

    def candidates(self, today: date) -> list[Brief]:
        lo = self.settings.get("scout.lookahead_days_min", 30)
        hi = self.settings.get("scout.lookahead_days_max", 120)
        out: list[Brief] = []
        for ev in self.calendar:
            when = next_occurrence(ev["month"], ev["day"], today)
            days = (when - today).days
            if not lo <= days <= hi:
                continue
            approx = bool(ev.get("approx"))
            for lane in ev["lanes"]:
                score = SOURCE_BASE["event"] * REGION_BONUS[ev["region"]] * lead_factor(days) * self._weight(ev["name"], lane)
                why = f"{ev['name']} is {days} days away ({when:%d %b}{', approx - confirm date' if approx else ''}); buyers search 1-3 months ahead."
                if ev["region"] != "global":
                    why += " Local festival content is undersupplied."
                out.append(Brief(
                    id=f"{slug(ev['name'])}-{lane}", topic=ev["name"], lane=lane, source="event", why=why,
                    shots=list(ev["shots"]), score=score, event_date=when.isoformat(), date_is_approx=approx,
                    upload_by=(when - timedelta(days=30)).isoformat(),
                ))
        for source, items in (("evergreen", self.evergreen), ("underserved", self.underserved)):
            for t in items:
                for lane in t["lanes"]:
                    score = SOURCE_BASE[source] * self._weight(t["topic"], lane)
                    why = ("Evergreen buyer demand." if source == "evergreen"
                           else "Authentic South Asian content is still thin on stock sites.")
                    out.append(Brief(id=f"{slug(t['topic'])}-{lane}", topic=t["topic"], lane=lane, source=source,
                                     why=why, shots=list(t["shots"]), score=score))
        return out

    def weekly_briefs(self, today: date | None = None, n: int | None = None) -> list[Brief]:
        today = today or date.today()
        n = n or self.settings.get("scout.briefs_per_week", 12)
        rng = random.Random(self.settings.get("scout.seed"))
        cands = self.candidates(today)
        # small jitter so evergreen topics rotate week to week instead of always the same ones
        for b in cands:
            b.score = round(b.score * rng.uniform(0.9, 1.1), 4)
        cands.sort(key=lambda b: b.score, reverse=True)
        picked: list[Brief] = []
        per_topic: dict[str, int] = {}
        for b in cands:
            if per_topic.get(b.topic, 0) >= 2:      # keep variety
                continue
            picked.append(b)
            per_topic[b.topic] = per_topic.get(b.topic, 0) + 1
            if len(picked) >= n:
                break
        for b in picked:
            self._finish(b)
        return picked

    def _finish(self, b: Brief) -> None:
        if self.llm is not None and getattr(self.llm, "name", "offline") != "offline":
            b.shots = self._llm_shots(b) or b.shots
        b.shots = [s for s in b.shots if self.scanner.scan_text(s).ok][:5]
        b.seed_keywords = seed_keywords(b.topic, " ".join(b.shots))
        if b.lane == "ai_images":
            b.ai_prompts = [p for p in (ai_prompt_for(s, b.topic) for s in b.shots[:3])
                            if self.scanner.scan_text(p, "prompt").ok]

    def _llm_shots(self, b: Brief) -> list[str]:
        lane_hint = {
            "my_photos": "real photos/videos a contributor can shoot on a phone in Sri Lanka",
            "code_vectors": "vector icon sets, seamless patterns or infographic templates",
            "ai_images": "photorealistic images of fictional people and places",
        }[b.lane]
        prompt = (
            f"You are a stock-photo market analyst. Topic: '{b.topic}'. Lane: {lane_hint}.\n"
            f"Existing ideas: {b.shots}.\n"
            "Suggest 5 specific, commercially useful shots that buyers actively search for and that are "
            "under-supplied. Prefer authentic South Asian / Sri Lankan subjects where relevant. Never mention "
            "brands, real people, artists, copyrighted characters or 'in the style of'. "
            'Return JSON: {"shots": ["...", ...]}'
        )
        try:
            shots = self.llm.complete_json(prompt).get("shots", [])
            return [str(s) for s in shots if isinstance(s, str)]
        except Exception as e:  # network/quota errors shouldn't stop the scout
            print(f"[scout] LLM expansion skipped for {b.topic}: {e}")
            return []


def write_briefs(briefs: list[Brief], settings: Settings, today: date | None = None) -> Path:
    today = today or date.today()
    y, w, _ = today.isocalendar()
    out_dir = settings.dir("briefs")
    stem = out_dir / f"{y}-W{w:02d}"
    stem.with_suffix(".json").write_text(json.dumps([asdict(b) for b in briefs], indent=2))
    lines = [f"# Stock Studio briefs - week {y}-W{w:02d}", ""]
    for i, b in enumerate(briefs, 1):
        lines += [f"## {i}. {b.topic} - {b.lane}  (score {b.score:.2f})", f"_{b.why}_", ""]
        if b.upload_by:
            lines.append(f"**Upload by:** {b.upload_by}")
        lines.append("**Shot list:**")
        lines += [f"- [ ] {s}" for s in b.shots]
        if b.ai_prompts:
            lines.append("**AI prompts (compliance-checked):**")
            lines += [f"- `{p}`" for p in b.ai_prompts]
        lines += [f"**Seed keywords:** {', '.join(b.seed_keywords)}", ""]
    stem.with_suffix(".md").write_text("\n".join(lines))
    return stem.with_suffix(".json")


def load_briefs(path: Path) -> list[Brief]:
    return [Brief(**d) for d in json.loads(Path(path).read_text())]
