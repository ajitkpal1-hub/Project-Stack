"""Safety Review Agent: the last word before anything reaches the household.

Re-checks the combined output of every earlier agent against fixed rules, and fixes
rather than trusts. Runs after the model, never instead of it. Each fix is recorded in
`scan.guardrail_notes` so the page can show what was changed and why.
"""

from __future__ import annotations

from reloop.models.classification import Action, ReuseStatus
from reloop.models.knowledge import AnswerMode
from reloop.models.pipeline import AgentStep, DonationMatch, DonationStatus, Option, PipelineResult, StepStatus
from reloop.services.guardrails import HAZARD_CATEGORIES, NEVER_DONATE, STANDARD_WARNINGS, item_unclear

NAME = "Safety review"
REUSE_ACTIONS = {Action.DONATE, Action.REUSE, Action.REPAIR}


class SafetyReviewAgent:
    def run(self, result: PipelineResult) -> tuple[PipelineResult, AgentStep]:
        r = result.model_copy(deep=True)
        scan = r.scan
        fixes: list[str] = []
        categories = {scan.primary_category, *(c.category for c in scan.components)}
        blocked = bool(categories & NEVER_DONATE)

        # 1. Hazardous or medical anywhere: no reuse, no donation, hazard flag on.
        if blocked:
            if scan.reuse_status != ReuseStatus.NOT_REUSABLE:
                scan.reuse_status = ReuseStatus.NOT_REUSABLE
                fixes.append("Marked not reusable because it contains hazardous or medical material.")
            if scan.recommended_action in REUSE_ACTIONS:
                scan.recommended_action = Action.SPECIAL_HANDLING
                fixes.append("Changed the main advice to special handling.")
            scan.needs_condition_check = False
            unsafe = [o for o in r.options if o.action in REUSE_ACTIONS]
            if unsafe:
                r.options = [o for o in r.options if o.action not in REUSE_ACTIONS]
                fixes.append("Removed reuse and donation options, which aren't safe for this item.")
            if not any(o.action == Action.SPECIAL_HANDLING for o in r.options):
                r.options.insert(0, Option(action=Action.SPECIAL_HANDLING, title="Hand it over for special handling",
                                           detail="Keep it sealed and separate from other waste, and hand it to the right collector."))
            if r.donation is None or r.donation.status != DonationStatus.NOT_ELIGIBLE or r.donation.partners:
                r.donation = DonationMatch(status=DonationStatus.NOT_ELIGIBLE, reason="Hazardous and medical items can never be donated.")
                fixes.append("Blocked donation.")

        # 2. Hazard categories always carry the hazard flag and the standard warning.
        if categories & HAZARD_CATEGORIES:
            scan.possibly_hazardous = True
            for cat, warning in STANDARD_WARNINGS.items():
                if cat in categories and warning not in scan.safety_warnings:
                    scan.safety_warnings.append(warning)
                    fixes.append("Added a standard safety warning.")

        # 3. Unknown item: ask, don't advise.
        if item_unclear(scan):
            if scan.recommended_action != Action.ASK_FIRST:
                scan.recommended_action = Action.ASK_FIRST
                fixes.append("Asked for more detail instead of advising on an unclear item.")
            if any(o.action != Action.ASK_FIRST for o in r.options):
                r.options = [o for o in r.options if o.action == Action.ASK_FIRST]
            if not scan.clarifying_questions:
                scan.clarifying_questions = ["What is the item, and what is it mostly made of?"]

        # 4. Condition not confirmed yet: never suggest donating.
        if scan.needs_condition_check:
            if any(o.action == Action.DONATE for o in r.options):
                r.options = [o for o in r.options if o.action != Action.DONATE]
                r.options.insert(0, Option(action=Action.ASK_FIRST, title="Check its condition first",
                                           detail="Tell us below whether it works and is clean. Then we'll say if it can be donated."))
                fixes.append("Held back the donation suggestion until you confirm the condition.")
            if r.donation and r.donation.status == DonationStatus.ELIGIBLE:
                r.donation = DonationMatch(status=DonationStatus.NEEDS_CONDITION,
                                           reason="Tell us its condition first, because a photo can't show whether it works or is clean.")
                fixes.append("Held back donation matching until you confirm the condition.")

        # 5. Donation can only be offered when donating is the advice.
        if r.donation and r.donation.status == DonationStatus.ELIGIBLE and scan.recommended_action != Action.DONATE:
            r.donation = DonationMatch(status=DonationStatus.NOT_ELIGIBLE, reason="Donating isn't the best route for this item.")
            fixes.append("Withdrew a donation match that didn't fit the advice.")

        # 6. An answer is only "grounded" if it actually cites a source.
        if r.knowledge and r.knowledge.mode == AnswerMode.GROUNDED and not r.knowledge.sources:
            r.knowledge = None
            fixes.append("Removed an official-guidance note that had no source.")

        if not r.options:
            r.options = [Option(action=Action.ASK_FIRST, title="Tell us a bit more", detail="Add a note about the item and scan again.")]

        scan.guardrail_notes = [*scan.guardrail_notes, *(f for f in fixes if f not in scan.guardrail_notes)]
        if fixes:
            step = AgentStep(agent=NAME, status=StepStatus.CHANGED,
                             summary=f"Checked everything and made {len(fixes)} safety fix(es) before showing it to you.")
        else:
            step = AgentStep(agent=NAME, status=StepStatus.DONE, summary="Checked every step against our safety rules. Nothing needed changing.")
        return r, step
