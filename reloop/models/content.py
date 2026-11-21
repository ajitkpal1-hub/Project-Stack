"""Internal content pipeline: short-video (Reel / YouTube Shorts) scripts about sorting waste.

Never shown on the website. Drafts are written only from passages in the loaded official
documents, checked by Python rules after the model, and always reviewed by a person before posting.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from reloop.models.categories import WasteCategory


class ReelShot(BaseModel):
    number: int = Field(description="Shot number, starting at 1")
    seconds: int = Field(description="Length of the shot in seconds, 1 to 10")
    visual: str = Field(description="What the camera shows, filmable by one person at home with a phone (no stock footage, no logos)")
    on_screen_text: str = Field(description="Short text overlay, at most 8 words")
    voiceover: str = Field(description="What the presenter says during this shot, one or two short sentences")


class KeyFact(BaseModel):
    fact: str = Field(description="One factual claim the script relies on, in plain words")
    source_number: int = Field(description="Number of the passage this fact comes from (1-based, as given in the prompt)")


class ReelScriptAI(BaseModel):
    """What the model returns. Every field is required by the schema."""

    title: str = Field(description="Working title for the team, e.g. 'Where do used batteries go?'")
    hook: str = Field(description="The spoken opening line, at most 12 words, that makes people stop scrolling")
    hook_on_screen: str = Field(description="On-screen text for the first 2 seconds, at most 6 words")
    shots: list[ReelShot] = Field(description="4 to 7 shots, about 30 to 45 seconds in total")
    caption: str = Field(description="Post caption, 2 to 4 short sentences, plain English, ends with a gentle call to action")
    hashtags: list[str] = Field(description="5 to 8 hashtags, each starting with #, relevant to waste sorting in India")
    key_facts: list[KeyFact] = Field(description="Every factual claim used in the script, each tied to a passage number")
    safety_note: str = Field(description="One-line safety reminder from the passages, or an empty string if none applies")


class ReelStatus(StrEnum):
    DRAFT = "draft"  # ready for a person to review
    NEEDS_FIX = "needs_fix"  # rules found something a reviewer must change before filming
    NO_SOURCE = "no_source"  # the documents don't cover the topic, so nothing was written


class ReelTopic(BaseModel):
    key: str  # stable id, e.g. "batteries"
    title: str  # e.g. "Used batteries"
    lane: WasteCategory
    queries: list[str]  # how to search the knowledge base for this topic


class ReelSource(BaseModel):
    number: int
    title: str
    publisher: str | None = None
    published_on: str | None = None
    url: str | None = None


class ReelDraft(BaseModel):
    status: ReelStatus
    topic: ReelTopic
    script: ReelScriptAI | None = None
    sources: list[ReelSource] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)  # what the rules flagged or changed
    demo: bool = False
    model: str | None = None
