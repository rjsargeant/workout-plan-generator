# Workout Plan Generator

A single-page **Streamlit** workout planner with a CLI and repeatable batch-evaluation mode. The application uses **Groq `openai/gpt-oss-120b`**, **Pydantic v2**, and **strict JSON Schema** to request a structured weekly workout plan. Developed for **Ubuntu 24.04 LTS**, **Python 3.12**, and **uv**.

> **Purpose:** An educational prompt-engineering assignment. Generated plans are not individualized medical advice. The application performs best-effort checks, not a professional fitness or clinical assessment.

## Features

- Structured inputs: fitness goal, experience, 1–7 days/week, equipment, and optional injuries/limitations.
- **Generate/Regenerate** produces a fresh plan from the currently displayed inputs. It does not compare profiles or require a separate regeneration prompt.
- Current plan shown with inline **Swap** controls for individual exercises; Groq selects an alternative with the same training intent.
- Previous successful full plan retained in a collapsed, read-only section. Exercise swaps do not replace the previous plan.
- Markdown and plain-text downloads reflect the **current plan after swaps**.
- Fixed **Caution** section; user-entered limitations are quoted without interpretation.
- Interactive CLI, JSON-profile generation, schema checking, existing-plan validation, and batch scenarios.
- Bounded retries and optional diagnostic logging.

## Quick start (Ubuntu 24.04 LTS)

Install `uv` using its official installation instructions if it is not already installed. From the extracted project root:

```bash
uv sync --group dev
cp .env.example .env
```

Set `GROQ_API_KEY` in `.env` (or your shell environment). Never commit or share the key. `.env` is ignored by Git.

```bash
uv run pytest -q
uv run workout-generator schema-check
uv run streamlit run src/workout_generator/streamlit_app.py
```

Open the local URL printed by Streamlit (typically `http://localhost:8501`). The main content area is centered and capped at 1,200 pixels.

**Note:** This source distribution does not contain a pre-generated `uv.lock`. `uv sync` resolves dependencies on the target system; commit the resulting lockfile for reproducible submission.

## Streamlit workflow

1. Choose the goal, experience level, available days, equipment and optional limitations. The limitations placeholder is only a hint, not submitted data.
2. Click **Generate/Regenerate** to request a fresh plan from the current form values.
3. Review the current workout, including its exercises, warm-ups, cooldowns, progression, recovery and Caution.
4. Click **Swap** beside an exercise to request a different exercise with the same training purpose. A successful swap updates the current plan only; an unsuccessful swap preserves it.
5. Download `.md` or `.txt`. Both use the current stored plan, including swaps.
6. Generate again to move the existing current plan into the collapsed **Previous Workout Plan** section.

Only the latest two successful full plans are retained in the current Streamlit session. Session state is not durable storage; refreshing or restarting a session may lose plans.

## Command-line use

```bash
# Interactive profile
uv run workout-generator generate

# Direct profile or scenario-wrapped input
uv run workout-generator generate --input scenarios/01_bodyweight.json

# Structured output with metadata
uv run workout-generator generate --input scenarios/01_bodyweight.json --json --output reports/plan.json

# Batch evaluation: each scenario is isolated and recorded
uv run workout-generator batch --scenarios scenarios --output reports/batch.json

# Check the strict schema locally
uv run workout-generator schema-check

# Validate an existing saved plan against a profile
uv run workout-generator validate --input reports/plan.json --profile profile.json
```

A standalone `profile.json` has this form:

```json
{
  "goal": "general_fitness",
  "experience": "beginner",
  "days_per_week": 3,
  "equipment": "no_equipment",
  "limitations": null
}
```

Scenario files wrap a profile under `profile` and add an `id` and optional `expected_exercises_absent` list. See `scenarios/` for examples. `generate --input` accepts both forms; `batch` expects scenario files.

For diagnostic tracebacks, place `--diagnostic` **before** the subcommand:

