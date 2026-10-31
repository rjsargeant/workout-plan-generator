"""Regression tests for targeted replacement and atomic session-state updates."""
import json

import pytest

from workout_generator.models import (
    Equipment,
    Evaluation,
    Exercise,
    Experience,
    FitnessProfile,
    GenerationResult,
    Goal,
    WorkoutDay,
    WorkoutPlan,
)
from workout_generator.service import GenerationError
from workout_generator.streamlit_app import swap_selected_exercise
from workout_generator.swapping import replace_exercise, swap_schema


def sample():
    profile = FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                             days_per_week=1, equipment=Equipment.none, limitations=None)
    original = Exercise(name='Squat', sets=3, repetitions='10', duration_seconds=None,
                        rest_seconds=60, instructions='Squat carefully', equipment_required=[])
    plan = WorkoutPlan(title='Plan', overview='Overview', goal=profile.goal,
                       experience=profile.experience, days_per_week=1,
                       workout_days=[WorkoutDay(day_number=1, day_of_week='Monday', focus='Legs',
                                                warmup='Warm up', exercises=[original], cooldown='Stretch')],
                       progression_guidance='Progress', recovery_guidance='Recover', disclaimer=None)
    return profile, plan


class FakeProvider:
    def __init__(self, replacement):
        self.replacement = replacement
    def generate(self, messages, schema, *, max_completion_tokens=2048):
        return json.dumps({'exercise': self.replacement}), None


def test_swap_schema_strict():
    schema = swap_schema()
    assert schema['additionalProperties'] is False
    assert schema['required'] == ['exercise']


def test_swap_only_selected_exercise():
    profile, plan = sample()
    replacement = plan.workout_days[0].exercises[0].model_dump()
    replacement['name'] = 'Reverse Lunge'
    updated = replace_exercise(plan, profile, 0, 0, client=FakeProvider(replacement))
    assert updated.workout_days[0].exercises[0].name == 'Reverse Lunge'
    assert plan.workout_days[0].exercises[0].name == 'Squat'


def test_swap_rejects_equipment_conflict_without_mutating_plan():
    profile, plan = sample()
    replacement = plan.workout_days[0].exercises[0].model_dump()
    replacement.update(name='Barbell Squat', equipment_required=['barbell'])
    with pytest.raises(GenerationError):
        replace_exercise(plan, profile, 0, 0, client=FakeProvider(replacement))
    assert plan.workout_days[0].exercises[0].name == 'Squat'


def test_swap_state_is_atomic():
    profile, plan = sample()
    result = GenerationResult(plan=plan, evaluation=Evaluation(findings=[]), attempts=1,
                              model='mock', prompt_version='test', elapsed_seconds=0)
    state = {'last_result': result, 'last_profile': profile, 'previous_result': result}
    def fake_swap(p, prof, di, ei):
        updated = p.model_copy(deep=True)
        updated.workout_days[0].exercises[0].name = 'Lunge'
        return updated
    swap_selected_exercise(state, 0, 0, swapper=fake_swap)
    assert state['last_result'].plan.workout_days[0].exercises[0].name == 'Lunge'
    assert state['previous_result'].plan.workout_days[0].exercises[0].name == 'Squat'
