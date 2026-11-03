import pytest

from stock_studio.metadata.compliance import ComplianceScanner, normalise


@pytest.fixture(scope="module")
def scanner():
    return ComplianceScanner()


@pytest.mark.parametrize(
    "text",
    [
        "Woman drinking Coca-Cola on a beach",
        "woman drinking cocacola",
        "COCA COLA bottle",
        "Nike's new running shoes",
        "runner in nikes",
        "Photorealistic portrait, Greg Rutkowski lighting",
        "Spider-Man swinging over Colombo",
        "spiderman",
        "Café inspired by Starbucks",
        "elephant painted like Van Gogh",
        "Taylor Swift at a concert",
        "Kumar Sangakkara batting",
        "tea plantation, Dilmah packaging",
        "Mickey Mouse balloon",
    ],
)
def test_blocks_banned_terms(scanner, text):
    res = scanner.scan_text(text, "prompt")
    assert not res.ok, f"expected a block for: {text}"


@pytest.mark.parametrize(
    "text",
    [
        "Fresh pineapple slices on a wooden table",          # 'apple' inside a word
        "Diverse team meeting in a modern Colombo office",
        "Vesak lanterns glowing at night in Sri Lanka",
        "Ceylon tea plantation in Nuwara Eliya at sunrise",
        "Batik fabric seamless pattern",                       # 'bat' not 'batman'
        "Sonic boom concept illustration",                     # partial character name
        "Teenager using a smartphone",
        "Business illustration, flat style",
        "A new style of working from home",
    ],
)
def test_clean_text_passes(scanner, text):
    res = scanner.scan_text(text, "title")
    assert res.ok, res.summary()


def test_ambiguous_brand_words_warn_not_block(scanner):
    res = scanner.scan_text("Red apple on a desk", "title")
    assert res.ok
    assert [w.term for w in res.warnings] == ["apple"]


def test_style_copying_phrases_are_blocked(scanner):
    for text in ["landscape in the style of an unnamed master", "art by somebody", "trending on artstation"]:
        assert not scanner.scan_text(text).ok, text


def test_scan_asset_fields_reports_field(scanner):
    res = scanner.scan_asset_fields(
        prompt="sunset over Galle fort",
        title="Sunset over Galle Fort",
        keywords=["sunset", "galle", "iphone", "fort"],
    )
    assert not res.ok
    assert [(h.field, h.term) for h in res.blocks] == [("keyword", "iphone")]


def test_clean_keywords(scanner):
    kept, removed = scanner.clean_keywords(["beach", "Adidas", "surf", "Disney castle", "sri lanka"])
    assert kept == ["beach", "surf", "sri lanka"]
    assert removed == ["Adidas", "Disney castle"]


def test_custom_terms(tmp_path):
    p = tmp_path / "terms.yaml"
    p.write_text("block:\n  brands: [acme corp]\nwarn: []\npatterns: []\n")
    s = ComplianceScanner(p, extra_block=["Zorblax"])
    assert not s.scan_text("ACME-Corp logo").ok
    assert not s.scan_text("zorblax mascot").ok
    assert s.scan_text("acme of design").ok


def test_normalise():
    assert normalise("  McDonald’s CAFÉ—menu ") == "mcdonald cafe menu"
