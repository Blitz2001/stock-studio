"""Load config.yaml + .env into one Settings object."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
DEFAULT_CONFIG = PACKAGE_DIR.parent / "config.yaml"


@dataclass
class Settings:
    raw: dict[str, Any]
    root: Path
    env: dict[str, str] = field(default_factory=dict)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def workspace(self) -> Path:
        p = self.root / self.get("workspace", "workspace")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def dir(self, name: str) -> Path:
        p = self.workspace / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.workspace / "studio.db"

    def env_value(self, key: str, default: str = "") -> str:
        return self.env.get(key) or os.environ.get(key, default)


def load_settings(config_path: str | Path | None = None, overrides: dict | None = None) -> Settings:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text()) or {}
    if overrides:
        _deep_merge(raw, overrides)
    root = path.parent if path.exists() else Path.cwd()
    load_dotenv(root / ".env")
    return Settings(raw=raw, root=root)


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_data_yaml(name: str) -> Any:
    return yaml.safe_load((DATA_DIR / name).read_text())
