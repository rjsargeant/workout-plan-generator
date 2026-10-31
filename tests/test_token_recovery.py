"""Regression tests for truncated strict JSON and finish-reason handling."""
import json
from typing import ClassVar

import pytest

from workout_generator.models import FitnessProfile
from workout_generator.service import (
    GenerationError,
    GroqProvider,
    IncompleteGenerationError,
    RetryPolicy,
    classify_error,
    generate_plan,
)

PROFILE = FitnessProfile(goal='general_fitness', experience='beginner', days_per_week=1, equipment='no_equipment', limitations=None)

def valid_plan():
    return {'title': 'Plan', 'overview': 'Routine', 'goal': 'general_fitness', 'experience': 'beginner', 'days_per_week': 1, 'workout_days': [{'day_number': 1, 'day_of_week': 'Monday', 'focus': 'Full body', 'warmup': 'March', 'cooldown': 'Stretch', 'exercises': [{'name': 'Bear crawl', 'sets': 2, 'repetitions': '8', 'duration_seconds': None, 'rest_seconds': 30, 'instructions': 'Move with control', 'equipment_required': []}]}], 'progression_guidance': 'Progress slowly', 'recovery_guidance': 'Rest', 'disclaimer': None}

class Truncated(Exception):
    status_code = 400
    body: ClassVar[dict] = {'error': {'code': 'json_validate_failed', 'message': 'max completion tokens reached before generating a valid document', 'failed_generation': 'PRIVATE CONTENT'}}

class Fake:

    def __init__(self, items):
        self.items = list(items)
        self.budgets = []
        self.messages = []

    def generate(self, messages, schema, *, max_completion_tokens=8192):
        self.budgets.append(max_completion_tokens)
        self.messages.append(messages)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return (json.dumps(item), None)

def test_truncation_retries_with_increased_budget():
    provider = Fake([Truncated(), valid_plan()])
    result = generate_plan(PROFILE, provider, policy=RetryPolicy(max_completion_tokens=4096, max_completion_tokens_ceiling=8192))
    assert provider.budgets == [4096, 8192]
    assert result.attempts == 2
    assert result.api_requests == 2
    assert result.recovered
    assert any(h['event'] == 'completion_budget_increased' for h in result.retry_history)

def test_token_exhaustion_never_retries_at_ceiling():
    provider = Fake([Truncated()])
    with pytest.raises(GenerationError) as exc:
        generate_plan(PROFILE, provider, policy=RetryPolicy(max_completion_tokens=8192, max_completion_tokens_ceiling=8192))
    assert exc.value.api_requests == 1
    assert 'PRIVATE CONTENT' not in str(exc.value)

def test_other_json_validation_error_is_recoverable():
    error = Truncated()
    error.body = {'error': {'code': 'json_validate_failed', 'message': 'schema violation'}}
    assert classify_error(error) == 'json_generation_failure'

def test_length_finish_reason_classified_as_token_exhaustion():
    assert classify_error(IncompleteGenerationError('length')) == 'token_exhaustion'
    assert classify_error(IncompleteGenerationError('content_filter')) == 'permanent'

def test_non_stop_finish_reason_is_preserved():
    provider = GroqProvider.__new__(GroqProvider)
    choice = type('Choice', (), {'finish_reason': 'length', 'message': type('Msg', (), {'content': ''})()})()
    response = type('Response', (), {'choices': [choice]})()
    provider.client = type('Client', (), {'chat': type('Chat', (), {'completions': type('Comp', (), {'create': lambda self, **kwargs: response})()})()})()
    with pytest.raises(IncompleteGenerationError) as exc:
        provider.generate([], {}, max_completion_tokens=512)
    assert exc.value.finish_reason == 'length'

def test_invalid_budget_configuration_rejected():
    with pytest.raises(ValueError, match='max_completion_tokens'):
        generate_plan(PROFILE, Fake([]), policy=RetryPolicy(max_completion_tokens=8192, max_completion_tokens_ceiling=4096))
