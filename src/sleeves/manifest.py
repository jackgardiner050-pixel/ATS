"""Sleeve manifest loader — hard validation against config/sleeves/_schema.yaml.

A manifest that omits the two admission-critical fields (registry_ref, kill_criteria) is
refused with the admission rule quoted. Nothing here modifies a protocol-locked file.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = _ROOT / "config" / "sleeves" / "_schema.yaml"
SLEEVES_DIR = _ROOT / "config" / "sleeves"

_PYTYPE = {"str": str, "list": list, "dict": dict, "bool": bool, "int": int, "float": float}
# fields whose absence is an ADMISSION failure (message quotes the admission rule)
_ADMISSION_FIELDS = ("registry_ref", "kill_criteria")


class ManifestError(ValueError):
    """Raised when a sleeve manifest fails hard validation."""


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def _check_type(name, value, spec, err):
    t = _PYTYPE[spec["type"]]
    if not isinstance(value, t) or (t is not bool and isinstance(value, bool)):
        err(f"field '{name}' has wrong type {type(value).__name__}, expected {spec['type']}")


def _validate_fields(data: dict, fields: dict, schema: dict, err, ctx="") -> dict:
    out = dict(data)
    for name, spec in fields.items():
        present = name in data
        if not present:
            if spec.get("required"):
                if name in _ADMISSION_FIELDS:
                    err(f"missing required '{name}'.\n" + str(schema.get("admission_rule", "")).strip())
                err(f"missing required field '{ctx}{name}'")
            elif "default" in spec:
                out[name] = spec["default"]
            continue
        value = data[name]
        _check_type(f"{ctx}{name}", value, spec, err)
        if spec.get("non_empty") and len(value) == 0:
            if name in _ADMISSION_FIELDS:
                err(f"field '{name}' is empty.\n" + str(schema.get("admission_rule", "")).strip())
            err(f"field '{ctx}{name}' must be non-empty")
        if "enum" in spec and value not in spec["enum"]:
            err(f"field '{ctx}{name}'={value!r} not in {spec['enum']}")
        if spec.get("type") == "dict" and "fields" in spec:
            out[name] = _validate_fields(value, spec["fields"], schema, err, ctx=f"{name}.")
    return out


def validate_manifest(data: dict, schema: dict | None = None) -> dict:
    schema = schema or load_schema()

    def err(msg):
        raise ManifestError(msg)

    if not isinstance(data, dict):
        err("manifest is not a mapping")
    return _validate_fields(data, schema["fields"], schema, err)


def load_manifest(path: str | Path, schema: dict | None = None) -> dict:
    data = yaml.safe_load(Path(path).read_text())
    try:
        return validate_manifest(data, schema)
    except ManifestError as e:
        raise ManifestError(f"{Path(path).name}: {e}") from None


def load_all(dir_: str | Path = SLEEVES_DIR) -> dict[str, dict]:
    """Load every sleeve manifest (skips _schema.yaml). Keyed by sleeve_id."""
    schema = load_schema()
    out = {}
    for p in sorted(Path(dir_).glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        m = load_manifest(p, schema)
        out[m["sleeve_id"]] = m
    return out
