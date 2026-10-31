"""Regression tests for Phase 1.1 changes; no live API calls."""
import json

import pytest

from workout_generator.cli import load_profile
from workout_generator.models import FitnessProfile, WorkoutPlan
from workout_generator.schema import strict_schema
from workout_generator.service import (
    GenerationError,
    RetryPolicy,
    classify_error,
    generate_plan,
)
from workout_generator.validation import evaluate

PROFILE = {'goal': 'general_fitness', 'experience': 'beginner', 'days_per_week': 1, 'equipment': 'no_equipment', 'limitations': None}

def plan(name='Bear crawl', equipment=None):
    return {'title': 'Plan', 'overview': 'Routine', 'goal': 'general_fitness', 'experience': 'beginner', 'days_per_week': 1, 'workout_days': [{'day_number': 1, 'day_of_week': 'Monday', 'focus': 'Full body', 'warmup': 'March', 'cooldown': 'Stretch', 'exercises': [{'name': name, 'sets': 2, 'repetitions': '8', 'duration_seconds': None, 'rest_seconds': 30, 'instructions': 'Move with control', 'equipment_required': equipment or []}]}], 'progression_guidance': 'Progress slowly', 'recovery_guidance': 'Rest', 'disclaimer': None}

class Fake:

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages = []

    def generate(self, messages, schema, *, max_completion_tokens=8192):
        self.messages.append(messages)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return (json.dumps(item) if isinstance(item, dict) else item, None)

class StatusFailure(Exception):

    def __init__(self, status_code, message='provider error', headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = {'error': {'message': message}}
        self.response = type('Response', (), {'headers': headers or {}})()

def test_load_both_profile_formats(tmp_path):
    direct = tmp_path / 'direct.json'
    direct.write_text(json.dumps(PROFILE))
    scenario = tmp_path / 'scenario.json'
    scenario.write_text(json.dumps({'id': 'test', 'profile': PROFILE}))
    assert load_profile(direct) == load_profile(scenario)

def test_invalid_scenario_rejected(tmp_path):
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps({'id': 'test', 'profile': {**PROFILE, 'days_per_week': 0}}))
    with pytest.raises(ValueError):
        load_profile(path)

def test_unknown_bodyweight_exercise_is_accepted():
    result = evaluate(WorkoutPlan.model_validate(plan('Reverse snow angel')), FitnessProfile.model_validate(PROFILE))
    assert result.valid
    assert not any(f.code == 'unrecognized_exercise' for f in result.findings)

def test_equipment_declaration_is_enforced():
    result = evaluate(WorkoutPlan.model_validate(plan('Creative movement', ['barbell'])), FitnessProfile.model_validate(PROFILE))
    assert not result.valid
    assert any(f.code == 'equipment' for f in result.findings)

def test_gym_only_name_still_rejected():
    result = evaluate(WorkoutPlan.model_validate(plan('Cable row')), FitnessProfile.model_validate(PROFILE))
    assert not result.valid

def test_schema_includes_required_equipment_list():
    schema = strict_schema()
    exercise = schema['$defs']['Exercise']
    assert 'equipment_required' in exercise['required']
    assert exercise['properties']['equipment_required']['type'] == 'array'

def test_rate_limit_does_not_consume_generation_budget():
    fake = Fake([StatusFailure(429, headers={'retry-after': '0'}), StatusFailure(429, headers={'retry-after': '0'}), plan()])
    result = generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _: None)
    assert result.attempts == 1
    assert result.api_requests == 3
    assert result.transport_retries == 2
    assert result.recovered
    assert len(fake.messages) == 3
    assert fake.messages[0] == fake.messages[1] == fake.messages[2]

def test_semantic_retry_receives_feedback():
    wrong = plan()
    wrong['days_per_week'] = 2
    fake = Fake([wrong, plan()])
    result = generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _: None)
    assert result.attempts == 2
    assert result.api_requests == 2
    assert 'Previous attempt failed validation' in fake.messages[1][1]['content']

def test_http_400_not_retried_and_details_available():
    fake = Fake([StatusFailure(400, 'invalid JSON schema')])
    with pytest.raises(GenerationError) as error:
        generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _: None)
    assert error.value.api_requests == 1
    assert 'invalid JSON schema' in str(error.value)
    assert len(fake.messages) == 1

def test_retry_ceiling():
    fake = Fake([StatusFailure(429) for _ in range(10)])
    with pytest.raises(GenerationError) as error:
        generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _: None, policy=RetryPolicy(max_rate_limit_retries=8, max_total_api_requests=3))
    assert error.value.api_requests == 3
    assert len(fake.messages) == 3

def test_5xx_transport_retry():
    fake = Fake([StatusFailure(503), plan()])
    result = generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _: None)
    assert result.transport_retries == 1
    assert result.attempts == 1

def test_bad_request_classification():
    assert classify_error(StatusFailure(400)) == 'permanent'
    assert classify_error(StatusFailure(429)) == 'rate_limit'
    assert classify_error(StatusFailure(502)) == 'transient'
