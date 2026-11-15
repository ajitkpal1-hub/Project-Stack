"""Recommendation Agent: rank what the household can do, following the waste hierarchy.

Reuse -> repair -> donate -> recycle/compost -> special handling -> dispose.
Deterministic on purpose: the AI already described the item, and ranking options by
fixed rules is cheaper, testable and can't invent anything. Text is general household
practice, never a named organisation or rule.
"""

from __future__ import annotations

from reloop.models.categories import WasteCategory
from reloop.models.classification import Action, Condition, ScanResult
from reloop.models.pipeline import AgentStep, Option, StepStatus
from reloop.services.guardrails import apply_condition, item_unclear

NAME = "Recommendation"

TITLES: dict[Action, str] = {
    Action.DONATE: "Donate it",
    Action.REPAIR: "Repair it",
    Action.REUSE: "Reuse it at home",
    Action.RECYCLE: "Recycle it",
    Action.COMPOST: "Compost it",
    Action.SPECIAL_HANDLING: "Hand it over for special handling",
    Action.DISPOSE: "Dispose of it",
    Action.ASK_FIRST: "Tell us a bit more",
}

# Fallback options per lane, in hierarchy order. Shown after the main recommendation.
FALLBACKS: dict[WasteCategory, list[tuple[Action, str]]] = {
    WasteCategory.WET: [
        (Action.COMPOST, "Compost it at home or in a society composter."),
        (Action.DISPOSE, "Otherwise put it in the wet waste (green) bin, with no plastic."),
    ],
    WasteCategory.DRY: [
        (Action.REUSE, "Containers and jars can often be reused for storage at home."),
        (Action.RECYCLE, "Rinse and dry it, then put it in the dry waste (blue) bin or give it to a kabadiwala."),
    ],
    WasteCategory.REUSE: [
        (Action.REPAIR, "If it needs a small fix, a local repair shop can give it a second life."),
        (Action.REUSE, "Pass it on to family, friends or neighbours who can use it."),
        (Action.RECYCLE, "If it can't be used again, separate its materials and recycle what you can."),
    ],
    WasteCategory.TEXTILE: [
        (Action.REUSE, "Old cloth makes good cleaning rags or bags."),
        (Action.RECYCLE, "Worn-out fabric can go to a textile collection point instead of the bin."),
    ],
    WasteCategory.E_WASTE: [
        (Action.REPAIR, "A mobile or electronics repair shop may be able to fix it."),
        (Action.SPECIAL_HANDLING, "Otherwise give it to an authorised e-waste collector. Never the regular bin."),
    ],
    WasteCategory.HAZARDOUS: [
        (Action.SPECIAL_HANDLING, "Keep it sealed and separate, and hand it over at a hazardous-waste collection."),
    ],
    WasteCategory.MEDICAL: [
        (Action.SPECIAL_HANDLING, "Wrap and mark it separately and give it to the municipal collector as biomedical waste."),
    ],
    WasteCategory.UNSURE: [],
}


class RecommendationAgent:
    def run(self, scan: ScanResult, condition: Condition | None = None) -> tuple[ScanResult, list[Option], AgentStep]:
        if condition is not None:
            scan = apply_condition(scan, condition)

        primary = Option(action=scan.recommended_action, title=TITLES[scan.recommended_action], detail=scan.action_summary)
        if item_unclear(scan):
            return scan, [primary], AgentStep(agent=NAME, status=StepStatus.DONE,
                                              summary="We need to know what the item is before ranking options.")

        options = [primary]
        for action, detail in FALLBACKS[scan.primary_category]:
            if action != primary.action and all(o.action != action for o in options):
                options.append(Option(action=action, title=TITLES[action], detail=detail))
        options = options[:3]

        if condition is not None:
            summary = f"Re-ranked the options after you said: {condition.value.replace('_', ' ')}."
        else:
            summary = f"Ranked {len(options)} option(s), starting with: {primary.title.lower()}."
        return scan, options, AgentStep(agent=NAME, status=StepStatus.DONE, summary=summary)
