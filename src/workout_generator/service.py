"""Groq provider, independently budgeted transport and corrective retries."""
from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from .models import FitnessProfile, GenerationResult, WorkoutPlan
from .prompts import PROMPT_VERSION, build_messages
from .schema import strict_schema
from .validation import evaluate

MODEL = 'openai/gpt-oss-120b'
LOG = logging.getLogger(__name__)
DEFAULT_MAX_COMPLETION_TOKENS = 8192

class IncompleteGenerationError(ValueError):
    """Raised when the provider response is absent or terminates abnormally."""
    def __init__(self, finish_reason: str | None):
        """Record the provider finish reason for later failure classification."""
        self.finish_reason = finish_reason
        super().__init__(f'Model did not finish normally (finish_reason={finish_reason!r})')


class RetryPolicy(BaseModel):
    """Configurable limits for generation, transport recovery, tokens and elapsed time."""
    max_generation_attempts: int = Field(default=2, ge=1, le=5)
    max_completion_tokens: int = Field(default=8192, ge=256, le=32768)
    max_completion_tokens_ceiling: int = Field(default=16384, ge=256, le=32768)
    max_rate_limit_retries: int = Field(default=3, ge=0, le=10)
    max_transient_retries: int = Field(default=2, ge=0, le=10)
    max_total_api_requests: int = Field(default=8, ge=1, le=50)
    max_elapsed_seconds: float = Field(default=120, gt=0)
    initial_backoff_seconds: float = Field(default=1, ge=0)
    max_backoff_seconds: float = Field(default=30, ge=0)

class GenerationError(RuntimeError):
    """Application-level failure preserving attempt counts and retry history."""
    def __init__(self, message: str, attempts: int = 0, *, api_requests: int = 0,
                 transport_retries: int = 0, retry_history: list[dict] | None = None):
        """Preserve counters and retry events when generation ultimately fails."""
        super().__init__(message)
        self.attempts = attempts
        self.api_requests = api_requests
        self.transport_retries = transport_retries
        self.retry_history = retry_history or []

class Provider(Protocol):
    """Interface used to inject real or fake model providers in tests."""
    def generate(self, messages: list[dict[str, str]], schema: dict[str, Any], *, max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS) -> tuple[str, dict[str, int] | None]: ...

class GroqProvider:
    """Groq SDK adapter; SDK-level automatic retries are deliberately disabled."""
    def __init__(self):
        """Load local configuration and create a client with SDK retries disabled."""
        from dotenv import load_dotenv
        from groq import Groq
        load_dotenv()
        if not os.getenv('GROQ_API_KEY'):
            raise GenerationError('GROQ_API_KEY missing from environment/.env')
        self.client = Groq(api_key=os.environ['GROQ_API_KEY'], max_retries=0, timeout=45)

    def generate(self, messages, schema, *, max_completion_tokens=DEFAULT_MAX_COMPLETION_TOKENS):
        """Submit a strict-schema request and return content with optional token usage."""
        response = self.client.chat.completions.create(
            model=MODEL, messages=messages, temperature=0.2,
            max_completion_tokens=max_completion_tokens,
            response_format={'type': 'json_schema', 'json_schema': {
                'name': 'workout_plan', 'strict': True, 'schema': schema}})
        if not response.choices:
            raise IncompleteGenerationError(None)
        if response.choices[0].finish_reason != 'stop':
            raise IncompleteGenerationError(response.choices[0].finish_reason)
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise ValueError('Empty model response')
        usage = response.usage
        return content, ({'prompt_tokens': usage.prompt_tokens,
                          'completion_tokens': usage.completion_tokens} if usage else None)

def classify_error(exc: Exception) -> str:
    """Unknown HTTP 400 is permanent by default; never guess it is transient."""
    status = getattr(exc, 'status_code', None)
    if _is_token_exhaustion(exc):
        return 'token_exhaustion'
    if _is_json_generation_failure(exc):
        return 'json_generation_failure'
    if isinstance(exc, IncompleteGenerationError) and exc.finish_reason in ('length', 'max_tokens'):
        return 'token_exhaustion'
    if status == 429:
        return 'rate_limit'
    if status in (500, 502, 503, 504):
        return 'transient'
    if status is not None:
        return 'permanent'
    try:
        from groq import APIConnectionError, APITimeoutError
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return 'transient'
    except ImportError:
        pass
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return 'transient'
    return 'permanent'

def _is_token_exhaustion(exc: Exception) -> bool:
    """Identify Groq's truncated strict-JSON error without treating all HTTP 400s alike."""
    if getattr(exc, 'status_code', None) != 400:
        return False
    body = getattr(exc, 'body', None)
    error = body.get('error', body) if isinstance(body, dict) else {}
    if not isinstance(error, dict) or error.get('code') != 'json_validate_failed':
        return False
    message = str(error.get('message', '')).lower()
    return 'max completion tokens reached' in message or 'max_completion_tokens' in message and 'truncat' in message


def _is_json_generation_failure(exc: Exception) -> bool:
    """Retry Groq output-generation errors, never invalid request/schema errors."""
    if getattr(exc, 'status_code', None) != 400:
        return False
    body = getattr(exc, 'body', None)
    error = body.get('error', body) if isinstance(body, dict) else {}
    return isinstance(error, dict) and error.get('code') == 'json_validate_failed'


def _error_detail(exc: Exception) -> str:
    """Keep concise error metadata; exclude potentially sensitive failed_generation payload."""
    status = getattr(exc, 'status_code', None)
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        error = body.get('error', body)
        if isinstance(error, dict):
            code = error.get('code')
            message = str(error.get('message', ''))[:800]
            return f'{type(exc).__name__} (HTTP {status}, code={code}): {message}'
    return f'{type(exc).__name__} (HTTP {status}): {str(exc)[:800]}' if status else f'{type(exc).__name__}: {str(exc)[:800]}'

