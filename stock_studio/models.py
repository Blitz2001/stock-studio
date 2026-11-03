"""Core data types shared by every agent step."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Lane(str, Enum):
    MY_PHOTOS = "my_photos"
    CODE_VECTORS = "code_vectors"
    AI_IMAGES = "ai_images"


class Status(str, Enum):
    NEW = "new"                      # produced, not yet checked
    QC_FAILED = "qc_failed"          # rejected by the QC agent (reason stored)
    DUPLICATE = "duplicate"          # blocked by the duplicate guard
    COMPLIANCE_FAILED = "compliance_failed"
    PENDING_REVIEW = "pending_review"  # passed every automated step; waiting for you
    APPROVED = "approved"            # you approved it in the dashboard
    REJECTED = "rejected"            # you rejected it
    EXPORTED = "exported"            # written to an upload batch


# Adobe Stock category IDs used in the bulk-upload CSV.
ADOBE_CATEGORIES: dict[int, str] = {
    1: "Animals", 2: "Buildings and Architecture", 3: "Business", 4: "Drinks",
    5: "The Environment", 6: "States of Mind", 7: "Food", 8: "Graphic Resources",
    9: "Hobbies and Leisure", 10: "Industry", 11: "Landscapes", 12: "Lifestyle",
    13: "People", 14: "Plants and Flowers", 15: "Culture and Religion", 16: "Science",
    17: "Social Issues", 18: "Sports", 19: "Technology", 20: "Transport", 21: "Travel",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}


@dataclass
class Asset:
    id: str
    path: str                     # master file (JPEG/PNG, SVG or video)
    lane: Lane
    status: Status = Status.NEW
    preview_path: str | None = None   # raster preview (vectors, video poster frame)
    topic: str = ""
    style: str = ""
    set_id: str = ""
    prompt: str = ""              # generation prompt (ai lane) or brief text
    title: str = ""
    keywords: list[str] = field(default_factory=list)
    category: int | None = None
    ai_generated: bool = False
    fictional: bool = False       # "people and property are fictional" (AI lane)
    needs_release: bool = False   # recognisable person/property in a real photo
    is_video: bool = False
    reasons: list[str] = field(default_factory=list)   # why rejected / warnings
    qc: dict[str, Any] = field(default_factory=dict)
    exported_batch: str = ""
    created_at: str = ""

    @property
    def raster_path(self) -> str:
        """The image the QC / dedupe / vision steps should look at."""
        return self.preview_path or self.path
