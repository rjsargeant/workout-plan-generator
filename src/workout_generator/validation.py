"""Conservative deterministic validation; not a medical safety certification."""
from __future__ import annotations

import re
from typing import Literal

from .models import Equipment, Evaluation, Finding, FitnessProfile, WorkoutPlan

# Deliberately conservative known-incompatible terms; unknown exercises are warned about.
GYM_ONLY = ("barbell", "smith machine", "cable", "lat pulldown", "leg press", "hack squat", "machine", "treadmill", "rowing machine", "elliptical", "bench press", "pull-up", "chin-up")
DUMBBELL_ONLY = ("dumbbell", "db ")
# Explicit movement restriction phrases, not diagnosis from vague injury labels.
RESTRICTIONS = {
    "no overhead pressing": ("overhead press", "shoulder press", "military press", "push press", "arnold press"),
    "avoid overhead pressing": ("overhead press", "shoulder press", "military press", "push press", "arnold press"),
    "no squats": ("squat",),
    "no lunges": ("lunge",),
    "no jumping": ("jump", "burpee", "plyometric"),
    "no running": ("running", "jogging", "treadmill run", "outdoor run", "run intervals"),
}

def is_running_exercise(name: str) -> bool:
    """Detect clearly running-based movements without banning other sprint activities."""
    name = name.casefold().replace('‑', '-').replace('–', '-')
    if any(term in name for term in ('walk', 'rowing', 'rower', 'bike', 'bicycle', 'cycling', 'cycle', 'swim')):
        return False
    return bool(re.search(r'\b(run|runs|running|jog|jogs|jogging|sprint running|running sprint)\b', name))


def evaluate(plan: WorkoutPlan, profile: FitnessProfile, forbidden: list[str] | None = None) -> Evaluation:
    """Check objective schedule, equipment and explicit restriction constraints."""
    findings: list[Finding] = []
    def add(severity: Literal['error', 'warning', 'info'], code: str, message: str) -> None:
        """Append a structured finding to the evaluation."""
        findings.append(Finding(severity=severity, code=code, message=message))
    if plan.goal != profile.goal or plan.experience != profile.experience:
        add("error", "profile_mismatch", "goal or experience differs from input")
    if plan.days_per_week != profile.days_per_week or len(plan.workout_days) != profile.days_per_week:
        add("error", "day_count", "workout day count does not match requested days")
    days = [d.day_number for d in plan.workout_days]
    weekdays = [d.day_of_week for d in plan.workout_days]
    if sorted(days) != list(range(1, len(days) + 1)) or len(set(weekdays)) != len(weekdays):
        add("error", "schedule", "day numbers or weekdays are repeated/invalid")
    if profile.limitations and not (plan.disclaimer and plan.disclaimer.strip()):
        add("error", "disclaimer", "limitations require a disclaimer")
    if not profile.limitations and plan.disclaimer is not None:
        add("warning", "unexpected_disclaimer", "disclaimer supplied without limitations")
    if not plan.title.strip() or not plan.overview.strip() or not plan.progression_guidance.strip() or not plan.recovery_guidance.strip():
        add("error", "missing_guidance", "plan title, overview, progression and recovery are required")
    restrictions = profile.limitations.casefold() if profile.limitations else ""
    for day in plan.workout_days:
        if not day.exercises or not all([day.focus.strip(), day.warmup.strip(), day.cooldown.strip()]):
            add("error", "incomplete_day", f"Day {day.day_number} is incomplete")
        for exercise in day.exercises:
            name = re.sub(r"\s+", " ", exercise.name.casefold().replace("–", "-"))
            if profile.equipment != Equipment.gym and any(x in name for x in GYM_ONLY):
                add("error", "equipment", f"{exercise.name} needs unavailable gym equipment")
            if profile.equipment == Equipment.none and any(x in name for x in DUMBBELL_ONLY):
                add("error", "equipment", f"{exercise.name} needs dumbbells")
            for phrase, excluded in RESTRICTIONS.items():
                # Avoid substring false positives such as bicycle crunches or rowing sprints.
                conflict = (is_running_exercise(name) if phrase == "no running"
                            else any(x in name for x in excluded))
                if phrase in restrictions and conflict:
                    add("error", "limitation", f"{exercise.name} conflicts with '{phrase}'")
            if forbidden and any(
                (is_running_exercise(name) if term.casefold() in ("run", "jog", "sprint", "running")
                 else re.search(r"\b" + re.escape(term.casefold()) + r"\b", name) is not None)
                for term in forbidden
            ):
                add("error", "scenario_exclusion", f"{exercise.name} violates scenario exclusion")
            declared = [item.casefold().strip() for item in exercise.equipment_required]
            if profile.equipment != Equipment.gym and any(
                any(term in item for term in GYM_ONLY) for item in declared
            ):
                add("error", "equipment", f"{exercise.name} declares unavailable gym equipment")
            if profile.equipment == Equipment.none and any(
                "dumbbell" in item or item == "db" for item in declared
            ):
                add("error", "equipment", f"{exercise.name} declares unavailable dumbbells")
            if profile.equipment == Equipment.none and any(
                item not in ("", "none", "bodyweight", "floor", "wall")
                and not any(term in item for term in GYM_ONLY)
                and "dumbbell" not in item for item in declared
            ):
                add("warning", "equipment_unverified", f"Check equipment for {exercise.name}: {declared}")
    return Evaluation(findings=findings)
