"""Deterministic safety rules applied AFTER the AI answers.

The model is instructed to follow these too, but the app never relies on that alone.
(In Phase 5 these become part of the Review and Safety Agent.)
"""

from reloop.models.categories import WasteCategory
from reloop.models.classification import (
    Action,
    AIClassification,
    Certainty,
    Condition,
    ReuseStatus,
    ScanResult,
)

HAZARD_CATEGORIES = {WasteCategory.HAZARDOUS, WasteCategory.MEDICAL, WasteCategory.E_WASTE}
NEVER_DONATE = {WasteCategory.HAZARDOUS, WasteCategory.MEDICAL}

STANDARD_WARNINGS = {
    WasteCategory.MEDICAL: "Never donate or reuse medical waste. Wrap sharps in a hard container before handing them over.",
    WasteCategory.HAZARDOUS: "Keep it sealed, away from children and heat, and out of the regular bins.",
    WasteCategory.E_WASTE: "Don't break it open or burn it. Batteries inside can leak or catch fire.",
}


def item_unclear(scan: AIClassification) -> bool:
    """True when we don't know what the item is (as opposed to knowing it but needing its condition)."""
    return not scan.item_detected or scan.certainty == Certainty.UNSURE or scan.primary_category == WasteCategory.UNSURE


def apply_guardrails(ai: AIClassification, demo: bool = False) -> ScanResult:
    # Start from the AI fields only, so re-checking a returned ScanResult recomputes everything.
    result = ScanResult(**ai.model_dump(include=set(AIClassification.model_fields)), demo=demo)
    notes: list[str] = []
    categories = {result.primary_category, *(c.category for c in result.components)}

    # 1. Medical or hazardous anywhere in the item: never donate or reuse.
    blocked = categories & NEVER_DONATE
    if blocked:
        if result.reuse_status != ReuseStatus.NOT_REUSABLE:
            result.reuse_status = ReuseStatus.NOT_REUSABLE
            notes.append("Marked not reusable because it contains hazardous or medical material.")
        if result.recommended_action in {Action.DONATE, Action.REUSE, Action.REPAIR}:
            result.recommended_action = Action.SPECIAL_HANDLING
            notes.append("Changed the advice to special handling. Hazardous and medical items can't be donated.")
        result.possibly_hazardous = True

    # 2. Any hazard category means the hazard flag is on.
    if categories & HAZARD_CATEGORIES:
        result.possibly_hazardous = True

    # 3. Standard warnings for each hazard category present (no duplicates).
    for cat in (WasteCategory.MEDICAL, WasteCategory.HAZARDOUS, WasteCategory.E_WASTE):
        if cat in categories and STANDARD_WARNINGS[cat] not in result.safety_warnings:
            result.safety_warnings.append(STANDARD_WARNINGS[cat])

    # 4. Unsure or nothing detected: don't advise, ask.
    if not result.item_detected or result.certainty == Certainty.UNSURE:
        if result.recommended_action != Action.ASK_FIRST:
            result.recommended_action = Action.ASK_FIRST
            notes.append("The photo wasn't clear enough, so we're asking before giving advice.")
        if not result.clarifying_questions:
            result.clarifying_questions = ["What is the item, and what is it mostly made of?"]

    # 5. Never trust a photo for condition: anything possibly reusable needs the user's confirmation.
    result.needs_condition_check = result.reuse_status == ReuseStatus.POSSIBLY_REUSABLE and not blocked
    if result.needs_condition_check and result.recommended_action == Action.DONATE:
        notes.append("We'll suggest donating only after you confirm the condition.")

    result.guardrail_notes = notes
    return result


def apply_condition(result: ScanResult, condition: Condition) -> ScanResult:
    """Update the recommendation after the user confirms the item's condition."""
    r = result.model_copy(deep=True)
    r.needs_condition_check = False
    lane = r.primary_category
    if lane in NEVER_DONATE:
        return r  # guardrails already fixed these; condition changes nothing

    if condition == Condition.WORKS_CLEAN:
        r.reuse_status = ReuseStatus.POSSIBLY_REUSABLE
        r.recommended_action = Action.DONATE
        r.action_summary = "Since it works and is clean, it could go to someone who needs it. List it for donation."
    elif condition == Condition.NEEDS_REPAIR:
        r.recommended_action = Action.REPAIR
        r.action_summary = "A small clean-up or repair could give it a second life. Fix it and then donate it, or offer it as 'needs repair'."
    elif condition == Condition.BROKEN:
        r.reuse_status = ReuseStatus.NOT_REUSABLE
        if lane == WasteCategory.E_WASTE:
            r.recommended_action = Action.SPECIAL_HANDLING
            r.action_summary = "Broken electronics are e-waste. Give it to an authorised e-waste collector."
        elif lane == WasteCategory.TEXTILE:
            r.recommended_action = Action.RECYCLE
            r.action_summary = "Worn-out fabric can go to a textile collection point instead of the bin."
        else:
            r.recommended_action = Action.RECYCLE
            r.action_summary = "It can't be reused. Separate its materials and put each part in the right bin."
    else:  # NOT_SURE
        r.recommended_action = Action.ASK_FIRST
        r.action_summary = "Check whether it works and is clean before donating it. If in doubt, keep it aside until you can check."
    r.guardrail_notes = [*r.guardrail_notes, f"Updated after you said: {condition.value.replace('_', ' ')}."]
    return r
