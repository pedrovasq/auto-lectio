#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pptx_scan import (
    CORE_REQUIRED_TOKENS,
    HYMN_TOKENS,
    OPTIONAL_HYMN_REF_TOKENS,
    OPTIONAL_SECOND_READING_TOKENS,
    WATERFALL_TOKENS,
    dump_json,
    has_placeholder,
    scan_pptx,
    seed_count,
    validate_with_officecli,
)


def lint_template(scan: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for token in CORE_REQUIRED_TOKENS:
        if not has_placeholder(scan, token):
            errors.append(f"missing required placeholder {token}")

    for token in WATERFALL_TOKENS:
        count = seed_count(scan, token)
        if count > 1:
            locations = scan["waterfall_seeds"][token]
            slides = sorted(set(locations.get("literal", []) + locations.get("shape", [])))
            errors.append(f"duplicate waterfall seed {token}: slides {', '.join(str(s) for s in slides)}")

    for token in OPTIONAL_SECOND_READING_TOKENS:
        if not has_placeholder(scan, token):
            warnings.append(f"missing optional second reading placeholder {token}")

    for token in HYMN_TOKENS:
        if not has_placeholder(scan, token):
            warnings.append(f"missing optional hymn/fixed-part seed {token}")

    for token in OPTIONAL_HYMN_REF_TOKENS:
        if not has_placeholder(scan, token):
            warnings.append(f"missing optional hymn reference placeholder {token}")

    unsupported = scan["unsupported_tokens"]["by_token"]
    for token, slides in unsupported.items():
        warnings.append(f"unsupported placeholder-looking token {token}: slides {', '.join(str(s) for s in slides)}")

    return errors, warnings


def _print_text_summary(path: Path, scan: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    print(f"Template: {path}")
    print(f"Slides: {scan['slide_count']}")
    print(f"Supported literal placeholders: {len(scan['literal_tokens']['by_token'])}")
    print(f"Supported named shapes: {len(scan['shape_names']['by_name'])}")

    if errors:
        print("\nErrors:")
        for item in errors:
            print(f"  - {item}")
    else:
        print("\nErrors: none")

    if warnings:
        print("\nWarnings:")
        for item in warnings:
            print(f"  - {item}")
    else:
        print("\nWarnings: none")

    seeds = [
        (token, sorted(set(locations.get("literal", []) + locations.get("shape", []))))
        for token, locations in scan["waterfall_seeds"].items()
        if locations.get("literal") or locations.get("shape")
    ]
    if seeds:
        print("\nWaterfall seeds:")
        for token, slides in seeds:
            print(f"  - {token}: slides {', '.join(str(s) for s in slides)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint an Auto-Lectio PPTX template without mutating it.")
    parser.add_argument("template", help="Path to a .pptx template")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--validate", action="store_true", help="Run optional OfficeCLI validation")
    parser.add_argument(
        "--require-officecli",
        action="store_true",
        help="Exit 2 if --validate is requested and officecli is missing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    path = Path(args.template)

    try:
        scan = scan_pptx(path)
    except Exception as exc:
        print(f"lint_template.py: {exc}", file=sys.stderr)
        return 2

    errors, warnings = lint_template(scan)
    validation = None
    if args.validate:
        validation = validate_with_officecli(path)
        scan["officecli_validation"] = validation.to_dict()
        if not validation.attempted and args.require_officecli:
            print(f"lint_template.py: {validation.message}", file=sys.stderr)
            return 2
        if not validation.ok:
            warnings.append(validation.message)

    payload = {
        "path": str(path),
        "ok": not errors and not (args.strict and warnings),
        "errors": errors,
        "warnings": warnings,
        "scan": scan,
    }
    if validation is not None:
        payload["officecli_validation"] = validation.to_dict()

    if args.json:
        print(dump_json(payload))
    else:
        _print_text_summary(path, scan, errors, warnings)
        if validation is not None:
            print(f"\nOfficeCLI: {validation.message}")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
