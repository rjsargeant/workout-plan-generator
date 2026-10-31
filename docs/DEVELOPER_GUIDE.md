# Developer's Guide — Workout Plan Generator

## 1. Design intent

This application demonstrates reliable LLM-assisted generation using structured user inputs, a versioned prompt, strict JSON Schema and independent local validation. It deliberately avoids an orchestration framework and an exhaustive exercise ontology. The goal is a comprehensible educational implementation, not clinical exercise prescription.

The codebase separates the **interface** (CLI / Streamlit), **application service** (generation and recovery), **provider** (Groq), **contracts** (Pydantic), and **reporting** (Markdown / text).

## 2. Full-plan request flow

```text
CLI or Streamlit form
    |
    v
FitnessProfile (Pydantic validation)
    |
    v
build_messages(profile) + strict_schema(WorkoutPlan)
    |
    v
GroqProvider.generate()  -- response_format: json_schema, strict: true
    |
    v
WorkoutPlan.model_validate_json()
    |
    v
evaluate(plan, original_profile)
    |
    +-- valid --> GenerationResult --> UI / CLI / batch / downloads
    |
    +-- recoverable error --> bounded retry --> same validation path
    |
    +-- permanent error --> GenerationError with diagnostic metadata
```

`FitnessProfile` is the authoritative representation of the user's structured inputs. The prompt builder serializes it as data, rather than accepting free-form instructions as the complete request. User-supplied limitations are data and must not override the system-level requirements.

## 3. Models and schema contract

`models.py` defines the shared Pydantic structures:

- `FitnessProfile`: goal, experience, days/week, equipment, optional limitations.
- `Exercise`: name, sets, reps or duration, rest, instructions, declared equipment.
- `WorkoutDay`: numbered weekday, focus, warm-up, exercises and cooldown.
- `WorkoutPlan`: complete week, progression/recovery guidance and a nullable LLM disclaimer field.
- `GenerationResult`: plan, evaluation, attempt counts, request counts and usage.
- `Scenario`, `ScenarioResult`, `BatchReport`: reproducible batch-evaluation contracts.

The LLM-facing models are `WorkoutPlan` and its nested types. A separate `SwapResponse` wraps a single `Exercise` for the swap feature. Diagnostic metadata is **not** part of the model's workout-plan response schema.

Groq strict mode requires all object properties to be required and `additionalProperties: false`. Nullable fields remain required. Pydantic's generated local `$defs` and `$ref` are preserved because Phase 0 tests showed that Groq accepted the tested references. `strict_schema()` verifies key invariants and reference resolution; it is **not** a full validator for every Groq-specific schema restriction. Schema changes should be tested locally and against Groq.

## 4. Prompt design

`prompts.py` contains `SYSTEM_PROMPT`, `PROMPT_VERSION` and `build_messages()`. The system message establishes the role, equipment and scheduling constraints, response quality, concise instructions and medical boundaries. The user message contains the validated profile and optional corrective feedback.

The active **Generate/Regenerate** button always requests a fresh plan using the current widget inputs; it does not automatically pass a previous plan or compare profiles. The code retains a `previous_plan` prompt path from earlier iterations, but the active button does not use it.

The prompt governs qualitative training choices (balanced programming, appropriate recovery, exercise variety); the validator checks only objective, implementable constraints. This avoids treating an exercise-name catalogue as a whitelist.

## 5. Provider and retry policy

`GroqProvider` uses `openai/gpt-oss-120b` with `response_format.type='json_schema'` and `strict=True`. The SDK's automatic retries are disabled so the application can account for actual API requests.

`generate_plan()` has two nested recovery concepts:

1. **Generation attempts:** initial generation and, where allowed, one corrective attempt for an invalid output or a recognized model JSON-generation failure.
2. **Transport retries:** bounded repeats within a generation attempt for HTTP 429, network problems and selected 5xx responses. These do not automatically consume the generation-quality budget.

Defaults in `RetryPolicy`:

| Parameter | Default |
|---|---:|
| Maximum generation attempts | 2 |
| Initial completion tokens | 8,192 |
| Completion-token ceiling | 16,384 |
| Rate-limit retries per generation | 3 |
| Transient retries per generation | 2 |
| Total API requests | 8 |
| Total elapsed time | 120 seconds |
| Initial / maximum backoff | 1 / 30 seconds |

A `json_validate_failed` error with explicit token exhaustion can increase the completion budget within its ceiling. A generic `json_validate_failed` may receive one retry. A malformed *request schema* is not treated as an intermittent model-generation error. `Retry-After` is respected when usable. `GenerationError` retains request counts and retry history.

The full `failed_generation` response is intentionally excluded from concise reports because it can contain sensitive user inputs. Diagnostic logging should still be reviewed for accidental disclosure.

## 6. Semantic validation and safety boundary

`validation.py` checks schedule integrity, selected known equipment conflicts and explicit restrictions. `GYM_ONLY` is a small negative-detection list; it does **not** define every permitted exercise. Unknown exercises are not rejected merely for being unknown. A special running-movement check avoids treating cycling or rowing sprints as running.

A valid result means no error-severity finding was detected. It does not mean a healthcare professional assessed the plan. The Caution text in `disclaimers.py` is fixed application wording, not a model diagnosis. When limitations are entered, the text quotes the original user-supplied description without interpretation. The LLM's `disclaimer` field is retained for schema compatibility but is not shown as a separate medical caution.

## 7. Exercise swapping

`swapping.replace_exercise()` receives the current plan, the **saved profile associated with that plan**, and day/exercise indices. It requests one alternative with the same training intent through the smaller `SwapResponse` schema. It checks that the exercise name changes, constructs a deep-copied candidate plan, and evaluates the candidate against the saved profile.

Only after validation does `streamlit_app.swap_selected_exercise()` replace the current session result. If the operation fails, the stored plan remains unchanged. The Previous Plan is not affected by swaps.

## 8. Streamlit session state and reporting

`store_successful_plan()` moves the current successful full plan to `previous_result` and saves the new `last_result` and `last_profile`. The previous plan is shown in a collapsed expander and is read-only. The UI's interactive exercise rows use native Streamlit columns because Markdown tables cannot contain buttons.

The download functions in `reporting.py` serialize `last_result.plan` on the current render, so they include successful swaps. They do not include interactive controls. `report_layout_css()` caps the wide Streamlit content container at 1,200 pixels. The form's placeholder is not part of the submitted fitness profile.

## 9. CLI and batch evaluation

`cli.py` provides `generate`, `batch`, `validate`, and `schema-check`. `load_profile()` accepts both a direct profile and a scenario wrapper. `batch_run()` isolates each scenario's failure, captures request/retry metadata, and writes a `BatchReport` JSON file. Scenarios include known exclusions for evaluation, but these checks are intentionally limited.

The JSON report contains a fixed medical disclaimer. Batch pass/fail status should be complemented by human review of plan balance and usability, particularly for user-supplied limitations.

## 10. Testing and maintenance

Run `uv run pytest -q` after any changes. Tests use fake providers and exercise input parsing, schemas, retries, UI state, report formatting, and swaps. Live API and visual Streamlit checks are separate manual acceptance activities.

When modifying the response model, verify that **all new fields are required** in Groq's strict schema, use nullable types when appropriate, and add a focused live compatibility test. When modifying the prompt, compare the same batch scenarios before and after changes. When modifying the UI, check that both downloads reflect the current plan after swaps.

## 11. Deliberately deferred concerns

No persistent database, complete plan-history system, profile-comparison logic, medical diagnosis, exercise ontology, or sophisticated workout optimization is included. These were deferred to keep the project aligned with the assignment rubric.
