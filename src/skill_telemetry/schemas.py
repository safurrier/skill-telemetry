"""Validate public CLI JSON using the packaged Draft 2020-12 schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Protocol, cast

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


class _SchemaValidator(Protocol):
    def validate(self, instance: object) -> None: ...


class SchemaError(ValueError):
    """Raised when a CLI JSON document does not satisfy its public v1 shape."""


COMMANDS = frozenset(
    {
        "version",
        "doctor",
        "readout",
        "usage",
        "ingest.pi",
        "ingest.codex",
        "evaluate",
        "serve",
    }
)
_SCHEMA_PACKAGE = "skill_telemetry"
_ENVELOPE_NAME = "envelope-v1.json"
_COMMAND_DATA_NAME = "command-data-v1.json"


def _schema(name: str) -> dict[str, object]:
    resource = files(_SCHEMA_PACKAGE).joinpath("schemas", name)
    loaded = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SchemaError("packaged schema is not an object")
    return cast(dict[str, object], loaded)


@lru_cache
def _validator() -> _SchemaValidator:
    """Load only packaged schemas and resolve their local references without a network."""
    envelope = _schema(_ENVELOPE_NAME)
    command_data = _schema(_COMMAND_DATA_NAME)
    command_data_id = command_data.get("$id")
    envelope_id = envelope.get("$id")
    if not isinstance(command_data_id, str) or not isinstance(envelope_id, str):
        raise SchemaError("packaged schema is missing an identifier")
    registry = Registry().with_resources(
        (
            (envelope_id, Resource.from_contents(envelope)),
            (command_data_id, Resource.from_contents(command_data)),
        )
    )
    return Draft202012Validator(envelope, registry=registry)


def validate_json_document(document: object) -> None:
    """Validate a finite-command envelope against the packaged v1 schema authority."""
    try:
        _validator().validate(document)
    except ValidationError as exc:
        raise SchemaError("command output does not satisfy schema version 1") from exc