```bash
uv run workout-generator --diagnostic generate --input scenarios/01_bodyweight.json
```

Review logs before sharing; they may include user-supplied limitations or provider error details.

## Testing and quality checks

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright src
```

`pytest` covers data models, prompt/schema handling, retry behaviour, CLI input, reporting, Streamlit helpers, and swapping. Unit tests use fake providers; they do not make live Groq calls. Lint and type-check commands are provided as **review checks**, not represented as clean or enforced release gates.

The batch command produces a JSON report with per-scenario success/failure, findings, plans, API request counts, retries, and timings. A passed scenario means it passed the implemented checks, **not** that the workout is medically safe or optimal.

## Structured-output and error-handling design

The LLM returns `WorkoutPlan` with nested `WorkoutDay` and `Exercise` models. `strict_schema()` checks that object properties are all required, `additionalProperties` is false, and local references resolve. **It preserves Pydantic `$defs` / `$ref`** rather than flattening them. This approach was verified in Phase 0 against Groq for the tested schemas.

The full-plan request defaults to 8,192 completion tokens, with bounded recovery for recognized token exhaustion, JSON-generation errors, rate limits and transient infrastructure errors. Invalid request/schema errors are not retried indiscriminately. See [Developer's Guide](docs/DEVELOPER_GUIDE.md) for the retry policy and call flow.

Equipment checks detect selected known incompatibilities without restricting exercise names to a fixed whitelist. Free-text limitations are not interpreted medically. The application-owned Caution is displayed once at the end of the report; LLM-generated caution text is not displayed.

## Source map

| Path | Responsibility |
|---|---|
| `src/workout_generator/models.py` | Pydantic input, output and evaluation models |
| `prompts.py` | Versioned system/user messages |
| `schema.py` | Strict-schema invariant checks |
| `service.py` | Groq adapter, retry policy and generation orchestration |
| `validation.py` | Best-effort semantic checks |
| `swapping.py` | Targeted single-exercise replacement |
| `reporting.py`, `disclaimers.py` | Downloads and fixed Caution |
| `streamlit_app.py` | Form, current/previous plans, inline swap controls |
| `cli.py` | Interactive, batch and validation commands |
| `tests/` | Regression tests |
| `scenarios/` | Batch input fixtures |

See [Developer's Guide](docs/DEVELOPER_GUIDE.md) for architecture, data flow, design rationale and extension points.

## Known limitations

- Groq model outputs are nondeterministic. Occasional `json_validate_failed` responses can occur despite an accepted schema.
- Automatic semantic validation is incomplete; it does not guarantee exercise safety, correct equipment declarations, or optimal training balance.
- The full-plan and exercise-swap requests have separate response schemas. A successful swap updates the current plan, but the app does not maintain a full edit history or persistent database.
- Streamlit UI appearance and live Groq behaviour must be verified on the target Ubuntu machine.
- The current source retains a few legacy helpers from earlier iterations; they are documented but not used in the primary Generate/Regenerate path.

## Assignment and submission

The assignment emphasizes structured inputs, prompt quality, usable output, error handling and readable typed Python code. Before publishing a public GitHub repository, run the tests and an actual Streamlit session, inspect the generated workout quality, commit `uv.lock`, and confirm that `.env`, logs and sensitive user data are not included.

## Final code-quality cleanup

This release candidate addresses the lint and type-check findings from the Ubuntu final-check log.
It organizes imports, removes unused imports and variables, uses enum instances for interactive
CLI profiles, and makes the retry-service exception logging explicit without suppressing
tracebacks. The user-facing workout functionality and Groq JSON schema are unchanged.

Run the final verification on Ubuntu with:

```bash
uv sync --group dev
uv run pytest -q
uv run ruff check src tests
uv run pyright src
uv run workout-generator schema-check
```

The source archive was checked with the available Python interpreter and pytest.
Ruff and Pyright were not installed in the offline build environment; the Ubuntu
checks above are required before declaring the release lint/type-check clean.
