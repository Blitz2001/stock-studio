"""Anthropic Claude (text + vision)."""
from __future__ import annotations

from .base import LLMError, LLMProvider, b64, image_for_llm


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install 'stock-studio[claude]' to use Claude") from e
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _complete(self, prompt: str, image_path: str | None) -> str:
        content: list[dict] = []
        if image_path:
            data, mime = image_for_llm(image_path)
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64(data)}})
        content.append({"type": "text", "text": prompt + "\n\nReply with a single JSON object only."})
        msg = self.client.messages.create(
            model=self.model, max_tokens=2000, messages=[{"role": "user", "content": content}]
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")
