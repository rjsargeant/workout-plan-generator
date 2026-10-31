"""Validate strict-mode invariants without flattening Pydantic's $defs."""
from __future__ import annotations

from typing import Any

from .models import WorkoutPlan


class SchemaError(ValueError):
    """Raised when generated JSON Schema violates required strict-mode invariants."""

def strict_schema(model: type = WorkoutPlan) -> dict[str, Any]:
    """Check required fields, additionalProperties and local references without flattening."""
    # Groq accepted Pydantic local references during Phase 0; inspect rather than flatten.
    schema = model.model_json_schema()
    problems: list[str] = []
    def walk(node: Any, path: str) -> None:
        """Recursively inspect schema nodes and collect compatibility errors."""
        if isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, f"{path}/{i}")
        elif isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                props = node.get("properties", {})
                if set(node.get("required", [])) != set(props):
                    problems.append(f"{path}: all properties must be required")
                if node.get("additionalProperties") is not False:
                    problems.append(f"{path}: additionalProperties must be false")
            ref = node.get("$ref")
            if ref is not None:
                if not isinstance(ref, str) or not ref.startswith("#/"):
                    problems.append(f"{path}: unsupported reference {ref}")
                else:
                    target: Any = schema
                    try:
                        for segment in ref[2:].split("/"):
                            target = target[segment.replace("~1", "/").replace("~0", "~")]
                    except (KeyError, TypeError, IndexError):
                        problems.append(f"{path}: unresolved reference {ref}")
            for key, value in node.items():
                walk(value, f"{path}/{key}")
    walk(schema, "$")
    if problems:
        raise SchemaError("; ".join(problems))
    return schema
