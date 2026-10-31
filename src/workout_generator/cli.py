"""Interactive, noninteractive and batch CLI."""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .disclaimers import MEDICAL_DISCLAIMER, caution_text
from .models import (
    BatchReport,
    Equipment,
    Experience,
    FitnessProfile,
    Goal,
    Scenario,
    ScenarioResult,
    WorkoutPlan,
)
from .prompts import PROMPT_VERSION
from .schema import strict_schema
from .service import MODEL, GenerationError, GroqProvider, generate_plan
from .validation import evaluate

LOG = logging.getLogger(__name__)

def load(path: Path):
    """Read and decode a UTF-8 JSON file."""
    return json.loads(path.read_text(encoding='utf-8'))

def load_profile(path: Path) -> FitnessProfile:
    """Accept either a direct profile or a scenario-wrapped profile."""
    data = load(path)
    if not isinstance(data, dict):
        raise TypeError('Profile input must be a JSON object')
    if 'profile' in data or 'id' in data:
        return Scenario.model_validate(data).profile
    return FitnessProfile.model_validate(data)

def choose(name, enum):
    """Prompt for one enumerated value in interactive CLI mode."""
    values = list(enum)
    print(name + ':')
    for i, item in enumerate(values, 1):
        print(f'{i}. {item.value}')
    return values[int(input('Choice: ')) - 1]

def interactive():
    """Collect and validate the required fitness-profile fields interactively."""
    return FitnessProfile(goal=choose('Goal', Goal), experience=choose('Experience', Experience),
                          days_per_week=int(input('Days per week (1-7): ')), equipment=choose('Equipment', Equipment),
                          limitations=input('Limitations (optional): ').strip() or None)

def render(plan, limitations=None):
    """Produce the single Markdown report used by both CLI and Streamlit."""
    from .reporting import render_markdown
    return render_markdown(plan, limitations=limitations)

def batch_run(folder, output, provider=None):
    """Run every scenario independently and write a combined JSON report."""
    paths = sorted(folder.glob('*.json'))
    if not paths:
        raise ValueError('No JSON scenario files found')
    provider = provider or GroqProvider()
    records = []
    for path in paths:
        start = time.monotonic()
        try:
            scenario = Scenario.model_validate(load(path))
            result = generate_plan(scenario.profile, provider, forbidden=scenario.expected_exercises_absent)
            record = ScenarioResult(id=scenario.id, status='passed', attempts=result.attempts,
                                    duration_seconds=result.elapsed_seconds, api_requests=result.api_requests,
                                    transport_retries=result.transport_retries, recovered=result.recovered,
                                    retry_history=result.retry_history, findings=result.evaluation.findings,
                                    error=None, plan=result.plan)
        except (ValueError, OSError, ValidationError, GenerationError) as exc:
            LOG.exception('Scenario %s failed', path.name)
            record = ScenarioResult(id=path.stem, status='failed', attempts=getattr(exc, 'attempts', 0),
                                    duration_seconds=round(time.monotonic()-start, 3),
                                    api_requests=getattr(exc, 'api_requests', 0),
                                    transport_retries=getattr(exc, 'transport_retries', 0),
                                    retry_history=getattr(exc, 'retry_history', []), findings=[],
                                    error=f'{type(exc).__name__}: {exc}', plan=None)
        records.append(record)
        print(f'{record.id}: {record.status}')
    report = BatchReport(model=MODEL, prompt_version=PROMPT_VERSION, results=records,
                         medical_disclaimer=MEDICAL_DISCLAIMER)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding='utf-8')
    print(f'Passed {report.passed}/{len(records)}. Report: {output}')
    return 0 if report.passed == len(records) else 1

def main(argv=None):
    """Parse CLI arguments, dispatch commands and return a process exit code."""
    parser = argparse.ArgumentParser(prog='workout-generator')
    parser.add_argument('--diagnostic', action='store_true')
    commands = parser.add_subparsers(dest='command', required=True)
    gen = commands.add_parser('generate')
    gen.add_argument('--input', type=Path)
    gen.add_argument('--output', type=Path)
    gen.add_argument('--json', action='store_true')
    batch = commands.add_parser('batch')
    batch.add_argument('--scenarios', type=Path, default=Path('scenarios'))
    batch.add_argument('--output', type=Path, default=Path('reports/batch.json'))
    val = commands.add_parser('validate')
    val.add_argument('--input', required=True, type=Path)
    val.add_argument('--profile', required=True, type=Path)
    commands.add_parser('schema-check')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.diagnostic else logging.CRITICAL)
    try:
        if args.command == 'schema-check':
            print(f'Strict schema valid: {len(strict_schema().get("$defs", {}))} definitions')
            return 0
        if args.command == 'validate':
            data = load(args.input)
            plan = WorkoutPlan.model_validate(data.get('plan', data))
            result = evaluate(plan, load_profile(args.profile))
            print(result.model_dump_json(indent=2))
            return 0 if result.valid else 1
        if args.command == 'batch':
            return batch_run(args.scenarios, args.output)
        profile = load_profile(args.input) if args.input else interactive()
        result = generate_plan(profile, GroqProvider())
        if args.json:
            payload = result.model_dump(mode='json')
            payload['medical_disclaimer'] = caution_text(profile.limitations)
            text = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            text = render(result.plan, limitations=profile.limitations)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + '\n', encoding='utf-8')
        else:
            print(text)
        if result.evaluation.findings:
            print('Review notes: ' + '; '.join(f.message for f in result.evaluation.findings), file=sys.stderr)
        return 0
    except (ValueError, OSError, ValidationError, GenerationError, EOFError, KeyboardInterrupt, IndexError) as exc:
        if args.diagnostic:
            LOG.exception('Command failed')
        print(f'Unable to complete request: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
