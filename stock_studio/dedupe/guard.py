"""Duplicate guard: block near-duplicates within a batch and against past uploads.

Adobe Stock rejects multiple near-identical versions from the same prompt, and a low
approval rate shrinks your weekly limit, so near-duplicates are blocked before review.

Two embedders:
  * clip  - CLIP ViT-B/32 via sentence-transformers. Catches semantic near-duplicates
            (same scene, re-generated). Runs on CPU; ~600 MB model download once.
  * phash - low-frequency DCT of the grayscale image. No extra dependencies; catches
            resized/re-exposed/slightly cropped copies but not re-generations.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import cv2
import numpy as np
from PIL import Image

from ..models import Asset, Lane, Status


class Embedder(Protocol):
    name: str

    def embed(self, paths: list[str]) -> np.ndarray: ...


class PHashEmbedder:
    name = "phash"

    def __init__(self, size: int = 64, keep: int = 12):
        self.size, self.keep = size, keep

    def embed_one(self, path: str | Path) -> np.ndarray:
        with Image.open(path) as im:
            g = np.asarray(im.convert("L").resize((self.size, self.size), Image.Resampling.LANCZOS), dtype=np.float32)
        d = cv2.dct(g)[: self.keep, : self.keep].flatten()[1:]   # drop DC = brightness
        n = np.linalg.norm(d)
        return (d / n) if n else d

    def embed(self, paths: list[str]) -> np.ndarray:
        return np.stack([self.embed_one(p) for p in paths]) if paths else np.zeros((0, self.keep**2 - 1))


class ClipEmbedder:
    name = "clip"

    def __init__(self, model_name: str = "clip-ViT-B-32"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("pip install 'stock-studio[clip]' for CLIP, or set EMBEDDER=phash") from e
        self.model = SentenceTransformer(model_name, device="cpu")

    def embed(self, paths: list[str]) -> np.ndarray:
        if not paths:
            return np.zeros((0, 512))
        images = []
        for p in paths:
            with Image.open(p) as im:
                images.append(im.convert("RGB").copy())
        return self.model.encode(images, batch_size=16, normalize_embeddings=True, convert_to_numpy=True)


def make_embedder(name: str) -> Embedder:
    if name == "clip":
        try:
            return ClipEmbedder()
        except RuntimeError as e:
            print(f"[dedupe] {e}; falling back to phash")
    return PHashEmbedder()


@dataclass
class DupHit:
    key: str
    duplicate_of: str
    similarity: float


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else v


def find_duplicates(candidates: list[tuple[str, np.ndarray]],
                    reference: dict[str, np.ndarray],
                    threshold: float,
                    groups: dict[str, str] | None = None) -> dict[str, DupHit]:
    """Pure core of the guard.

    Walks candidates in order. Each is compared with every reference vector (past uploads,
    already-accepted assets) and with every earlier candidate that was *kept*. The first
    of a near-identical group survives; the rest are reported.

    `groups` optionally maps keys to a content group. Two keys with *different, non-empty*
    groups are never compared (e.g. two code-generated icon sets with different contents
    share a grid layout that a perceptual hash would confuse). Missing/empty = compare all.
    """
    groups = groups or {}
    ref_keys = list(reference)
    ref = np.stack([_unit(reference[k]) for k in ref_keys]) if ref_keys else None
    ref_groups = np.array([groups.get(k, "") for k in ref_keys], dtype=object)
    kept_keys: list[str] = []
    kept_vecs: list[np.ndarray] = []
    hits: dict[str, DupHit] = {}

    def best(keys, mat, key_groups, v, g):
        sims = mat @ v
        if g:
            sims = np.where((key_groups == "") | (key_groups == g), sims, -1.0)
        i = int(np.argmax(sims))
        return keys[i], float(sims[i])

    for key, vec in candidates:
        v = _unit(vec)
        g = groups.get(key, "")
        best_key, best_sim = None, -1.0
        if ref is not None:
            best_key, best_sim = best(ref_keys, ref, ref_groups, v, g)
        if kept_vecs:
            k2, s2 = best(kept_keys, np.stack(kept_vecs),
                          np.array([groups.get(k, "") for k in kept_keys], dtype=object), v, g)
            if s2 > best_sim:
                best_key, best_sim = k2, s2
        if best_key is not None and best_sim >= threshold:
            hits[key] = DupHit(key, best_key, round(best_sim, 4))
        else:
            kept_keys.append(key)
            kept_vecs.append(v)
    return hits


# Assets in these states count as "already in your portfolio or pipeline".
REFERENCE_STATUSES = {Status.PENDING_REVIEW, Status.APPROVED, Status.EXPORTED}


class DuplicateGuard:
    def __init__(self, store, embedder: Embedder, threshold: float):
        self.store, self.embedder, self.threshold = store, embedder, threshold

    def _ensure_embeddings(self, assets: Iterable[Asset]) -> dict[str, np.ndarray]:
        assets = list(assets)
        have = self.store.embeddings(self.embedder.name, keys=[a.id for a in assets])
        missing = [a for a in assets if a.id not in have]
        if missing:
            vecs = self.embedder.embed([a.raster_path for a in missing])
            for a, v in zip(missing, vecs):
                self.store.put_embedding(a.id, self.embedder.name, v, "asset")
                have[a.id] = v
        return have

    def index_history(self, folder: str | Path) -> int:
        """Embed a folder of files you've already uploaded (one-off, before first run)."""
        from ..models import IMAGE_EXTS
        paths = [p for p in Path(folder).rglob("*") if p.suffix.lower() in IMAGE_EXTS]
        existing = self.store.embeddings(self.embedder.name, source="history")
        todo = [p for p in paths if f"history:{p}" not in existing]
        for i in range(0, len(todo), 32):
            chunk = todo[i : i + 32]
            for p, v in zip(chunk, self.embedder.embed([str(p) for p in chunk])):
                self.store.put_embedding(f"history:{p}", self.embedder.name, v, "history")
        return len(todo)

    def check(self, batch: list[Asset]) -> dict[str, DupHit]:
        batch_vecs = self._ensure_embeddings(batch)
        batch_ids = {a.id for a in batch}
        ref_assets = [a for s in REFERENCE_STATUSES for a in self.store.list(status=s) if a.id not in batch_ids]
        reference = self._ensure_embeddings(ref_assets)
        reference.update(self.store.embeddings(self.embedder.name, source="history"))
        groups = {a.id: f"vector:{a.set_id}" for a in batch + ref_assets
                  if a.lane == Lane.CODE_VECTORS and a.set_id}
        return find_duplicates([(a.id, batch_vecs[a.id]) for a in batch], reference, self.threshold, groups)
