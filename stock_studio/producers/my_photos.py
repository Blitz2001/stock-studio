"""Lane A - your own phone photos and videos.

Ingests a folder, culls blurry shots and burst duplicates (keeping the sharpest), auto-
straightens tilted horizons, applies a light colour correction, and flags frames with
faces as needing a model release. Originals are never modified.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..config import Settings
from ..dedupe.guard import PHashEmbedder, find_duplicates
from ..models import IMAGE_EXTS, VIDEO_EXTS, Asset, Lane, Status
from ..store import Store

GPS_TAG = 0x8825
_FACE = None


def file_id(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ---- measurements ------------------------------------------------------------
def to_gray_small(arr: np.ndarray, max_side: int = 1500) -> np.ndarray:
    g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr
    s = max_side / max(g.shape)
    return cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g


def sharpness(arr: np.ndarray, grid: int = 8) -> float:
    """Laplacian variance of the sharpest tiles (90th percentile over an 8x8 grid).

    Whole-image variance punishes photos that are mostly smooth sky or wall even when the
    subject is crisp; the sharpest tiles reflect whether *anything* is in focus.
    """
    lap = cv2.Laplacian(to_gray_small(arr), cv2.CV_64F)
    h, w = lap.shape
    tiles = [lap[i * h // grid:(i + 1) * h // grid, j * w // grid:(j + 1) * w // grid].var()
             for i in range(grid) for j in range(grid)]
    return float(np.percentile(tiles, 90))


def face_boxes(arr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Frontal faces big enough to be identifiable. Returns [] if no detector is available."""
    global _FACE
    if _FACE is None:
        if not hasattr(cv2, "CascadeClassifier"):
            print("[photos] OpenCV build has no Haar face detector; install opencv-python-headless<5. "
                  "Face/release flags will rely on the vision QC only.")
            _FACE = False
        else:
            _FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if _FACE is False:
        return []
    g = to_gray_small(arr, 1200)
    min_side = max(24, int(min(g.shape) * 0.04))
    faces = _FACE.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side))
    return [tuple(map(int, f)) for f in faces]


def estimate_tilt(arr: np.ndarray, max_deg: float = 5.0) -> float:
    """Degrees to rotate counter-clockwise to level the image (0 if no confident lines)."""
    g = to_gray_small(arr, 1000)
    edges = cv2.Canny(g, 60, 160)
    min_len = int(min(g.shape) * 0.2)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60, minLineLength=min_len, maxLineGap=20)
    if lines is None:
        return 0.0
    angles, weights = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = math.degrees(math.atan2(y2 - y1, x2 - x1))
        a = (a + 90) % 180 - 90                    # (-90, 90]
        if abs(a) <= max_deg:                      # near-horizontal
            dev = a
        elif abs(abs(a) - 90) <= max_deg:          # near-vertical
            dev = a - 90 if a > 0 else a + 90
        else:
            continue
        angles.append(dev)
        weights.append(math.hypot(x2 - x1, y2 - y1))
    if sum(weights) < 0.6 * max(g.shape):   # not enough straight structure to trust
        return 0.0
    order = np.argsort(angles)
    cum = np.cumsum(np.array(weights)[order])
    median = float(np.array(angles)[order][np.searchsorted(cum, cum[-1] / 2)])
    return median if abs(median) >= 0.3 else 0.0


def _max_inner_rect(w: int, h: int, angle_deg: float) -> tuple[int, int]:
    """Largest axis-aligned rectangle inside a w x h rectangle rotated by angle."""
    a = math.radians(abs(angle_deg))
    if w <= 0 or h <= 0:
        return 0, 0
    long_side, short_side = (w, h) if w >= h else (h, w)
    sin_a, cos_a = math.sin(a), math.cos(a)
    if short_side <= 2.0 * sin_a * cos_a * long_side or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * short_side
        wr, hr = (x / sin_a, x / cos_a) if w >= h else (x / cos_a, x / sin_a)
    else:
        cos_2a = cos_a * cos_a - sin_a * sin_a
        wr, hr = (w * cos_a - h * sin_a) / cos_2a, (h * cos_a - w * sin_a) / cos_2a
    return int(wr), int(hr)


