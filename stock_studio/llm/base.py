"""Provider interface + helpers shared by all LLM backends."""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image


class LLMError(RuntimeError):
    pass


class LLMProvider:
    name = "base"
    has_vision = True
    can_generate_images = False

    def complete_json(self, prompt: str, image_path: str | None = None) -> dict[str, Any]:
        """Send a prompt (optionally with one image) and parse a JSON object from the reply."""
        text = self._complete(prompt, image_path)
        return parse_json(text)

    def _complete(self, prompt: str, image_path: str | None) -> str:  # pragma: no cover
        raise NotImplementedError

    def generate_image(self, prompt: str, out_path: Path, aspect_ratio: str = "4:3") -> Path:
        raise LLMError(f"{self.name} cannot generate images")


class OfflineProvider(LLMProvider):
    """No network. QC falls back to technical checks, metadata to templates."""
    name = "offline"
    has_vision = False

    def __init__(self, reason: str = "LLM_PROVIDER=offline"):
        self.reason = reason

    def _complete(self, prompt: str, image_path: str | None) -> str:
        raise LLMError(f"offline provider ({self.reason})")


def image_for_llm(path: str | Path, max_side: int = 1024) -> tuple[bytes, str]:
    """Downscale to save tokens/quota; return JPEG bytes + mime type."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> dict[str, Any]:
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"No JSON object in model reply: {text[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"Bad JSON from model: {e}") from e
