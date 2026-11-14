"""Structured output of the waste classifier.

The AI fills `AIClassification` (schema enforced by structured outputs). Python then
applies safety guardrails and produces `ScanResult`, which is what the UI renders.
Certainty is qualitative on purpose: we never show a made-up percentage.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from reloop.models.categories import WasteCategory


class Certainty(StrEnum):
    CLEAR = "clear"  # the item and its lane are unambiguous in the photo
    LIKELY = "likely"  # probable, but something could change the answer
    UNSURE = "unsure"  # cannot tell from the photo; must ask before advising


class ReuseStatus(StrEnum):
    POSSIBLY_REUSABLE = "possibly_reusable"  # could be reused IF the user confirms condition
    NOT_REUSABLE = "not_reusable"
    UNKNOWN = "unknown"


class Action(StrEnum):
    DONATE = "donate"
    REPAIR = "repair"
    REUSE = "reuse"
    RECYCLE = "recycle"
    COMPOST = "compost"
    SPECIAL_HANDLING = "special_handling"  # hazardous, e-waste, medical routes
    DISPOSE = "dispose"
    ASK_FIRST = "ask_first"  # not enough information to advise safely


class Component(BaseModel):
    name: str = Field(description="Part of the item, e.g. 'glass bottle' or 'plastic cap'")
    material: str = Field(description="Main material, e.g. glass, PET plastic, cotton, lithium battery")
    category: WasteCategory


class AIClassification(BaseModel):
    """What the vision model returns. Every field is required by the schema."""

    item_detected: bool = Field(description="False if no household item or waste is visible (e.g. blank, a person, a screen of text)")
    identified_item: str = Field(description="Short plain-English name of the main item, e.g. 'Old mobile phone charger'")
    components: list[Component] = Field(description="Separate parts made of different materials. One entry for a single-material item.")
    primary_category: WasteCategory
    certainty: Certainty
    certainty_reason: str = Field(description="One sentence on what makes the identification clear or uncertain")
    reuse_status: ReuseStatus
    possibly_hazardous: bool = Field(description="True if the item may contain batteries, chemicals, sharps, mercury, medicine or biological material")
    recommended_action: Action
    action_summary: str = Field(description="One or two plain sentences telling the household what to do")
    safety_warnings: list[str] = Field(description="Concrete handling warnings. Empty list if none apply.")
    disposal_steps: list[str] = Field(description="2-5 short ordered steps for correct segregation or handover in an Indian household")
    clarifying_questions: list[str] = Field(description="Questions to ask the user when the photo cannot settle category or safety. Empty if none needed.")


class ScanResult(AIClassification):
    """AIClassification after Python guardrails. This is what pages render."""

    guardrail_notes: list[str] = Field(default_factory=list)
    needs_condition_check: bool = False
    demo: bool = False  # True when produced by the mock classifier, never by real AI


class Condition(StrEnum):
    WORKS_CLEAN = "works_clean"
    NEEDS_REPAIR = "needs_repair"
    BROKEN = "broken"
    NOT_SURE = "not_sure"


CONDITION_LABELS: dict[Condition, str] = {
    Condition.WORKS_CLEAN: "It works and is clean",
    Condition.NEEDS_REPAIR: "It needs cleaning or a small repair",
    Condition.BROKEN: "It's broken or worn out",
    Condition.NOT_SURE: "I'm not sure",
}
