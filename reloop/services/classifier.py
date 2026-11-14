"""Vision classifiers. The provider is chosen by settings, so it can be swapped.

- ClaudeClassifier: real analysis through the Anthropic API.
- MockClassifier: deterministic answers for tests and a clearly labelled demo mode.
  It never pretends to be real AI (results carry demo=True).
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Protocol

from reloop.config import Settings
from reloop.models.categories import WasteCategory
from reloop.models.classification import (
    Action,
    AIClassification,
    Certainty,
    Component,
    ReuseStatus,
)
from reloop.utils.images import PreparedImage

log = logging.getLogger("reloop.classifier")

DEFAULT_MODEL = "claude-opus-5-5"


class ClassifierUnavailable(RuntimeError):
    """The AI service could not produce an answer. The message is safe to show users."""


class Classifier(Protocol):
    is_demo: bool

    def classify(self, image: PreparedImage, note: str | None = None, filename: str | None = None) -> AIClassification: ...


SYSTEM_PROMPT = """You identify household items and waste from a single photo for RELOOP AI, a service for households in India (pilot: Thakurli, Dombivli and Kalyan, Maharashtra).

Waste categories (use exactly one as primary_category, and one per component):
- wet: food scraps, peels, garden waste, flowers
- dry: clean recyclable paper, cardboard, plastic, metal, glass
- reuse: usable items someone could take (furniture, books, toys, utensils, working goods)
- textile: clothes, fabric, bags, shoes
- e-waste: anything with a plug, circuit, cable or screen
- hazardous: batteries, paint, chemicals, pesticides, aerosol cans, tube lights, CFL bulbs
- medical: medicines, syringes, needles, sanitary pads, diapers, masks, bandages
- unsure: you cannot tell what the item is or what it is made of

