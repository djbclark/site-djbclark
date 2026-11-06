#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Check a bottom (btm) config file against bottom's JSON schema, strictly.

bottom ignores unknown keys in release builds, so a typo like
`split_comand = true` is silently dropped. The published schema does not
forbid unknown keys either, so this script adds additionalProperties=false to
every object that lists properties and suggests the nearest real key.

    validate.py [CONFIG] [--schema SCHEMA.json]

Exit 0: valid. Exit 1: problems printed. Exit 2: cannot read an input.
"""

import argparse
import difflib
import json
import sys
import tomllib
from pathlib import Path

from jsonschema.validators import validator_for

DEFAULT_CONFIG = Path.home() / ".config/bottom/bottom.toml"
# The fork's schema: it knows processes.split_command, upstream's does not.
DEFAULT_SCHEMA = Path.home() / "src/bottom/schema/nightly/bottom.json"


def make_strict(node):
    if isinstance(node, dict):
        if "properties" in node and "additionalProperties" not in node:
            node["additionalProperties"] = False
        for value in node.values():
            make_strict(value)
    elif isinstance(node, list):
        for value in node:
            make_strict(value)


def where(error) -> str:
    return ".".join(str(p) for p in error.absolute_path) or "(top level)"


def describe(error) -> str:
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        known = list(error.schema.get("properties", {}))
        lines = []
        for key in sorted(set(error.instance) - set(known)):
            near = difflib.get_close_matches(key, known, n=1)
            hint = f" (did you mean '{near[0]}'?)" if near else ""
            lines.append(f"unknown key '{key}'{hint}")
        return "; ".join(lines)
    return error.message


def leaves(error):
    """Expand anyOf/oneOf into the errors of the branch that got furthest, so a
    bad key inside `processes` is reported as that key, not as 'not valid under
    any of the given schemas'."""
    if not error.context:
        yield error
        return
    deepest = max(error.context, key=lambda e: len(e.absolute_path))
    branch = deepest.schema_path[0]
    for sub in error.context:
        if sub.schema_path[0] == branch:
            yield from leaves(sub)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", nargs="?", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()

    try:
        schema = json.loads(args.schema.read_text())
        config = tomllib.loads(args.config.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read input: {exc}", file=sys.stderr)
        return 2

    make_strict(schema)
    validator = validator_for(schema)(schema)
    errors = [leaf for e in validator.iter_errors(config) for leaf in leaves(e)]
    errors.sort(key=lambda e: list(map(str, e.absolute_path)))
    if not errors:
        print(f"ok: {args.config}")
        return 0
    for error in errors:
        print(f"{args.config}: {where(error)}: {describe(error)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
