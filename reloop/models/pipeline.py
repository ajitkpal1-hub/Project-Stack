"""Data shapes for the Phase 5 multi-agent workflow.

Input -> Classification -> Knowledge -> Recommendation -> Donation Matching -> Safety Review -> Response.
Each agent reads the result so far and adds its part. `PipelineResult` is what the scan page renders.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from reloop.models.classification import Action, Condition, ScanResult
from reloop.models.knowledge import Answer


class StepStatus(StrEnum):
    DONE = "done"
    CHANGED = "changed"  # the safety review altered something
    SKIPPED = "skipped"  # not applicable, or the service isn't set up
    FAILED = "failed"  # an error; the rest of the pipeline still ran


class AgentStep(BaseModel):
    agent: str  # display name, e.g. "Knowledge"
    status: StepStatus
    summary: str  # one plain sentence on what this step did


class Option(BaseModel):
    """One way to deal with the item, ranked by the waste hierarchy."""

    action: Action
    title: str
    detail: str


class DonationStatus(StrEnum):
    ELIGIBLE = "eligible"  # user confirmed condition, item is safe to pass on
    NEEDS_CONDITION = "needs_condition"  # could be, once the user confirms condition
    NOT_ELIGIBLE = "not_eligible"  # hazardous, medical, broken or not reusable
    NOT_APPLICABLE = "not_applicable"  # we couldn't identify the item yet


class Partner(BaseModel):
    """A verified receiving organisation. Filled from the admin-verified directory (Phase 7)."""

    name: str
    locality: str
    accepts: list[str] = Field(default_factory=list)


class DonationMatch(BaseModel):
    status: DonationStatus
    reason: str
    receiver_types: list[str] = Field(default_factory=list)  # general kinds of receiver, never invented names
    partners: list[Partner] = Field(default_factory=list)  # only verified partners


class PipelineResult(BaseModel):
    scan: ScanResult
    knowledge: Answer | None = None
    options: list[Option] = Field(default_factory=list)
    donation: DonationMatch | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    condition: Condition | None = None
