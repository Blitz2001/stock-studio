"""Full pipeline with a fake LLM: exercises the vision QC, metadata and AI lane code paths."""
import numpy as np
from PIL import Image

from stock_studio.llm.base import LLMProvider
from stock_studio.models import Status
from stock_studio.pipeline import Studio
from stock_studio.producers.ai_images import generate


class FakeLLM(LLMProvider):
    name = "fake"
    can_generate_images = True
    image_model = "fake-imagen"

    def __init__(self):
        self.generated_prompts = []

    def generate_image(self, prompt, out_path, aspect_ratio="4:3"):
        self.generated_prompts.append(prompt)
        rng = np.random.default_rng(len(self.generated_prompts))
        arr = rng.integers(0, 255, (1800, 2400, 3), dtype=np.uint8)  # noisy = sharp, unique
        Image.fromarray(arr).save(out_path)
        return out_path

    def complete_json(self, prompt, image_path=None):
        if "strict reviewer" in prompt:
            if "typing on a laptop" in prompt:        # context of the "bad" image
                return {"issues": [{"type": "anatomy", "detail": "six fingers on left hand", "severity": "reject"}],
                        "people_present": True, "overall_quality": 7}
            return {"issues": [], "people_present": True, "property_present": False, "overall_quality": 8}
        return {"title": "South Asian team meeting in a bright modern office",
                "keywords": ["team", "meeting", "office", "MacBook", "south asian", "colombo", "business"]
                            + [f"kw{i}" for i in range(60)],
                "category": 3}


def test_ai_lane_end_to_end(settings):
    llm = FakeLLM()
    studio = Studio(settings, llm=llm)
    rep = generate(
        ["Diverse team meeting in a modern Colombo office, natural light",
         "Close-up of hands typing on a laptop keyboard",
         "Business woman in the style of Annie Leibovitz"],          # must never be sent
        settings, studio.store, llm, topic="south asian business people")
    assert len(rep.generated) == 2 and len(rep.blocked) == 1
    assert all("Leibovitz" not in p for p in llm.generated_prompts)

    r = studio.process()
    assert (r.qc_failed, r.ready_for_review) == (1, 1)
    failed = studio.store.list(Status.QC_FAILED)[0]
    assert "six fingers" in failed.reasons[0]

    ok = studio.store.list(Status.PENDING_REVIEW)[0]
    assert ok.ai_generated and ok.fictional and ok.category == 3
    assert "macbook" not in ok.keywords and len(ok.keywords) == 49
    assert ok.keywords[:3] == ["team", "meeting", "office"]          # LLM ranking preserved
    assert any("removed banned keywords: macbook" in w for w in ok.reasons)


def test_ai_images_wait_for_vision_when_offline(settings):
    llm = FakeLLM()
    studio = Studio(settings, llm=llm)
    generate(["A bowl of rice and curry on a banana leaf"], settings, studio.store, llm)
    from stock_studio.llm.base import OfflineProvider
    offline = Studio(settings, llm=OfflineProvider())
    r = offline.process()
    assert r.deferred == 1 and studio.store.list(Status.NEW)       # not passed, not failed: waits
