import csv
from datetime import date

from PIL import Image

from stock_studio.analytics.sales import compute_weights, import_sales, performance
from stock_studio.export.exporter import Exporter
from stock_studio.models import Asset, Lane, Status
from stock_studio.pipeline import Studio


def approved_photo(tmp_path, store, i, size=(2400, 1800), **kw):
    p = tmp_path / f"img{i}.jpg"
    Image.new("RGB", size, (i * 40 % 255, 100, 150)).save(p)
    a = Asset(id=f"asset{i:011d}", path=str(p), lane=kw.pop("lane", Lane.MY_PHOTOS), status=Status.APPROVED,
              title=f"Tea plantation number {i}", keywords=["tea", "plantation", "sri lanka"], category=11,
              topic=kw.pop("topic", "tea"), **kw)
    store.upsert(a)
    return a


def test_weekly_cap_and_batches(tmp_path, settings, store):
    for i in range(5):
        approved_photo(tmp_path, store, i)
    ex = Exporter(settings, store)
    r = ex.export("adobe", today=date(2026, 11, 3))
    assert len(r.exported) == 3 and r.deferred == 2 and r.remaining_cap == 0   # cap 3, batch size 2
    assert len(r.batches) == 2
    again = ex.export("adobe", today=date(2026, 11, 4))                        # same ISO week
    assert again.exported == []
    nxt = ex.export("adobe", today=date(2026, 11, 10))                         # next week
    assert len(nxt.exported) == 2
    # freepik has its own cap and still gets everything
    assert len(ex.export("freepik", today=date(2026, 11, 3)).exported) == 3


def test_adobe_csv_and_upscale(tmp_path, settings, store):
    approved_photo(tmp_path, store, 1, size=(1800, 1500))      # 2.7 MP -> needs upscale
    r = Exporter(settings, store).export("adobe", today=date(2026, 11, 3))
    rows = list(csv.DictReader(open(f"{r.batches[0]}/adobe_stock_metadata.csv")))
    assert list(rows[0]) == ["Filename", "Title", "Keywords", "Category", "Releases"]
    assert rows[0]["Keywords"] == "tea, plantation, sri lanka" and rows[0]["Category"] == "11"
    with Image.open(f"{r.batches[0]}/{rows[0]['Filename']}") as im:
        assert im.width * im.height >= 4_000_000 and min(im.size) >= 2000


def test_checklist_lists_ai_and_release_files(tmp_path, settings, store):
    approved_photo(tmp_path, store, 1, lane=Lane.AI_IMAGES, ai_generated=True, fictional=True)
    approved_photo(tmp_path, store, 2, needs_release=True)
    r = Exporter(settings, store).export("adobe", today=date(2026, 11, 3))
    text = open(f"{r.batches[0]}/CHECKLIST.md").read()
    ai_section = text.split("## Tick 'Created using generative AI tools'")[1].split("##")[0]
    release_section = text.split("release")[1]
    assert "number-1" in ai_section and "number-2" not in ai_section
    assert "number-2" in release_section


def test_approve_refuses_banned_terms(tmp_path, settings, store):
    a = approved_photo(tmp_path, store, 1)
    a.status = Status.PENDING_REVIEW
    store.upsert(a)
    studio = Studio(settings)
    assert studio.approve(a.id, title="Tea pickers drinking Pepsi") != []
    assert store.get(a.id).status == Status.PENDING_REVIEW
    assert studio.approve(a.id, title="Tea pickers on a misty hillside") == []
    assert store.get(a.id).status == Status.APPROVED


def test_sales_import_matches_and_weights(tmp_path, settings, store):
    for i, topic in enumerate(["tea", "tea", "patterns", "patterns"]):
        approved_photo(tmp_path, store, i, topic=topic)
    Exporter(settings, store).export("adobe", today=date(2026, 11, 3))
    settings.raw["export"]["weekly_cap"] = 10
    Exporter(settings, store).export("adobe", today=date(2026, 11, 3))
    tea_file = next(f for f, aid in store.filename_index().items() if aid == "asset00000000000")
    sales = tmp_path / "sales.csv"
    sales.write_text("Date,Original Filename,Title,Royalty\n"
                     f"2026-11-20,{tea_file},x,$0.99\n"
                     f"2026-11-21,{tea_file},x,$0.99\n"
                     "2026-11-22,unknown.jpg,Tea plantation number 1,0.33\n"
                     "2026-11-23,nothing.jpg,Something else,0.10\n")
    added, matched = import_sales(sales, "adobe", store)
    assert (added, matched) == (4, 3)
    assert import_sales(sales, "adobe", store)[0] == 0          # re-import doesn't double count
    perf = performance(store)
    assert perf["topic"].loc["tea", "earnings"] == round(0.99 * 2 + 0.33, 2)
    w = compute_weights(perf)
    assert w["topics"]["tea"] > 1.0 > w["topics"]["patterns"]
    assert len(perf["unmatched_sales"]) == 1
