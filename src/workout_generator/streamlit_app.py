"""Single-page Streamlit interface over the existing Phase 1 generation service.

Run with: uv run streamlit run src/workout_generator/streamlit_app.py
No Groq request occurs until the user presses Generate Plan.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from workout_generator.disclaimers import caution_text
from workout_generator.models import (
    Equipment,
    Experience,
    FitnessProfile,
    GenerationResult,
    Goal,
)
from workout_generator.reporting import render_markdown, render_plain_text
from workout_generator.service import GenerationError, GroqProvider, generate_plan
from workout_generator.swapping import replace_exercise

LOG = logging.getLogger(__name__)

GOAL_LABELS = {
    Goal.muscle: "Build muscle",
    Goal.fat: "Lose fat",
    Goal.general: "General fitness",
    Goal.endurance: "Improve endurance",
}
EXPERIENCE_LABELS = {
    Experience.beginner: "Beginner",
    Experience.intermediate: "Intermediate",
    Experience.advanced: "Advanced",
}
EQUIPMENT_LABELS = {
    Equipment.none: "No equipment",
    Equipment.dumbbells: "Home dumbbells",
    Equipment.gym: "Full gym",
}


def create_profile(goal: Goal, experience: Experience, days: int,
                   equipment: Equipment, limitations: str) -> FitnessProfile:
    """Validate UI values with exactly the same model used by the CLI."""
    return FitnessProfile(goal=goal, experience=experience, days_per_week=days,
                          equipment=equipment, limitations=limitations)


def create_plan(profile: FitnessProfile, previous_plan=None) -> GenerationResult:
    """Invoke the existing service; kept separate to simplify testing/mocking."""
    if previous_plan is None:
        return generate_plan(profile, GroqProvider())
    return generate_plan(profile, GroqProvider(), previous_plan=previous_plan)


def render_plan(st: Any, result: GenerationResult, limitations: str | None = None) -> None:
    """Display and download the exact same Markdown report."""
    report = render_markdown(result.plan, limitations=limitations)
    st.markdown(report)
    st.download_button("Download plan (.txt)",
                       data=render_plain_text(result.plan, limitations=limitations),
                       file_name="workout-plan.txt", mime="text/plain")
    st.download_button("Download plan (.md)", data=report,
                       file_name="workout-plan.md", mime="text/markdown")

def variation_context(action: str, saved_result: GenerationResult | None):
    """Only an explicit Regenerate action supplies the current plan as context.

    The current form values always determine the new profile, even when they
    differ from the values used for the saved plan.
    """
    if action == "regenerate" and saved_result is not None:
        return saved_result.plan
    return None


def store_successful_plan(state: Any, profile: FitnessProfile,
                          result: GenerationResult) -> None:
    """Atomically promote a successful result; retain only the immediately prior plan."""
    current = state.get("last_result")
    if current is not None:
        state["previous_result"] = current
        state["previous_profile_limitations"] = state.get("last_profile_limitations")
    else:
        state.pop("previous_result", None)
        state.pop("previous_profile_limitations", None)
    state["last_profile"] = profile
    state["last_result"] = result
    state["last_profile_limitations"] = profile.limitations


def swap_selected_exercise(state: Any, day_index: int, exercise_index: int,
                           swapper=replace_exercise) -> None:
    """Commit a replacement only after the complete updated plan is validated."""
    result = state["last_result"]
    profile = state["last_profile"]
    updated = swapper(result.plan, profile, day_index, exercise_index)
    state["last_result"] = result.model_copy(update={"plan": updated})


def render_current_plan(st: Any, result: GenerationResult, limitations: str | None = None) -> None:
    """Render current exercises with inline swap controls and current-state downloads.

    Native Streamlit columns are necessary because buttons cannot be embedded in
    a Markdown table. Both downloads are produced from the same updated plan.
    """
    # The current session plan is authoritative for both on-screen rows and exports.
    plan = result.plan
    st.markdown(f"## {plan.title}")
    st.markdown(plan.overview)
    st.markdown(
        f"**Goal:** {plan.goal.value.replace('_', ' ').title()}  \n"
        f"**Experience:** {plan.experience.value.title()}  \n"
        f"**Training days per week:** {plan.days_per_week}"
    )
    for day_index, day in enumerate(plan.workout_days):
        st.markdown(f"### Day {day.day_number} · {day.day_of_week} — {day.focus}")
        st.markdown(f"**Warm-up:** {day.warmup}")
        header = st.columns([2.5, 0.8, 1.5, 1.0, 5.0, 1.6, 0.9], gap="small")
        for col, label in zip(header, (
            "Exercise", "Sets", "Reps / Time", "Rest", "Instructions", "Equipment", "Swap"
        )):
            col.markdown(f"**{label}**")
        for exercise_index, exercise in enumerate(day.exercises):
            cols = st.columns([2.5, 0.8, 1.5, 1.0, 5.0, 1.6, 0.9], gap="small", vertical_alignment="center")
            cols[0].write(exercise.name)
            cols[1].write(str(exercise.sets))
            cols[2].write(exercise.repetitions or f"{exercise.duration_seconds} sec")
            cols[3].write(f"{exercise.rest_seconds} sec")
            cols[4].write(exercise.instructions)
            cols[5].write(", ".join(exercise.equipment_required) or "None")
            if cols[6].button(
                "Swap", icon=":material/sync:", key=f"swap_{day_index}_{exercise_index}",
                help=f"Swap {exercise.name}", type="secondary",
            ):
                try:
                    with st.spinner(f"Finding an alternative to {exercise.name}…"):
                        swap_selected_exercise(st.session_state, day_index, exercise_index)
                    st.session_state["swap_notice"] = f"Replaced {exercise.name}."
                    st.rerun()
                except (GenerationError, ValueError) as exc:
                    LOG.exception("Exercise swap failed")
                    st.error(f"Unable to replace the exercise: {exc}")
                except Exception:
                    LOG.exception("Unexpected exercise swap error")
                    st.error("Unable to replace the exercise. The current plan has been preserved.")
        st.markdown(f"**Cooldown:** {day.cooldown}")
    st.markdown("### Progression")
    st.markdown(plan.progression_guidance)
    st.markdown("### Recovery")
    st.markdown(plan.recovery_guidance)
    st.markdown("---")
    st.markdown("**Caution**")
    st.markdown(caution_text(limitations))

    # On the next rerun, successful swaps are already stored in last_result.
    # Both downloads therefore reflect the updated current plan, not a cached report.
    st.download_button("Download plan (.txt)",
                       data=render_plain_text(plan, limitations=limitations),
                       file_name="workout-plan.txt", mime="text/plain")
    st.download_button("Download plan (.md)",
                       data=render_markdown(plan, limitations=limitations),
                       file_name="workout-plan.md", mime="text/markdown")


# Keep Streamlit in wide mode for the interactive exercise table, but cap the
# actual reading width so the form and report do not stretch across a large monitor.
# The cap is responsive: smaller screens still use their available width.
REPORT_MAX_WIDTH_PX = 1200


def report_layout_css() -> str:
    """Return the responsive, centered content-width rule for Streamlit."""
    return f"""<style>
    .stMainBlockContainer, .block-container {{
        max-width: {REPORT_MAX_WIDTH_PX}px;
        width: 100%;
        margin-left: auto;
        margin-right: auto;
        padding-top: 2rem;
        padding-left: clamp(1rem, 2vw, 2rem);
        padding-right: clamp(1rem, 2vw, 2rem);
    }}
    </style>"""


def main() -> None:
    """Render explicit new/variation actions and retain two successful plans."""
    import streamlit as st

    st.set_page_config(page_title="Workout Plan Generator", page_icon="🏋️", layout="wide")
    st.markdown(report_layout_css(), unsafe_allow_html=True)
    st.title("Workout Plan Generator")
    st.markdown("### Your Fitness Goals. Your Workout Plan.")
    st.markdown(
        "Create a personalized weekly workout plan tailored to your fitness goals, "
        "experience, available equipment, and training schedule. Whether you're "
        "building strength, improving endurance, losing fat, or simply staying "
        "active, the AI-powered generator will design a structured exercise "
        "program around your needs."
    )
    st.markdown(
        "Generate a new plan whenever you wish, or swap individual exercises "
        "to explore suitable alternatives."
    )
    if st.session_state.pop("plan_ready_notice", False):
        st.success("Your workout plan is ready.")

    with st.form("fitness_profile"):
        goal = st.selectbox("Fitness goal", list(Goal),
                            format_func=lambda item: GOAL_LABELS[item])
        experience = st.selectbox("Experience level", list(Experience),
                                  format_func=lambda item: EXPERIENCE_LABELS[item])
        days = st.slider("Days available per week", min_value=1, max_value=7, value=3)
        equipment = st.selectbox("Equipment access", list(Equipment),
                                 format_func=lambda item: EQUIPMENT_LABELS[item])
        limitations = st.text_area("Injuries or limitations (optional)", max_chars=500,
                                   placeholder="e.g. 'bad knees', 'no overhead pressing'")
        new_submitted = st.form_submit_button("Generate/Regenerate", type="primary")

    if new_submitted:
        try:
            profile = create_profile(goal, experience, days, equipment, limitations)
            context = None  # Every click generates a fresh plan using the displayed inputs.
            with st.spinner("Generating your workout plan…"):
                result = create_plan(profile, previous_plan=context)
            # Commit state only after the new plan has passed all validation.
            store_successful_plan(st.session_state, profile, result)
            st.session_state["plan_ready_notice"] = True
            # Re-evaluate form widget disabled states using the newly saved plan.
            st.rerun()
        except ValidationError as exc:
            st.error("Please correct the supplied information: " + "; ".join(
                str(item["msg"]) for item in exc.errors()))
        except GenerationError as exc:
            LOG.exception("Workout generation failed")
            st.error(f"Unable to generate a workout plan: {exc}")
        except Exception:
            LOG.exception("Unexpected Streamlit generation error")
            st.error("An unexpected error occurred. Your existing plans have been preserved.")

    if "last_result" in st.session_state:
        st.markdown("### Current Workout Plan")
        if st.session_state.pop("swap_notice", None):
            st.success("Exercise replaced successfully.")
        render_current_plan(st, st.session_state["last_result"],
                            limitations=st.session_state.get("last_profile_limitations"))
        if "previous_result" in st.session_state:
            with st.expander("Previous Workout Plan", expanded=False):
                # The previous version is comparison-only; downloads target the current plan.
                st.markdown(render_markdown(
                    st.session_state["previous_result"].plan,
                    limitations=st.session_state.get("previous_profile_limitations")))
    else:
        st.divider()
        st.markdown("**Caution**\n\n" + caution_text())


if __name__ == "__main__":
    main()
