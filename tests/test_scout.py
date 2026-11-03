import json
from datetime import date

from stock_studio.metadata.compliance import ComplianceScanner
from stock_studio.scout.demand import DemandScout, next_occurrence, write_briefs


def test_next_occurrence_wraps_year():
    assert next_occurrence(1, 14, date(2026, 11, 3)) == date(2027, 1, 14)
    assert next_occurrence(12, 25, date(2026, 11, 3)) == date(2026, 12, 25)


def test_events_respect_lookahead_window(settings):
    cands = DemandScout(settings).candidates(date(2026, 11, 3))
    events = {b.topic for b in cands if b.source == "event"}
    assert "Christmas" in events and "Thai Pongal" in events       # 52 and 72 days out
    assert "Halloween" not in events                                # just passed
    assert "Black Friday and Cyber Monday" not in events            # 24 days: too late to upload


def test_briefs_are_compliant_and_written(settings):
    scout = DemandScout(settings)
    briefs = scout.weekly_briefs(today=date(2026, 11, 3), n=10)
    assert len(briefs) == 10
    s = ComplianceScanner()
    for b in briefs:
        assert b.shots and all(s.scan_text(x).ok for x in b.shots)
        assert all(s.scan_text(p).ok for p in b.ai_prompts)
        if b.lane == "ai_images":
            assert b.ai_prompts
    path = write_briefs(briefs, settings, date(2026, 11, 3))
    assert path.name == "2026-W45.json" and len(json.loads(path.read_text())) == 10
    assert path.with_suffix(".md").exists()


def test_sales_weights_steer_the_scout(settings):
    (settings.dir("analytics") / "weights.json").write_text(
        json.dumps({"topics": {"sri lankan food": 2.0, "healthcare": 0.5}}))
    briefs = DemandScout(settings).weekly_briefs(today=date(2026, 11, 3), n=40)
    order = [b.topic for b in briefs]
    assert order.index("sri lankan food") < order.index("healthcare") if "healthcare" in order else True
    assert "sri lankan food" in order[:8]
