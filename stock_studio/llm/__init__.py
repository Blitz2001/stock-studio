"""LLM / vision providers. Pick one with LLM_PROVIDER in .env."""
from __future__ import annotations

from ..config import Settings
from .base import LLMProvider, OfflineProvider


def get_provider(settings: Settings) -> LLMProvider:
    name = settings.env_value("LLM_PROVIDER", "gemini").strip().lower()
    if name == "offline":
        return OfflineProvider()
    if name == "gemini":
        from .gemini import GeminiProvider
        key = settings.env_value("GEMINI_API_KEY")
        if not key:
            return OfflineProvider(reason="GEMINI_API_KEY not set")
        return GeminiProvider(key, settings.env_value("GEMINI_MODEL", "gemini-2.5-flash"),
                              settings.env_value("GEMINI_IMAGE_MODEL", "imagen-4.0-generate-001"))
    if name == "claude":
        from .claude import ClaudeProvider
        key = settings.env_value("ANTHROPIC_API_KEY")
        if not key:
            return OfflineProvider(reason="ANTHROPIC_API_KEY not set")
        return ClaudeProvider(key, settings.env_value("CLAUDE_MODEL", "claude-sonnet-5-5"))
    if name == "openai":
        from .openai_provider import OpenAIProvider
        key = settings.env_value("OPENAI_API_KEY")
        if not key:
            return OfflineProvider(reason="OPENAI_API_KEY not set")
        return OpenAIProvider(key, settings.env_value("OPENAI_MODEL", "gpt-4o-mini"))
    raise ValueError(f"Unknown LLM_PROVIDER '{name}' (use gemini, claude, openai or offline)")


__all__ = ["LLMProvider", "OfflineProvider", "get_provider"]
