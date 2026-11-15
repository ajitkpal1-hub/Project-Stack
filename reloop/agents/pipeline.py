"""The multi-agent workflow.

Input -> Classification -> Knowledge -> Recommendation -> Donation Matching -> Safety Review -> Response.

Only Classification is essential: if it fails, the scan fails with a friendly message.
Every other agent degrades gracefully, and the Safety Review always runs last.
"""

from __future__ import annotations

import logging

from reloop.agents import classification as classification_mod
from reloop.agents import knowledge as knowledge_mod
from reloop.agents.classification import ClassificationAgent
from reloop.agents.donation import DonationMatchingAgent, PartnerDirectory
from reloop.agents.knowledge import KnowledgeAgent
from reloop.agents.recommendation import RecommendationAgent
from reloop.agents.safety import SafetyReviewAgent
from reloop.models.classification import Condition
from reloop.models.pipeline import AgentStep, PipelineResult, StepStatus
from reloop.rag.answer import KnowledgeAssistant
from reloop.services.classifier import Classifier, ClassifierUnavailable
from reloop.services.guardrails import apply_guardrails
from reloop.utils.images import PreparedImage

log = logging.getLogger("reloop.pipeline")


class WastePipeline:
    def __init__(self, classifier: Classifier | None, assistant: KnowledgeAssistant | None = None,
                 directory: PartnerDirectory | None = None):
        self.classification = ClassificationAgent(classifier)
        self.knowledge = KnowledgeAgent(assistant)
        self.recommendation = RecommendationAgent()
        self.donation = DonationMatchingAgent(directory)
        self.safety = SafetyReviewAgent()

    def run(self, image: PreparedImage, note: str | None = None, filename: str | None = None) -> PipelineResult:
        """Raises ClassifierUnavailable when the item can't be classified."""
        if self.classification.classifier is None:
            raise ClassifierUnavailable("AI scanning isn't switched on yet. Please check back soon.")
        scan, s1 = self.classification.run(image, note, filename)
        knowledge, s2 = self.knowledge.run(scan)
        scan, options, s3 = self.recommendation.run(scan)
        donation, s4 = self.donation.run(scan)
        draft = PipelineResult(scan=scan, knowledge=knowledge, options=options, donation=donation, steps=[s1, s2, s3, s4])
        return self._finish(draft)

    def rerun_with_condition(self, previous: PipelineResult, condition: Condition) -> PipelineResult:
        """Re-plan after the user confirms the item's condition. No new AI calls.

        `previous` comes back from the browser, so the scan is re-checked by the
        guardrails before anything is built on it.
        """
        scan = apply_guardrails(previous.scan, demo=previous.scan.demo)
        s1 = AgentStep(agent=classification_mod.NAME, status=StepStatus.DONE,
                       summary=f"Used your earlier scan of '{scan.identified_item}'.")
        s2 = AgentStep(agent=knowledge_mod.NAME, status=StepStatus.DONE if previous.knowledge else StepStatus.SKIPPED,
                       summary="Kept the official guidance found for your scan." if previous.knowledge
                       else "No official guidance was found for this scan.")
        scan, options, s3 = self.recommendation.run(scan, condition)
        donation, s4 = self.donation.run(scan)
        draft = PipelineResult(scan=scan, knowledge=previous.knowledge, options=options, donation=donation,
                               steps=[s1, s2, s3, s4], condition=condition)
        return self._finish(draft)

    def _finish(self, draft: PipelineResult) -> PipelineResult:
        result, s5 = self.safety.run(draft)
        result.steps = [*draft.steps, s5]
        log.info("pipeline category=%s action=%s donation=%s steps=%s", result.scan.primary_category,
                 result.scan.recommended_action, result.donation.status if result.donation else None,
                 ",".join(f"{s.agent}:{s.status.value}" for s in result.steps))
        return result
