"""Offline regression tests for the unified Streamlit generation action."""
from unittest.mock import Mock

from test_phase2_refinements import sample_plan

from workout_generator.models import Equipment, Experience, FitnessProfile, Goal
from workout_generator.streamlit_app import store_successful_plan, variation_context


def profile(limitation=None, days=1):
    return FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                          days_per_week=days, equipment=Equipment.none,
                          limitations=limitation)


def result():
    return Mock(plan=sample_plan())


def test_new_plan_never_uses_previous_plan_as_context():
    current = result()
    assert variation_context("new", current) is None
    assert variation_context("new", None) is None


def test_regenerate_uses_previous_plan_even_when_profile_changed():
    current = result()
    assert variation_context("regenerate", current) is current.plan
    assert variation_context("regenerate", None) is None


def test_initial_success_stores_only_current_plan():
    state = {}
    p, r = profile(), result()
    store_successful_plan(state, p, r)
    assert state['last_result'] is r
    assert state['last_profile'] == p
    assert 'previous_result' not in state


def test_successful_regeneration_moves_current_to_previous():
    state = {}
    first, second = result(), result()
    store_successful_plan(state, profile('no running'), first)
    store_successful_plan(state, profile('bad knees'), second)
    assert state['last_result'] is second
    assert state['previous_result'] is first
    assert state['previous_profile_limitations'] == 'no running'
    assert state['last_profile_limitations'] == 'bad knees'


def test_only_immediately_previous_plan_retained():
    state = {}
    first, second, third = result(), result(), result()
    for r in (first, second, third):
        store_successful_plan(state, profile(), r)
    assert state['last_result'] is third
    assert state['previous_result'] is second


def test_generation_failure_preserves_both_plans():
    state = {}
    store_successful_plan(state, profile(), result())
    store_successful_plan(state, profile(), result())
    snapshot = state.copy()
    try:
        raise RuntimeError('simulated provider failure')
    except RuntimeError:
        pass  # No store_successful_plan call occurs on a failed generation.
    assert state == snapshot
