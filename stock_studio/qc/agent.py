"""QC agent: reject weak files before a human reviewer (or Adobe's) ever sees them.

Two layers:
  1. Technical checks (always, offline): resolution per platform, sharpness, clipping,
     video duration/size.
  2. Vision check (LLM): anatomy errors, garbled text, logos/trademarks, watermarks,
     generation artifacts, resemblance to real/famous people, and people/property that
     need releases in your own photos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..config import Settings
from ..llm.base import LLMProvider
from ..models import Asset, Lane
from ..producers.my_photos import sharpness

Image.MAX_IMAGE_PIXELS = 300_000_000


@dataclass
class QCResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)   # reject reasons
    warnings: list[str] = field(default_factory=list)
    deferred: bool = False                              # vision check needed but unavailable
    upscale_to: float | None = None                     # factor needed to meet platform minimums
    people_present: bool = False
    property_present: bool = False
    data: dict = field(default_factory=dict)


def required_upscale(w: int, h: int, settings: Settings) -> float:
    """Smallest factor that satisfies every enabled platform's minimum size."""
    need = 1.0
    if settings.get("platforms.adobe.enabled", True):
        min_mp = settings.get("platforms.adobe.min_megapixels", 4.0)
        need = max(need, math.sqrt(min_mp * 1e6 / (w * h)))
    if settings.get("platforms.freepik.enabled", True):
        need = max(need, settings.get("platforms.freepik.min_shortest_side", 2000) / min(w, h))
    return round(need, 3)


def technical_checks(a: Asset, settings: Settings) -> QCResult:
    r = QCResult(passed=True)
    if a.is_video:
        info = a.qc.get("video", {})
        min_h = settings.get("platforms.adobe.video_min_height", 720)
        if info.get("height", 0) < min_h and info.get("width", 0) < min_h:
            r.reasons.append(f"video below {min_h}p ({info.get('width')}x{info.get('height')})")
        dur = info.get("duration_s", 0)
        if not 5 <= dur <= 60:
            r.reasons.append(f"video duration {dur}s outside 5-60s")
        r.passed = not r.reasons
        return r

    with Image.open(a.raster_path) as im:
        w, h = im.size
        arr = np.asarray(im.convert("L").resize((max(1, w * 1000 // max(w, h)), max(1, h * 1000 // max(w, h)))))
    r.data.update(width=w, height=h, megapixels=round(w * h / 1e6, 2))

    if a.lane != Lane.CODE_VECTORS:     # vector previews are rendered at any size we like
        factor = required_upscale(w, h, settings)
        max_f = settings.get("export.max_upscale_factor", 2.0)
        if factor > max_f:
            r.reasons.append(f"too small ({w}x{h}); needs {factor:.2f}x upscale, limit is {max_f}x")
        elif factor > 1.0:
            r.upscale_to = factor
            r.warnings.append(f"will be upscaled {factor:.2f}x on export")

        sharp = sharpness(arr)
        r.data["sharpness"] = round(sharp, 1)
        t = settings.get("qc.blur_threshold", 30.0)
        if a.lane == Lane.AI_IMAGES:
            t /= 3                      # generated images are smoother by nature
        if sharp < t:
            r.reasons.append(f"soft/blurry (sharpness {sharp:.0f} < {t:.0f})")

        clipped = float(((arr <= 2) | (arr >= 253)).mean())
        r.data["clipped_fraction"] = round(clipped, 3)
        if clipped > settings.get("qc.clip_fraction_max", 0.06):
            r.warnings.append(f"{clipped:.0%} of pixels clipped to pure black/white")
    r.passed = not r.reasons
    return r


VISION_PROMPT = """You are a strict reviewer for Adobe Stock and Freepik. Inspect this image.
Lane: {lane}. Context: {context}

Check for, and report every instance of:
- anatomy errors (extra/missing/fused fingers, distorted hands, faces, limbs, teeth, eyes)
- garbled, misspelled or nonsensical text, or any readable text that isn't essential
- logos, brand marks, trademarks, recognisable products or packaging
- watermarks, signatures, frames
- generation artifacts (melted objects, impossible geometry, repeating textures, noise, banding, halos)
- resemblance to a real, famous or identifiable person
- recognisable private property, artworks, tattoos or architecture that may need a property release
{lane_rules}
Return JSON only:
{{"issues": [{{"type": "anatomy|text|logo|watermark|artifact|real_person|property|other",
              "detail": "short description", "severity": "reject|warn"}}],
  "people_present": true|false,
  "identifiable_people": true|false,
  "property_present": true|false,
  "overall_quality": 1-10,
  "summary": "one sentence"}}"""

LANE_RULES = {
    Lane.AI_IMAGES: "This image is AI-generated. Any anatomy error, garbled text, logo, watermark, "
                    "visible artifact or real-person resemblance is severity 'reject'.",
    Lane.MY_PHOTOS: "This is a real photo. Identifiable people or private property are severity 'warn' "
                    "(they need releases, not rejection). Visible logos/brands are 'reject' unless tiny "
                    "and incidental ('warn'). Generation artifacts don't apply.",
    Lane.CODE_VECTORS: "This is a programmatic vector illustration. Only report logos, broken/overlapping "
                       "shapes, or text that is not placeholder text.",
}


def vision_check(a: Asset, llm: LLMProvider) -> QCResult:
    prompt = VISION_PROMPT.format(lane=a.lane.value, context=(a.prompt or a.topic or "none")[:400],
                                  lane_rules=LANE_RULES[a.lane])
    data = llm.complete_json(prompt, image_path=a.raster_path)
    r = QCResult(passed=True, data={"vision": data})
    for issue in data.get("issues", []) or []:
        msg = f"{issue.get('type', 'other')}: {issue.get('detail', '')}".strip()
        (r.reasons if issue.get("severity") == "reject" else r.warnings).append(msg)
    q = data.get("overall_quality")
    if isinstance(q, (int, float)) and q < 6:
        r.reasons.append(f"overall quality {q}/10")
    r.people_present = bool(data.get("people_present"))
    r.property_present = bool(data.get("property_present"))
    if a.lane == Lane.MY_PHOTOS and data.get("identifiable_people"):
        r.warnings.append("identifiable people - model release needed")
    r.passed = not r.reasons
    return r


class QCAgent:
    def __init__(self, settings: Settings, llm: LLMProvider):
        self.settings, self.llm = settings, llm

    def check(self, a: Asset) -> QCResult:
        tech = technical_checks(a, self.settings)
        if not tech.passed:
            return tech                           # no need to spend vision quota
        if a.lane == Lane.CODE_VECTORS:
            return tech                           # our own geometry; nothing to hallucinate
        if not self.llm.has_vision:
            if a.lane == Lane.AI_IMAGES and self.settings.get("qc.require_vision_check_for_ai", True):
                tech.deferred = True
                tech.warnings.append(f"vision QC not run ({getattr(self.llm, 'reason', 'no vision model')}); "
                                     "AI images wait until it can run")
            else:
                tech.warnings.append("vision QC skipped (no LLM configured) - check by eye")
            return tech
        try:
            vis = vision_check(a, self.llm)
        except Exception as e:
            tech.deferred = a.lane == Lane.AI_IMAGES
            tech.warnings.append(f"vision QC failed: {e}")
            return tech
        tech.reasons += vis.reasons
        tech.warnings += vis.warnings
        tech.people_present, tech.property_present = vis.people_present, vis.property_present
        tech.data.update(vis.data)
        tech.passed = not tech.reasons
        return tech