def _delay(exc: Exception, retry_number: int, policy: RetryPolicy) -> float:
    """Calculate bounded retry backoff, preferring a provider Retry-After header."""
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    retry_after = headers.get('retry-after')
    if retry_after is not None:
        try:
            return max(0, float(retry_after))
        except (ValueError, TypeError):
            pass
    return min(policy.max_backoff_seconds,
               policy.initial_backoff_seconds * (2 ** (retry_number - 1))) * random.uniform(0.8, 1.2)

def generate_plan(profile: FitnessProfile, provider: Provider, *, forbidden: list[str] | None = None,
                  sleep: Callable[[float], None] = time.sleep,
                  policy: RetryPolicy | None = None,
                  previous_plan: WorkoutPlan | None = None) -> GenerationResult:
    """Orchestrate strict generation, semantic checks and independently budgeted retries."""
    policy = policy or RetryPolicy()
    if policy.max_completion_tokens > policy.max_completion_tokens_ceiling:
        raise ValueError('max_completion_tokens must not exceed max_completion_tokens_ceiling')
    schema = strict_schema()
    start = time.monotonic()
    history: list[dict[str, str | int | float]] = []
    api_requests = 0
    transport_retries = 0
    feedback: str | None = None
    completion_budget = policy.max_completion_tokens

    def fail(exc: Exception, generation: int) -> None:
        """Raise a GenerationError containing the counters and history collected so far."""
        LOG.error('Generation terminated: %s', _error_detail(exc), exc_info=(type(exc), exc, exc.__traceback__))
        raise GenerationError(f'Generation failed: {_error_detail(exc)}', generation,
                              api_requests=api_requests, transport_retries=transport_retries,
                              retry_history=history) from exc

    # A generation attempt is distinct from transport retries within that attempt.
    for generation in range(1, policy.max_generation_attempts + 1):
        messages = build_messages(profile, feedback,
                                  previous_plan.model_dump_json() if previous_plan else None)
        rate_retries = 0
        transient_retries = 0
        while True:
            if api_requests >= policy.max_total_api_requests or time.monotonic()-start >= policy.max_elapsed_seconds:
                fail(RuntimeError('API request or elapsed-time budget exhausted'), generation)
            api_requests += 1
            try:
                content, usage = provider.generate(messages, schema, max_completion_tokens=completion_budget)
            except Exception as exc:  # noqa: BLE001 - classify SDK and transport failures centrally
                category = classify_error(exc)
                history.append({'generation': generation, 'request': api_requests,
                                'event': category, 'detail': _error_detail(exc)[:1000]})
                LOG.warning('API request %d: %s', api_requests, _error_detail(exc))
                # A failed constrained-decoding attempt can be retried; invalid schema cannot.
                if category == 'json_generation_failure':
                    if generation >= policy.max_generation_attempts:
                        fail(exc, generation)
                    # Repeat the same request once; a new prompt or schema is not needed.
                    break
                if category == 'token_exhaustion':
                    if generation >= policy.max_generation_attempts:
                        fail(exc, generation)
                    next_budget = min(policy.max_completion_tokens_ceiling, completion_budget * 2)
                    if next_budget <= completion_budget:
                        fail(exc, generation)
                    history.append({'generation': generation, 'request': api_requests,
                                    'event': 'completion_budget_increased',
                                    'previous_limit': completion_budget, 'new_limit': next_budget})
                    completion_budget = next_budget
                    feedback = 'Keep exercise instructions concise and complete every required JSON field.'
                    break
                # Rate limits and transient outages do not consume corrective-generation budget.
                number = 0
                if category == 'rate_limit' and rate_retries < policy.max_rate_limit_retries:
                    rate_retries += 1
                    number = rate_retries
                elif category == 'transient' and transient_retries < policy.max_transient_retries:
                    transient_retries += 1
                    number = transient_retries
                else:
                    fail(exc, generation)
                delay = _delay(exc, number, policy)
                if (api_requests >= policy.max_total_api_requests or
                        time.monotonic()-start+delay >= policy.max_elapsed_seconds):
                    fail(RuntimeError('Retry would exceed request/time budget'), generation)
                transport_retries += 1
                history.append({'generation': generation, 'request': api_requests,
                                'event': 'transport_retry', 'delay_seconds': round(delay, 3)})
                sleep(delay)
                continue
            try:
                plan = WorkoutPlan.model_validate_json(content)
                assessment = evaluate(plan, profile, forbidden)
                if not assessment.valid:
                    raise ValueError('; '.join(f'{f.code}: {f.message}' for f in assessment.findings
                                               if f.severity == 'error'))
                return GenerationResult(plan=plan, evaluation=assessment, attempts=generation,
                                        api_requests=api_requests, transport_retries=transport_retries,
                                        recovered=(generation > 1 or transport_retries > 0),
                                        retry_history=history, model=MODEL, prompt_version=PROMPT_VERSION,
                                        elapsed_seconds=round(time.monotonic()-start, 3), usage=usage)
            except (ValueError, ValidationError) as exc:
                history.append({'generation': generation, 'request': api_requests,
                                'event': 'validation_failure', 'detail': str(exc)[:1000]})
                LOG.warning('Generated plan failed validation: %s', exc)
                if generation == policy.max_generation_attempts:
                    fail(exc, generation)
                feedback = str(exc)[:1500]
                break
    raise AssertionError('unreachable')
