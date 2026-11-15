"""Donation Matching Agent: can this item be donated, and to what kind of receiver?

Rules: never hazardous or medical; never before the user confirms the condition.
Receivers are described by kind only. Named organisations come solely from the
admin-verified partner directory (Phase 7), which is empty until then; we never invent one.
"""

from __future__ import annotations

from typing import Protocol

from reloop.models.categories import WasteCategory
from reloop.models.classification import Action, ReuseStatus, ScanResult
from reloop.models.pipeline import AgentStep, DonationMatch, DonationStatus, Partner, StepStatus
from reloop.services.guardrails import NEVER_DONATE, item_unclear

NAME = "Donation matching"

RECEIVER_TYPES: dict[WasteCategory, list[str]] = {
    WasteCategory.REUSE: ["Neighbours and housing-society groups", "Community donation drives", "Schools or hostels, for books and stationery"],
    WasteCategory.TEXTILE: ["Clothing donation drives", "Charities that accept clean, wearable clothes"],
    WasteCategory.E_WASTE: ["Schools or community centres that accept working electronics", "Refurbishers who resell working devices"],
    WasteCategory.DRY: ["Neighbours who reuse jars and containers"],
}
DEFAULT_RECEIVERS = ["Neighbours and housing-society groups", "Community donation drives"]


class PartnerDirectory(Protocol):
    def find(self, category: WasteCategory) -> list[Partner]: ...


class EmptyPartnerDirectory:
    """Until verified partners exist (Phase 7) there is nothing to match against."""

    def find(self, category: WasteCategory) -> list[Partner]:
        return []


class DonationMatchingAgent:
    def __init__(self, directory: PartnerDirectory | None = None):
        self.directory = directory or EmptyPartnerDirectory()

    def run(self, scan: ScanResult) -> tuple[DonationMatch, AgentStep]:
        categories = {scan.primary_category, *(c.category for c in scan.components)}

        if categories & NEVER_DONATE:
            match = DonationMatch(status=DonationStatus.NOT_ELIGIBLE,
                                  reason="Hazardous and medical items can never be donated.")
        elif item_unclear(scan):
            match = DonationMatch(status=DonationStatus.NOT_APPLICABLE, reason="We need to know what the item is first.")
        elif scan.needs_condition_check:
            match = DonationMatch(status=DonationStatus.NEEDS_CONDITION,
                                  reason="It might be donatable. Tell us its condition first, because a photo can't show whether it works or is clean.")
        elif scan.recommended_action == Action.DONATE:
            receivers = RECEIVER_TYPES.get(scan.primary_category, DEFAULT_RECEIVERS)
            partners = self.directory.find(scan.primary_category)
            match = DonationMatch(status=DonationStatus.ELIGIBLE, receiver_types=receivers, partners=partners,
                                  reason="You said it works and is clean, so it can go to someone who needs it.")
        elif scan.reuse_status == ReuseStatus.NOT_REUSABLE:
            match = DonationMatch(status=DonationStatus.NOT_ELIGIBLE, reason="It isn't in a state someone else could use.")
        else:
            match = DonationMatch(status=DonationStatus.NOT_ELIGIBLE, reason="Donating isn't the best route for this item.")

        summaries = {
            DonationStatus.ELIGIBLE: f"Can be donated. {len(match.partners)} verified partner(s) on record, so we suggest kinds of receiver.",
            DonationStatus.NEEDS_CONDITION: "Possibly donatable, once you confirm its condition.",
            DonationStatus.NOT_ELIGIBLE: f"Not for donation: {match.reason[0].lower()}{match.reason[1:]}",
            DonationStatus.NOT_APPLICABLE: "Skipped until we know what the item is.",
        }
        status = StepStatus.SKIPPED if match.status == DonationStatus.NOT_APPLICABLE else StepStatus.DONE
        return match, AgentStep(agent=NAME, status=status, summary=summaries[match.status])
