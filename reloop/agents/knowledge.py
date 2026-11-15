"""Knowledge Agent: what do the loaded official documents say about this item?

Builds a question from the classification and asks the RAG assistant. Answers cite
only ingested documents; if nothing relevant is found the result says so.
"""

from __future__ import annotations

import logging

from reloop.models.categories import LANES_BY_CATEGORY
from reloop.models.classification import ScanResult
from reloop.models.knowledge import Answer, AnswerMode
from reloop.models.pipeline import AgentStep, StepStatus
from reloop.rag.answer import KnowledgeAssistant
from reloop.services.guardrails import item_unclear

log = logging.getLogger("reloop.agents.knowledge")
NAME = "Knowledge"


def build_question(scan: ScanResult) -> str:
    lane = LANES_BY_CATEGORY[scan.primary_category]
    item = " ".join(scan.identified_item.split())[:120]
    return f"How should a household handle and dispose of {item} ({lane.name.lower()})?"


class KnowledgeAgent:
    def __init__(self, assistant: KnowledgeAssistant | None):
        self.assistant = assistant

    def run(self, scan: ScanResult) -> tuple[Answer | None, AgentStep]:
        if item_unclear(scan):
            return None, AgentStep(agent=NAME, status=StepStatus.SKIPPED,
                                   summary="Skipped until we know what the item is.")
        if self.assistant is None:
            return None, AgentStep(agent=NAME, status=StepStatus.SKIPPED,
                                   summary="The knowledge base isn't available, so there's no official guidance to show.")
        try:
            answer = self.assistant.answer(build_question(scan))
        except Exception:  # noqa: BLE001 - one failing agent must not break the scan
            log.exception("knowledge agent failed")
            return None, AgentStep(agent=NAME, status=StepStatus.FAILED,
                                   summary="We couldn't check the official documents this time.")

        if answer.mode == AnswerMode.PASSAGES:
            # Scans quote the two most relevant passages word for word (no second AI call).
            answer = answer.model_copy(update={"sources": answer.sources[:2],
                                               "message": "From the official documents, quoted word for word:"})
        n = len(answer.sources)
        summaries = {
            AnswerMode.GROUNDED: (StepStatus.DONE, f"Found guidance in {n} passage(s) from the loaded official documents."),
            AnswerMode.PASSAGES: (StepStatus.DONE, f"Found {n} relevant passage(s); showing them word for word."),
            AnswerMode.NO_SOURCE: (StepStatus.DONE, "The loaded documents don't cover this item, so we don't quote any."),
            AnswerMode.UNAVAILABLE: (StepStatus.FAILED, "We couldn't reach the knowledge base this time."),
        }
        status, summary = summaries[answer.mode]
        return answer, AgentStep(agent=NAME, status=status, summary=summary)
