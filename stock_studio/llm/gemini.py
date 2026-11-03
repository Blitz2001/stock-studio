"""Google Gemini (text + vision) and Imagen (image generation) via the google-genai SDK."""
from __future__ import annotations

from pathlib import Path

from .base import LLMError, LLMProvider, image_for_llm


class GeminiProvider(LLMProvider):
    name = "gemini"
    can_generate_images = True

    def __init__(self, api_key: str, model: str, image_model: str):
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install 'stock-studio[gemini]' to use Gemini") from e
        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.image_model = image_model

    def _complete(self, prompt: str, image_path: str | None) -> str:
        t = self._types
        parts: list = []
        if image_path:
            data, mime = image_for_llm(image_path)
            parts.append(t.Part.from_bytes(data=data, mime_type=mime))
        parts.append(prompt)
        resp = self.client.models.generate_content(
            model=self.model,
            contents=parts,
            config=t.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
        )
        if not resp.text:
            raise LLMError("Gemini returned no text (possibly blocked by safety filters)")
        return resp.text

    def generate_image(self, prompt: str, out_path: Path, aspect_ratio: str = "4:3") -> Path:
        t = self._types
        resp = self.client.models.generate_images(
            model=self.image_model,
            prompt=prompt,
            config=t.GenerateImagesConfig(number_of_images=1, aspect_ratio=aspect_ratio),
        )
        if not resp.generated_images:
            raise LLMError("Imagen returned no image (prompt may have been filtered)")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.generated_images[0].image.image_bytes)
        return out_path