def straighten(arr: np.ndarray, angle: float) -> np.ndarray:
    if not angle:
        return arr
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rot = cv2.warpAffine(arr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    cw, ch = _max_inner_rect(w, h, angle)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return rot[y0 : y0 + ch, x0 : x0 + cw]


def colour_correct(arr: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """Gentle grey-world white balance + 0.5% auto-levels, blended by `strength`."""
    if strength <= 0:
        return arr
    f = arr.astype(np.float32)
    means = f.reshape(-1, 3).mean(0) + 1e-6
    gains = means.mean() / means
    gains = 1 + (gains - 1) * strength
    f = f * gains
    lum = f.mean(2)
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.5)
    if hi - lo > 20:
        stretched = (f - lo) * (255.0 / (hi - lo))
        f = f + (stretched - f) * strength
    return np.clip(f, 0, 255).astype(np.uint8)


# ---- ingest ------------------------------------------------------------------
@dataclass
class IngestReport:
    added: int = 0
    blurry: int = 0
    burst_dupes: int = 0
    skipped: int = 0
    needs_release: int = 0
    straightened: int = 0


def _load_rgb(path: Path) -> tuple[np.ndarray, Image.Exif]:
    with Image.open(path) as im:
        exif = im.getexif()
        im = ImageOps.exif_transpose(im).convert("RGB")
        return np.asarray(im), exif


def _video_frames(path: Path, n: int = 5) -> tuple[list[np.ndarray], dict]:
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    info = {"width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": round(fps, 2), "duration_s": round(total / fps, 2) if fps else 0}
    frames = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / n))
        ok, fr = cap.read()
        if ok:
            frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames, info


def ingest_folder(folder: str | Path, settings: Settings, store: Store, topic: str = "") -> IngestReport:
    folder = Path(folder)
    out_dir = settings.dir("assets/my_photos")
    blur_t = settings.get("photos.blur_threshold", 25.0)
    max_deg = settings.get("photos.max_straighten_degrees", 5.0)
    strength = settings.get("photos.colour_correction_strength", 0.5)
    report = IngestReport()
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS)

    staged: list[tuple[Asset, float, np.ndarray]] = []
    for p in files:
        aid = file_id(p)
        if store.get(aid):
            report.skipped += 1
            continue
        is_video = p.suffix.lower() in VIDEO_EXTS
        try:
            if is_video:
                frames, info = _video_frames(p)
                if not frames:
                    raise ValueError("no readable frames")
                score = float(np.median([sharpness(f) for f in frames]))
                arr = frames[len(frames) // 2]
                faces = sum(len(face_boxes(f)) for f in frames)
                qc = {"video": info}
            else:
                arr, _ = _load_rgb(p)
                score = sharpness(arr)
                faces = len(face_boxes(arr))
                qc = {}
        except Exception as e:  # unreadable/HEIC without plugin etc.
            print(f"[photos] skip {p.name}: {e}")
            report.skipped += 1
            continue
        qc.update({"sharpness": round(score, 1), "faces": faces, "source": str(p)})
        a = Asset(id=aid, path=str(p), lane=Lane.MY_PHOTOS, topic=topic, is_video=is_video,
                  needs_release=faces > 0, qc=qc)
        if faces:
            a.reasons.append(f"WARN {faces} face(s) detected - attach a model release or exclude")
        if score < blur_t:
            a.status = Status.QC_FAILED
            a.reasons.append(f"blurry (sharpness {score:.0f} < {blur_t:.0f})")
            report.blurry += 1
            store.upsert(a)
            continue
        staged.append((a, score, arr))

    # Burst culling: within this folder keep only the sharpest of each near-identical group.
    if staged:
        emb = PHashEmbedder()
        staged.sort(key=lambda t: t[1], reverse=True)
        vecs = []
        for a, _, arr in staged:
            tmp = Image.fromarray(arr)
            tmp.thumbnail((512, 512))
            g = np.asarray(tmp.convert("L").resize((emb.size, emb.size)), dtype=np.float32)
            d = cv2.dct(g)[: emb.keep, : emb.keep].flatten()[1:]
            vecs.append((a.id, d / (np.linalg.norm(d) or 1)))
        hits = find_duplicates(vecs, {}, threshold=0.95)
        for a, score, arr in staged:
            if a.id in hits:
                a.status = Status.DUPLICATE
                a.reasons.append(f"burst duplicate of {hits[a.id].duplicate_of} (kept the sharper shot)")
                report.burst_dupes += 1
                store.upsert(a)
                continue
            if a.is_video:
                poster = out_dir / f"{a.id}_poster.jpg"
                Image.fromarray(arr).save(poster, quality=92)
                a.preview_path = str(poster)
            else:
                angle = estimate_tilt(arr, max_deg)
                fixed = colour_correct(straighten(arr, angle), strength)
                if angle:
                    report.straightened += 1
                    a.qc["straightened_deg"] = round(angle, 2)
                out = out_dir / f"{a.id}.jpg"
                _save_with_exif(fixed, Path(a.qc["source"]), out, strip_gps=settings.get("export.strip_gps", True))
                a.path = str(out)
            report.added += 1
            report.needs_release += int(a.needs_release)
            store.upsert(a)
    return report


def _save_with_exif(arr: np.ndarray, src: Path, out: Path, strip_gps: bool) -> None:
    with Image.open(src) as im:
        exif = im.getexif()
    exif[0x0112] = 1                       # orientation already applied
    if strip_gps and GPS_TAG in exif:
        del exif[GPS_TAG]
    Image.fromarray(arr).save(out, "JPEG", quality=95, exif=exif.tobytes(), subsampling=0)
