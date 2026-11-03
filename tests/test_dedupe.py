import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageEnhance

from stock_studio.dedupe.guard import DuplicateGuard, PHashEmbedder, find_duplicates
from stock_studio.models import Asset, Lane, Status
from stock_studio.store import Store

THRESHOLD = 0.90


def scene(path, seed, size=(800, 600)):
    """A random 'photo': coloured shapes on a gradient, unique per seed."""
    rng = np.random.default_rng(seed)
    w, h = size
    grad = np.linspace(0, 1, w)[None, :, None] * rng.uniform(80, 200, 3) + rng.uniform(0, 50, 3)
    img = Image.fromarray(np.broadcast_to(grad, (h, w, 3)).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rng.integers(0, w - 50), rng.integers(0, h - 50)
        x1, y1 = x0 + rng.integers(40, 300), y0 + rng.integers(40, 250)
        fill = tuple(int(c) for c in rng.integers(0, 256, 3))
        (d.ellipse if rng.random() < 0.5 else d.rectangle)([x0, y0, x1, y1], fill=fill)
    img.save(path, quality=92)
    return str(path)


@pytest.fixture()
def emb():
    return PHashEmbedder()


def sim(emb, a, b):
    va, vb = emb.embed_one(a), emb.embed_one(b)
    return float(va @ vb)


def test_identical_and_edited_copies_are_near_duplicates(tmp_path, emb):
    orig = scene(tmp_path / "orig.jpg", 1)
    with Image.open(orig) as im:
        im.resize((400, 300)).save(tmp_path / "small.jpg")                       # resized
        ImageEnhance.Brightness(im).enhance(1.25).save(tmp_path / "bright.jpg")  # re-exposed
        im.crop((16, 12, 784, 588)).save(tmp_path / "crop.jpg")                  # ~2% crop
        im.save(tmp_path / "recompressed.jpg", quality=60)
    for name in ["small", "bright", "crop", "recompressed"]:
        s = sim(emb, orig, tmp_path / f"{name}.jpg")
        assert s >= THRESHOLD, f"{name}: {s:.3f}"


def test_different_images_are_not_duplicates(tmp_path, emb):
    paths = [scene(tmp_path / f"s{i}.jpg", i) for i in range(10)]
    vecs = emb.embed(paths)
    sims = vecs @ vecs.T
    np.fill_diagonal(sims, 0)
    assert sims.max() < THRESHOLD, f"max cross-similarity {sims.max():.3f}"


def test_find_duplicates_keeps_first_of_group():
    a = np.array([1.0, 0, 0])
    a2 = np.array([0.99, 0.05, 0])
    b = np.array([0, 1.0, 0])
    hits = find_duplicates([("a", a), ("a2", a2), ("b", b)], reference={}, threshold=0.95)
    assert set(hits) == {"a2"}
    assert hits["a2"].duplicate_of == "a"


def test_find_duplicates_against_reference():
    ref = {"history:old.jpg": np.array([0, 0, 1.0])}
    hits = find_duplicates([("new", np.array([0.02, 0, 1.0])), ("other", np.array([1.0, 0, 0]))], ref, 0.95)
    assert list(hits) == ["new"]
    assert hits["new"].duplicate_of == "history:old.jpg"


def test_rejected_candidates_do_not_shadow_later_ones():
    # 'x' is a dup of history; 'y' is close to 'x' but not to history. Because 'x' was
    # dropped, 'y' should be judged only against history and kept.
    ref = {"h": np.array([1.0, 0.0])}
    x = np.array([0.97, 0.243])   # ~0.97 to h
    y = np.array([0.80, 0.60])    # ~0.80 to h, ~0.92 to x
    hits = find_duplicates([("x", x), ("y", y)], ref, threshold=0.95)
    assert set(hits) == {"x"}


def test_groups_keep_different_vector_sets_apart():
    v = np.array([1.0, 0.0])
    groups = {"festival": "vector:icons-festival", "travel": "vector:icons-travel",
              "festival_blue": "vector:icons-festival"}
    hits = find_duplicates([("festival", v), ("travel", v), ("festival_blue", v)], {}, 0.95, groups)
    # different sets with an identical layout are kept; a recolour of the same set is blocked
    assert set(hits) == {"festival_blue"}
    # ungrouped history still applies to everything
    hits = find_duplicates([("travel", v)], {"history:x": v}, 0.95, groups)
    assert set(hits) == {"travel"}


def test_guard_end_to_end(tmp_path, emb):
    store = Store(tmp_path / "db.sqlite")
    hist_dir = tmp_path / "uploaded"
    hist_dir.mkdir()
    scene(hist_dir / "sold_last_year.jpg", 42)

    guard = DuplicateGuard(store, emb, THRESHOLD)
    assert guard.index_history(hist_dir) == 1
    assert guard.index_history(hist_dir) == 0   # idempotent

    # an asset already approved last week
    approved = Asset(id="approved1", path=scene(tmp_path / "approved.jpg", 7), lane=Lane.MY_PHOTOS,
                     status=Status.APPROVED)
    store.upsert(approved)

    with Image.open(hist_dir / "sold_last_year.jpg") as im:
        im.resize((640, 480)).save(tmp_path / "reupload.jpg")
    with Image.open(tmp_path / "approved.jpg") as im:
        ImageEnhance.Contrast(im).enhance(1.1).save(tmp_path / "approved_again.jpg")
    fresh = scene(tmp_path / "fresh.jpg", 99)

    batch = [
        Asset(id="reupload", path=str(tmp_path / "reupload.jpg"), lane=Lane.MY_PHOTOS),
        Asset(id="approved_again", path=str(tmp_path / "approved_again.jpg"), lane=Lane.MY_PHOTOS),
        Asset(id="fresh", path=fresh, lane=Lane.MY_PHOTOS),
        Asset(id="fresh_copy", path=fresh, lane=Lane.MY_PHOTOS),
    ]
    for a in batch:
        store.upsert(a)
    hits = guard.check(batch)
    assert set(hits) == {"reupload", "approved_again", "fresh_copy"}
    assert hits["reupload"].duplicate_of.startswith("history:")
    assert hits["approved_again"].duplicate_of == "approved1"
    assert hits["fresh_copy"].duplicate_of == "fresh"
