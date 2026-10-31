"""Regression tests for the agreed Phase 2 presentation refinements."""
from unittest.mock import Mock

from workout_generator.disclaimers import MEDICAL_DISCLAIMER
from workout_generator.models import (
    Equipment,
    Experience,
    FitnessProfile,
    Goal,
    WorkoutPlan,
)
from workout_generator.reporting import additional_caution, render_markdown
from workout_generator.streamlit_app import render_plan
from workout_generator.validation import evaluate


def sample_plan():
    return WorkoutPlan.model_validate({
        "title": "Example Plan", "overview": "Example overview",
        "goal": "general_fitness", "experience": "beginner", "days_per_week": 1,
        "workout_days": [{"day_number": 1, "day_of_week": "Monday", "focus": "Strength",
                          "warmup": "Warm up", "cooldown": "Cool down", "exercises": [
                              {"name": "Bird Dog", "sets": 2, "repetitions": "10", "duration_seconds": None,
                               "rest_seconds": 30, "instructions": "Keep steady", "equipment_required": []}]}],
        "progression_guidance": "Progress gently", "recovery_guidance": "Rest",
        "disclaimer": "Caution: Consult a clinician before exercise."})


def test_caution_normalization():
    assert additional_caution("Caution: Consult a clinician") == "Consult a clinician"
    assert additional_caution("Additional Caution: Caution: Take care") == "Take care"


def test_markdown_has_one_caution_and_smaller_headings():
    report = render_markdown(sample_plan())
    assert "Additional Caution" not in report
    assert "**Caution**" in report
    assert report.count("**Caution**") == 1
    assert "## Example Plan" in report
    assert "### Day 1" in report
    assert "### Progression" in report
    assert report.rstrip().endswith(MEDICAL_DISCLAIMER)
    assert report.index("| Exercise | Sets |") < report.index("### Progression")


def test_streamlit_screen_and_download_share_report():
    st = Mock()
    result = Mock(plan=sample_plan())
    render_plan(st, result)
    assert st.markdown.call_args.args[0] == st.download_button.call_args.kwargs["data"]


def test_ambiguous_limitation_does_not_generate_generic_warning():
    profile = FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                             days_per_week=1, equipment=Equipment.none, limitations="knee discomfort")
    findings = evaluate(sample_plan(), profile).findings
    assert not any(item.code == "unverified_limitation" for item in findings)
