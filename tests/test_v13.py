"""Targeted regressions for Groq generation errors and reporting."""
import json
from typing import ClassVar

from test_token_recovery import PROFILE, Fake, valid_plan

from workout_generator.cli import render
from workout_generator.disclaimers import MEDICAL_DISCLAIMER
from workout_generator.models import BatchReport, FitnessProfile, WorkoutPlan
from workout_generator.service import classify_error, generate_plan
from workout_generator.validation import evaluate


class JsonFailure(Exception):
    status_code = 400
    body: ClassVar[dict] = {'error': {'code': 'json_validate_failed', 'message': 'Failed to generate JSON.'}}

class SchemaFailure(Exception):
    status_code = 400
    body: ClassVar[dict] = {'error': {'code': 'invalid_request_error', 'message': 'invalid JSON schema'}}

def test_json_generation_failure_retries_same_request():
    fake = Fake([JsonFailure(), valid_plan()])
    result = generate_plan(PROFILE, fake)
    assert result.api_requests == 2 and result.attempts == 2 and result.recovered
    assert fake.messages[0] == fake.messages[1]
    assert fake.budgets == [8192, 8192]

def test_schema_failure_is_permanent():
    assert classify_error(SchemaFailure()) == 'permanent'

def test_nonrunning_sprints_are_allowed():
    p = FitnessProfile(goal='general_fitness', experience='beginner', days_per_week=1,
                       equipment='full_gym', limitations='No running')
    for name in ('Stationary Bike Sprint', 'Rowing Sprint', 'Bicycle Crunches', 'Incline Treadmill Walking'):
        data = valid_plan()
        data['workout_days'][0]['exercises'][0]['name'] = name
        data['disclaimer'] = 'Consult a professional.'
        result = evaluate(WorkoutPlan.model_validate(data), p, forbidden=['run', 'jog', 'sprint'])
        assert result.valid, (name, result.findings)

def test_running_still_rejected():
    p = FitnessProfile(goal='general_fitness', experience='beginner', days_per_week=1,
                       equipment='full_gym', limitations='No running')
    data = valid_plan()
    data['workout_days'][0]['exercises'][0]['name'] = 'Treadmill Running Intervals'
    data['disclaimer'] = 'Consult a professional.'
    result = evaluate(WorkoutPlan.model_validate(data), p, forbidden=['run'])
    assert not result.valid

def test_disclaimer_at_end_of_text_and_batch_json():
    text = render(WorkoutPlan.model_validate(valid_plan()))
    assert text.rstrip().endswith(MEDICAL_DISCLAIMER)
    report = BatchReport(model='test', prompt_version='test', results=[], medical_disclaimer=MEDICAL_DISCLAIMER)
    assert list(json.loads(report.model_dump_json()))[-1] == 'medical_disclaimer'
