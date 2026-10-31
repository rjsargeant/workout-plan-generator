"""Offline checks of the Phase 2 adapter; no Groq credentials required."""
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from workout_generator.models import Equipment, Experience, FitnessProfile, Goal
from workout_generator.streamlit_app import (
    EQUIPMENT_LABELS,
    GOAL_LABELS,
    create_plan,
    create_profile,
)


def test_ui_profile_matches_phase1_contract():
    result = create_profile(Goal.general, Experience.beginner, 3, Equipment.none, "  ")
    assert isinstance(result, FitnessProfile)
    assert result.limitations is None
    assert result.days_per_week == 3


@pytest.mark.parametrize("days", [0, 8])
def test_invalid_days_rejected(days):
    with pytest.raises(ValidationError):
        create_profile(Goal.general, Experience.beginner, days, Equipment.none, "")


def test_long_limitations_rejected():
    with pytest.raises(ValidationError):
        create_profile(Goal.general, Experience.beginner, 3, Equipment.none, "x" * 501)


def test_all_ui_enum_choices_covered():
    assert set(GOAL_LABELS) == set(Goal)
    assert set(EQUIPMENT_LABELS) == set(Equipment)


def test_create_plan_delegates_to_shared_service():
    profile = create_profile(Goal.general, Experience.beginner, 3, Equipment.none, "")
    fake_result = object()
    with patch("workout_generator.streamlit_app.GroqProvider") as provider, \
         patch("workout_generator.streamlit_app.generate_plan", return_value=fake_result) as generate:
        assert create_plan(profile) is fake_result
        generate.assert_called_once_with(profile, provider.return_value)


def test_successful_generation_triggers_form_state_refresh():
    """Regression: Streamlit must rerun after saving a plan to enable Regenerate."""
    import ast
    import inspect

    from workout_generator import streamlit_app

    tree = ast.parse(inspect.getsource(streamlit_app.main))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    save_calls = [node for node in calls if isinstance(node.func, ast.Name)
                  and node.func.id == "store_successful_plan"]
    rerun_calls = [node for node in calls if isinstance(node.func, ast.Attribute)
                   and node.func.attr == "rerun"]
    assert len(save_calls) == 1
    assert len(rerun_calls) == 1
    assert rerun_calls[0].lineno > save_calls[0].lineno
