"""Replace one exercise via a small strict Groq structured-output request."""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict

from .models import Exercise, FitnessProfile, WorkoutPlan
from .schema import strict_schema
from .service import GenerationError, GroqProvider, _error_detail, classify_error
from .validation import evaluate

LOG = logging.getLogger(__name__)


class SwapResponse(BaseModel):
    """Strict response wrapper containing exactly one replacement exercise."""
    model_config = ConfigDict(extra="forbid")
    exercise: Exercise


def swap_schema() -> dict:
    """Reuse strict-schema transformation with the small swap response model."""
    return strict_schema(SwapResponse)


def replace_exercise(plan: WorkoutPlan, profile: FitnessProfile, day_index: int,
                     exercise_index: int, *, client=None) -> WorkoutPlan:
    """Return a new validated plan; never mutate the existing plan on failure."""
    if not 0 <= day_index < len(plan.workout_days):
        raise ValueError("Invalid workout day")
    day = plan.workout_days[day_index]
    if not 0 <= exercise_index < len(day.exercises):
        raise ValueError("Invalid exercise selection")
    # Select the target by stable day/exercise indices, not by possibly repeated names.
    original = day.exercises[exercise_index]
    others = [ex.name for index, ex in enumerate(day.exercises) if index != exercise_index]
    system = ("You are a fitness workout planner. Replace the selected exercise with a DIFFERENT "
              "exercise serving substantially the same training purpose. Respect the fitness "
              "profile, available equipment, experience and explicit limitations. Avoid exercises "
              "already in this workout day. Do not offer medical advice. Return only the required "
              "structured exercise object. Keep instructions concise.")
    context = {"profile": profile.model_dump(mode="json"), "day_focus": day.focus,
               "existing_exercise": original.model_dump(mode="json"),
               "other_exercises_on_day": others}
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(context)}]
    provider = client or GroqProvider()
    schema = swap_schema()
    # A single recovery attempt is allowed for model JSON-generation failures.
    for attempt in range(2):
        try:
            content, _usage = provider.generate(messages, schema, max_completion_tokens=2048)
            replacement = SwapResponse.model_validate_json(content).exercise
            if replacement.name.casefold().strip() == original.name.casefold().strip():
                raise ValueError("The replacement must be a different exercise")
            candidate = plan.model_copy(deep=True)
            candidate.workout_days[day_index].exercises[exercise_index] = replacement
            evaluation = evaluate(candidate, profile)
            if not evaluation.valid:
                raise ValueError("Replacement violates workout constraints: " + "; ".join(
                    finding.message for finding in evaluation.findings if finding.severity == "error"))
            return candidate
        except Exception as exc:
            LOG.warning("Exercise swap attempt %s failed: %s", attempt + 1, _error_detail(exc))
            if attempt == 0 and (classify_error(exc) in ("json_generation_failure", "token_exhaustion")
                                 or isinstance(exc, ValueError)):
                continue
            raise GenerationError("Unable to swap exercise: " + _error_detail(exc)) from exc
    raise GenerationError("Unable to swap exercise")
