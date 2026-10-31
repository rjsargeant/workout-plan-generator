"""Shared Markdown report for CLI output, Streamlit display and download."""
from __future__ import annotations

import re

from .disclaimers import caution_text
from .models import WorkoutPlan


def additional_caution(text: str) -> str:
    """Normalize an LLM-supplied caution prefix without changing its meaning."""
    clean = re.sub(r"^(?:(?:additional\s+)?caution\s*:\s*)+", "", text.strip(), flags=re.IGNORECASE)
    return clean


def render_markdown(plan: WorkoutPlan, limitations: str | None = None) -> str:
    """Render a complete Markdown document, including the standard disclaimer."""
    lines = [f"## {plan.title}", "", plan.overview, "",
             f"**Goal:** {plan.goal.value.replace('_', ' ').title()}  ",
             f"**Experience:** {plan.experience.value.title()}  ",
             f"**Training days per week:** {plan.days_per_week}", ""]
    for day in plan.workout_days:
        lines.extend([f"### Day {day.day_number} · {day.day_of_week} — {day.focus}", "",
                      f"**Warm-up:** {day.warmup}", "",
                      "| Exercise | Sets | Reps / Duration | Rest | Instructions | Equipment |",
                      "|---|---:|---|---|---|---|"])
        for exercise in day.exercises:
            prescription = exercise.repetitions or f"{exercise.duration_seconds} seconds"
            cells = [exercise.name, str(exercise.sets), prescription,
                     f"{exercise.rest_seconds} seconds", exercise.instructions,
                     ", ".join(exercise.equipment_required) or "None"]
            cells = [str(value).replace("|", "\\|").replace("\n", " ") for value in cells]
            lines.append("| " + " | ".join(cells) + " |")
        lines.extend(["", f"**Cooldown:** {day.cooldown}", ""])
    lines.extend(["### Progression", "", plan.progression_guidance, "",
                  "### Recovery", "", plan.recovery_guidance, ""])
    lines.extend(["---", "", "**Caution**", "", caution_text(limitations), ""])
    return "\n".join(lines)


def render_plain_text(plan: WorkoutPlan, limitations: str | None = None) -> str:
    """Produce a readable plain-text version of the same workout content."""
    lines = [plan.title, "", plan.overview, "",
             f"Goal: {plan.goal.value.replace('_', ' ').title()}",
             f"Experience: {plan.experience.value.title()}",
             f"Training days per week: {plan.days_per_week}", ""]
    for day in plan.workout_days:
        lines += [f"Day {day.day_number} - {day.day_of_week} - {day.focus}",
                  f"Warm-up: {day.warmup}", ""]
        for ex in day.exercises:
            prescription = ex.repetitions or f"{ex.duration_seconds} seconds"
            equipment = ", ".join(ex.equipment_required) or "None"
            lines += [f"- {ex.name}: {ex.sets} sets x {prescription}; rest {ex.rest_seconds} seconds",
                      f"  Instructions: {ex.instructions}", f"  Equipment: {equipment}"]
        lines += ["", f"Cooldown: {day.cooldown}", ""]
    lines += ["Progression", plan.progression_guidance, "", "Recovery",
              plan.recovery_guidance, "", "Caution", caution_text(limitations), ""]
    return "\n".join(lines)