Rules:
1. Describe only what is visible. Never assume an item works, is clean, is safe, or is suitable for donation from its appearance. If it might be reusable, use reuse_status "possibly_reusable"; the app will ask the user about its condition.
2. Certainty is a word, never a number: "clear" only when both the item and its lane are unambiguous; "likely" when probable; "unsure" when the photo cannot settle it. When unsure, set recommended_action to "ask_first" and add clarifying_questions.
3. Safety first. If the item may contain a battery, chemical, sharp, mercury, medicine or biological material, set possibly_hazardous true, add specific safety_warnings, and never recommend donating it.
4. Medical/biomedical waste is never donatable or reusable.
5. For mixed items, list each material as a separate component (e.g. a tetra pack, a toy with batteries, a bottle with a cap).
6. Give disposal_steps as 2-5 short, practical steps for an Indian household (segregation at home, then handover). Do not name specific organisations, phone numbers, websites, laws or rule numbers; the app adds verified sources separately.
7. If no household item is visible, set item_detected false, primary_category "unsure", certainty "unsure", recommended_action "ask_first".
8. Plain, friendly English. No jargon."""


class ClaudeClassifier:
    is_demo = False

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 60.0):
        import anthropic  # imported lazily so tests and demo mode don't need a key

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
        self._model = model or DEFAULT_MODEL

    def classify(self, image: PreparedImage, note: str | None = None, filename: str | None = None) -> AIClassification:
        # filename is deliberately not sent to the AI (it can contain personal details).
        anthropic = self._anthropic
        text = "Identify this item and classify it."
        if note:
            text += f"\nThe user adds: {note[:300]}"
        started = time.perf_counter()
        try:
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                # On a safety decline, the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium"},
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image.media_type,
                                    "data": base64.standard_b64encode(image.data).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": text},
                        ],
                    }
                ],
                output_format=AIClassification,
            )
        except anthropic.AuthenticationError:
            log.error("classifier auth failed (check LLM_API_KEY)")
            raise ClassifierUnavailable("The AI service isn't set up correctly right now.") from None
        except anthropic.RateLimitError:
            log.warning("classifier rate limited")
            raise ClassifierUnavailable("The AI service is busy. Please try again in a minute.") from None
        except anthropic.BadRequestError as e:
            log.error("classifier bad request: %s", e.message)
            raise ClassifierUnavailable("The AI service couldn't process that photo. Please try another one.") from None
        except anthropic.APIStatusError as e:
            log.error("classifier API error %s", e.status_code)
            raise ClassifierUnavailable("The AI service had a problem. Please try again shortly.") from None
        except anthropic.APIConnectionError:
            log.error("classifier connection error")
            raise ClassifierUnavailable("We couldn't reach the AI service. Please try again shortly.") from None

        elapsed = time.perf_counter() - started
        log.info(
            "classified model=%s stop=%s in=%s out=%s %.1fs request=%s",
            response.model, response.stop_reason, response.usage.input_tokens,
            response.usage.output_tokens, elapsed, getattr(response, "_request_id", None),
        )
        if response.stop_reason == "refusal":
            raise ClassifierUnavailable("The AI service declined to analyse this photo. Please try a different photo of the item.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ClassifierUnavailable("The AI answer was incomplete. Please try again.")
        return response.parsed_output


class MockClassifier:
    """Deterministic stand-in keyed on words in the file name. Used for tests and demo mode."""

    is_demo = True

    def __init__(self, fail: bool = False):
        self._fail = fail

    def classify(self, image: PreparedImage, note: str | None = None, filename: str | None = None) -> AIClassification:
        if self._fail:
            raise ClassifierUnavailable("The AI service had a problem. Please try again shortly.")
        hint = f"{filename or ''} {note or ''}".lower()
        for keyword, factory in _MOCK_LIBRARY:
            if keyword in hint:
                return factory()
        return _mock_unsure()


def _mock_charger() -> AIClassification:
    return AIClassification(
        item_detected=True, identified_item="Mobile phone charger with cable",
        components=[
            Component(name="charger block", material="plastic and circuit board", category=WasteCategory.E_WASTE),
            Component(name="cable", material="copper wire in plastic", category=WasteCategory.E_WASTE),
        ],
        primary_category=WasteCategory.E_WASTE, certainty=Certainty.CLEAR,
        certainty_reason="A wall charger and cable are clearly visible.",
        reuse_status=ReuseStatus.POSSIBLY_REUSABLE, possibly_hazardous=True,
        recommended_action=Action.SPECIAL_HANDLING,
        action_summary="Chargers are e-waste. If it still works, someone may be able to use it; otherwise give it to an e-waste collector.",
        safety_warnings=["Don't put electronics in the wet or dry bin."],
        disposal_steps=["Keep it separate from other waste.", "Wrap the cable so it doesn't tangle.", "Hand it to an authorised e-waste collector or drop-off point."],
        clarifying_questions=[],
    )


def _mock_bottle() -> AIClassification:
    return AIClassification(
        item_detected=True, identified_item="Plastic water bottle with cap",
        components=[
            Component(name="bottle", material="PET plastic", category=WasteCategory.DRY),
            Component(name="cap", material="HDPE plastic", category=WasteCategory.DRY),
        ],
        primary_category=WasteCategory.DRY, certainty=Certainty.CLEAR,
        certainty_reason="A clear plastic bottle is clearly visible.",
        reuse_status=ReuseStatus.NOT_REUSABLE, possibly_hazardous=False,
        recommended_action=Action.RECYCLE,
        action_summary="Rinse it, let it dry and put it in the dry waste bin.",
        safety_warnings=[],
        disposal_steps=["Empty and rinse the bottle.", "Let it dry.", "Crush it to save space.", "Put it in the dry waste bin."],
        clarifying_questions=[],
    )


def _mock_medicine() -> AIClassification:
    return AIClassification(
        item_detected=True, identified_item="Strip of tablets",
        components=[Component(name="blister strip", material="foil and plastic with medicine", category=WasteCategory.MEDICAL)],
        primary_category=WasteCategory.MEDICAL, certainty=Certainty.LIKELY,
        certainty_reason="It looks like a medicine strip but the label isn't readable.",
        reuse_status=ReuseStatus.POSSIBLY_REUSABLE, possibly_hazardous=True,
        recommended_action=Action.DONATE,  # deliberately wrong: guardrails must override this
        action_summary="Medicines need separate handling.",
        safety_warnings=["Keep medicines away from children and animals."],
        disposal_steps=["Keep the medicine in its strip.", "Put it in a separate, marked bag.", "Hand it over through local medical waste collection."],
        clarifying_questions=[],
    )


def _mock_chair() -> AIClassification:
    return AIClassification(
        item_detected=True, identified_item="Wooden chair",
        components=[Component(name="chair", material="wood", category=WasteCategory.REUSE)],
        primary_category=WasteCategory.REUSE, certainty=Certainty.CLEAR,
        certainty_reason="A wooden chair is clearly visible.",
        reuse_status=ReuseStatus.POSSIBLY_REUSABLE, possibly_hazardous=False,
        recommended_action=Action.DONATE,
        action_summary="If it's sturdy, a neighbour or NGO could use it.",
        safety_warnings=[],
        disposal_steps=["Check it's stable and has no loose nails.", "Wipe it clean.", "List it for donation."],
        clarifying_questions=[],
    )


def _mock_unsure() -> AIClassification:
    return AIClassification(
        item_detected=True, identified_item="Unidentified item",
        components=[Component(name="item", material="unknown", category=WasteCategory.UNSURE)],
        primary_category=WasteCategory.UNSURE, certainty=Certainty.UNSURE,
        certainty_reason="The photo doesn't show enough detail to tell what this is.",
        reuse_status=ReuseStatus.UNKNOWN, possibly_hazardous=False,
        recommended_action=Action.ASK_FIRST,
        action_summary="We can't tell what this is from the photo.",
        safety_warnings=[],
        disposal_steps=["Keep it aside for now.", "Try another photo in good light, or tell us what it is."],
        clarifying_questions=["What is the item, and what is it mostly made of?", "Does it have a battery, plug or any liquid inside?"],
    )


_MOCK_LIBRARY = [
    ("charger", _mock_charger),
    ("bottle", _mock_bottle),
    ("medicine", _mock_medicine),
    ("tablet", _mock_medicine),
    ("chair", _mock_chair),
]


def get_classifier(settings: Settings) -> Classifier | None:
    """Return the configured classifier, or None when AI isn't configured."""
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return MockClassifier()
    if provider == "anthropic" and settings.llm_api_key:
        return ClaudeClassifier(api_key=settings.llm_api_key, model=settings.llm_model or None)
    return None
