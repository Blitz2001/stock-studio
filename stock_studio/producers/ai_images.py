"""Lane C - AI images, done carefully.

Few, specific, buyer-driven images from compliance-checked prompts. Every prompt is
scanned *before* it is sent to the generator; a blocked prompt is never generated.
One image per prompt by default, because Adobe rejects near-identical variations.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..config import Settings
from ..llm.base import LLMProvider
from ..metadata.compliance import default_scanner
from ..models import Asset, Lane
from ..store import Store


@dataclass
class GenerationReport:
    generated: list[str] = field(default_factory=list)
    blocked: list[tuple[str, list[str]]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def generate(prompts: list[str], settings: Settings, store: Store, provider: LLMProvider,
             topic: str = "", aspect_ratio: str = "4:3", per_prompt: int = 1) -> GenerationReport:
    report = GenerationReport()
    scanner = default_scanner()
    if not provider.can_generate_images:
        raise RuntimeError(f"Provider '{provider.name}' can't generate images. Set LLM_PROVIDER=gemini "
                           "and GEMINI_API_KEY in .env (Imagen is a paid API feature).")
    out_dir = settings.dir("assets/ai_images")
    for prompt in prompts:
        res = scanner.scan_text(prompt, "prompt")
        if not res.ok:
            report.blocked.append((prompt, res.summary()))
            continue
        for k in range(per_prompt):
            aid = hashlib.sha1(f"{prompt}|{k}".encode()).hexdigest()[:16]
            if store.get(aid):
                continue
            try:
                path = provider.generate_image(prompt, out_dir / f"{aid}.png", aspect_ratio=aspect_ratio)
            except Exception as e:
                report.failed.append((prompt, str(e)))
                continue
            model = getattr(provider, "image_model", provider.name)
            store.upsert(Asset(id=aid, path=str(path), lane=Lane.AI_IMAGES, topic=topic, prompt=prompt,
                               ai_generated=True, fictional=True, style="photoreal",
                               qc={"generator": model}))
            report.generated.append(aid)
    return report
