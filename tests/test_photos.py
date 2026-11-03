import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from stock_studio.models import Status
from stock_studio.producers.my_photos import estimate_tilt, ingest_folder, sharpness, straighten


def landscape(w=2400, h=1600, seed=0):
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", (w, h), (120, 170, 220))
    d = ImageDraw.Draw(img)
    d.rectangle([0, h * 0.55, w, h], fill=(60, 120, 70))
    for y in range(int(h * 0.6), h, 90):
        d.line([0, y, w, y], fill=(40, 90, 50), width=6)
    for _ in range(250):
        x, y = rng.integers(0, w), rng.integers(0, int(h * 0.5))
        d.ellipse([x, y, x + 25, y + 15], fill=(255, 255, 255))
    return img


def test_tilt_is_detected_and_level_images_left_alone():
    img = landscape()
    assert estimate_tilt(np.asarray(img)) == 0.0
    for deg in (2.0, -3.5):
        tilted = img.rotate(deg, resample=Image.BICUBIC).crop((80, 80, 2320, 1520))
        est = estimate_tilt(np.asarray(tilted))
        assert abs(est + deg) < 0.4, (deg, est)        # rotate back by -deg
        fixed = straighten(np.asarray(tilted), est)
        assert abs(estimate_tilt(fixed)) < 0.4
        assert fixed.shape[0] < tilted.size[1]           # cropped to remove rotated corners


def test_sharpness_separates_blur():
    a = np.asarray(landscape())
    blurred = np.asarray(Image.fromarray(a).filter(ImageFilter.GaussianBlur(4)))
    assert sharpness(a) > 25 > sharpness(blurred)


def test_ingest_culls_blurry_and_burst_duplicates(tmp_path, settings, store):
    src = tmp_path / "phone"
    src.mkdir()
    img = landscape(seed=1)
    img.save(src / "a.jpg", quality=95)
    img.filter(ImageFilter.GaussianBlur(1.2)).save(src / "a_burst_softer.jpg", quality=95)
    img.filter(ImageFilter.GaussianBlur(6)).save(src / "blurry.jpg")
    landscape(seed=2).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(src / "b.jpg", quality=95)

    rep = ingest_folder(src, settings, store, topic="tea plantations")
    assert (rep.added, rep.blurry, rep.burst_dupes) == (2, 1, 1)
    by_src = {a.qc["source"].split("/")[-1]: a for a in store.list()}
    assert by_src["a.jpg"].status == Status.NEW                 # sharper shot kept
    assert by_src["a_burst_softer.jpg"].status == Status.DUPLICATE
    assert by_src["blurry.jpg"].status == Status.QC_FAILED
    # originals untouched, processed copies written to the workspace
    assert by_src["a.jpg"].path.startswith(str(settings.workspace))
    # re-ingesting the same folder is a no-op
    assert ingest_folder(src, settings, store).skipped == 4
