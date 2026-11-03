"""OpenAI chat models with vision."""
from __future__ import annotations

from .base import LLMError, LLMProvider, b64, image_for_llm


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install 'stock-studio[openai]' to use OpenAI") from e
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _complete(self, prompt: str, image_path: str | None) -> str:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_path:
            data, mime = image_for_llm(image_path)
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64(data)}"}})
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
