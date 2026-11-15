"""Classification Agent: photo -> what the item is and which lane it goes in.

Wraps the vision classifier (Claude or the labelled mock) and applies the Python
guardrails straight away, so every later agent works from safe, normalised data.
"""

from __future__ import annotations

from reloop.models.classification import ScanResult
from reloop.models.pipeline import AgentStep, StepStatus
from reloop.services.classifier import Classifier
from reloop.services.guardrails import apply_guardrails
from reloop.utils.images import PreparedImage

NAME = "Classification"


class ClassificationAgent:
    def __init__(self, classifier: Classifier | None):
        self.classifier = classifier

    def run(self, image: PreparedImage, note: str | None, filename: str | None) -> tuple[ScanResult, AgentStep]:
        """Raises ClassifierUnavailable: without a classification nothing else can run."""
        assert self.classifier is not None  # WastePipeline.run checks this first
        ai = self.classifier.classify(image, note=note, filename=filename)
        scan = apply_guardrails(ai, demo=self.classifier.is_demo)
        if not scan.item_detected:
            summary = "No household item was visible, so we'll ask before advising."
        else:
            source = "a sample answer (demo mode)" if scan.demo else "the photo"
            summary = f"Identified '{scan.identified_item}' in the {scan.primary_category.value} lane from {source}."
        return scan, AgentStep(agent=NAME, status=StepStatus.DONE, summary=summary)
