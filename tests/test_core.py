"""Regression tests for core; assertions guard existing application behaviour."""

import json

import pytest
from pydantic import ValidationError

from workout_generator.cli import batch_run, main
from workout_generator.models import FitnessProfile, WorkoutPlan
from workout_generator.prompts import build_messages
from workout_generator.schema import strict_schema
from workout_generator.service import GenerationError, generate_plan
from workout_generator.validation import evaluate

PROFILE = {'goal':'general_fitness','experience':'beginner','days_per_week':1,'equipment':'no_equipment','limitations':None}
PLAN = {'title':'Basic plan','overview':'Simple routine','goal':'general_fitness','experience':'beginner',
        'days_per_week':1,'workout_days':[{'day_number':1,'day_of_week':'Monday','focus':'Full body',
        'warmup':'Walk in place','cooldown':'Gentle stretching','exercises':[
            {'name':'Bodyweight squat','sets':2,'repetitions':'8','duration_seconds':None,
             'rest_seconds':60,'instructions':'Move slowly and comfortably','equipment_required':[]}]}],
        'progression_guidance':'Add repetitions gradually','recovery_guidance':'Rest and sleep','disclaimer':None}

class Fake:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
    def generate(self, messages, schema, *, max_completion_tokens=8192):
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return json.dumps(output) if isinstance(output, dict) else output, None

def test_input_validation():
    for days in (0, 8):
        with pytest.raises(ValidationError):
            FitnessProfile.model_validate({**PROFILE,'days_per_week':days})
    with pytest.raises(ValidationError):
        FitnessProfile.model_validate({**PROFILE,'surprise':1})

def test_schema_refs_and_strict():
    schema = strict_schema()
    assert '$defs' in schema
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == set(schema['properties'])
    for obj in schema['$defs'].values():
        if obj.get('type') == 'object':
            assert obj['additionalProperties'] is False
            assert set(obj['required']) == set(obj['properties'])

def test_prompts():
    messages = build_messages(FitnessProfile.model_validate(PROFILE))
    assert [m['role'] for m in messages] == ['system','user']
    assert 'no_equipment' in messages[1]['content']

def test_success():
    fake = Fake([PLAN])
    result = generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _:None)
    assert result.attempts == fake.calls == 1
    assert result.evaluation.valid

def test_semantic_retry():
    wrong = {**PLAN,'days_per_week':3}
    fake = Fake([wrong, PLAN])
    result = generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _:None)
    assert result.attempts == fake.calls == 2

def test_two_attempt_cap():
    fake = Fake(['not json','not json'])
    with pytest.raises(GenerationError) as err:
        generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _:None)
    assert fake.calls == 2 and err.value.attempts == 2

def test_nonretryable_failure():
    fake = Fake([RuntimeError('fatal')])
    with pytest.raises(GenerationError):
        generate_plan(FitnessProfile.model_validate(PROFILE), fake, sleep=lambda _:None)
    assert fake.calls == 1

def test_equipment_and_limitations():
    profile = FitnessProfile.model_validate({**PROFILE,'limitations':'No squats'})
    findings = evaluate(WorkoutPlan.model_validate({**PLAN,'disclaimer':'Consult a professional'}), profile)
    assert not findings.valid
    assert any(f.code == 'limitation' for f in findings.findings)
    changed = json.loads(json.dumps(PLAN))
    changed['workout_days'][0]['exercises'][0]['name'] = 'Barbell squat'
    assert any(f.code == 'equipment' for f in evaluate(WorkoutPlan.model_validate(changed), FitnessProfile.model_validate(PROFILE)).findings)

def test_cli_schema_and_invalid_input(tmp_path):
    assert main(['schema-check']) == 0
    path = tmp_path/'invalid.json'
    path.write_text(json.dumps({**PROFILE,'days_per_week':0}))
    assert main(['generate','--input',str(path)]) == 2

def test_batch_with_fake(tmp_path):
    folder = tmp_path/'scenarios'
    folder.mkdir()
    (folder/'one.json').write_text(json.dumps({'id':'one','profile':PROFILE}))
    report = tmp_path/'report.json'
    assert batch_run(folder, report, Fake([PLAN])) == 0
    assert json.loads(report.read_text())['results'][0]['status'] == 'passed'
