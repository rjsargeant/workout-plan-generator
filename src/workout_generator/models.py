"""Strict, typed application and LLM contracts."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model rejecting unexpected input fields; strict Groq schema rules are checked separately."""
    model_config = ConfigDict(extra="forbid")

class Goal(str, Enum):
    """Supported training objectives exposed by the CLI and Streamlit UI."""
    muscle = "build_muscle"
    fat = "lose_fat"
    general = "general_fitness"
    endurance = "improve_endurance"

class Experience(str, Enum):
    """Supported training-experience levels."""
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"

class Equipment(str, Enum):
    """Equipment-access categories used by prompt construction and validation."""
    none = "no_equipment"
    dumbbells = "home_dumbbells"
    gym = "full_gym"

class FitnessProfile(StrictModel):
    """Validated input profile shared by every application entry point."""
    goal: Goal
    experience: Experience
    days_per_week: int = Field(ge=1, le=7)
    equipment: Equipment
    limitations: str | None = Field(default=None, max_length=500)

    @field_validator("limitations")
    @classmethod
    def clean_limitations(cls, value: str | None) -> str | None:
        """Normalize whitespace-only limitations to None."""
        return value.strip() or None if value is not None else None

class Exercise(StrictModel):
    """One exercise prescription in a generated or swapped workout."""
    name: str
    sets: int
    repetitions: str | None
    duration_seconds: int | None
    rest_seconds: int
    instructions: str
    equipment_required: list[str]

    @model_validator(mode="after")
    def check_prescription(self):
        """Reject blank or implausible prescriptions after Pydantic type parsing."""
        if not self.name.strip() or not self.instructions.strip():
            raise ValueError("exercise name and instructions cannot be blank")
        if self.sets < 1 or self.sets > 20 or self.rest_seconds < 0 or self.rest_seconds > 900:
            raise ValueError("implausible sets or rest interval")
        if (not self.repetitions or not self.repetitions.strip()) and (
            self.duration_seconds is None or self.duration_seconds <= 0
        ):
            raise ValueError("exercise needs repetitions or positive duration")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("duration must not be negative")
        return self

class WorkoutDay(StrictModel):
    """A numbered training day with exercise prescriptions and supporting guidance."""
    day_number: int
    day_of_week: Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    focus: str
    warmup: str
    exercises: list[Exercise]
    cooldown: str

class WorkoutPlan(StrictModel):
    """Complete structured output requested from the full-plan Groq call."""
    title: str
    overview: str
    goal: Goal
    experience: Experience
    days_per_week: int
    workout_days: list[WorkoutDay]
    progression_guidance: str
    recovery_guidance: str
    disclaimer: str | None

class Finding(StrictModel):
    """One semantic validation observation with severity and stable code."""
    severity: Literal["error", "warning", "info"]
    code: str
    message: str

class Evaluation(StrictModel):
    """Aggregate semantic validation findings for a plan."""
    findings: list[Finding]
    @property
    def valid(self) -> bool:
        """True when no error-severity finding exists; warnings do not block plans."""
        return not any(f.severity == "error" for f in self.findings)

class GenerationResult(StrictModel):
    """Successful generation plus diagnostic and retry metadata."""
    plan: WorkoutPlan
    evaluation: Evaluation
    attempts: int
    api_requests: int = 0
    transport_retries: int = 0
    recovered: bool = False
    retry_history: list[dict[str, str | int | float]] = Field(default_factory=list)
    model: str
    prompt_version: str
    elapsed_seconds: float
    usage: dict[str, int] | None = None

class Scenario(StrictModel):
    """Batch fixture containing an identifier, input profile and exclusions."""
    id: str
    profile: FitnessProfile
    expected_exercises_absent: list[str] = Field(default_factory=list)

class ScenarioResult(StrictModel):
    """Per-scenario success/failure, plan and diagnostic data."""
    id: str
    status: Literal["passed", "failed"]
    attempts: int
    duration_seconds: float
    api_requests: int = 0
    transport_retries: int = 0
    recovered: bool = False
    retry_history: list[dict[str, str | int | float]] = Field(default_factory=list)
    findings: list[Finding]
    error: str | None
    plan: WorkoutPlan | None

class BatchReport(StrictModel):
    """Combined results for a batch run and its fixed medical disclaimer."""
    model: str
    prompt_version: str
    results: list[ScenarioResult]
    medical_disclaimer: str = ""
    @property
    def passed(self) -> int:
        """Number of scenarios whose final status is passed."""
        return sum(r.status == "passed" for r in self.results)
