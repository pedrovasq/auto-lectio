#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pptx_scan import dump_json, scan_pptx, validate_with_officecli


def remaining_supported_tokens(scan: dict[str, Any]) -> dict[str, list[int]]:
    remaining: dict[str, list[int]] = {}
    for token, slides in scan["literal_tokens"]["by_token"].items():
        if slides:
            remaining[token] = slides
    return remaining


def _print_text_summary(path: Path, scan: dict[str, Any], show_tokens: bool) -> None:
    print(f"PPTX: {path}")
    print(f"Slides: {scan['slide_count']}")

    remaining = remaining_supported_tokens(scan)
    if remaining:
        print("\nRemaining supported literal placeholders:")
        for token, slides in remaining.items():
            print(f"  - {token}: slides {', '.join(str(s) for s in slides)}")
    else:
        print("\nRemaining supported literal placeholders: none")

    if scan["shape_names"]["by_name"]:
        print("\nSupported placeholder shape names:")
        for name, slides in scan["shape_names"]["by_name"].items():
            print(f"  - {name}: slides {', '.join(str(s) for s in slides)}")
    else:
        print("\nSupported placeholder shape names: none")

    if show_tokens and scan["literal_tokens"]["by_slide"]:
        print("\nLiteral tokens by slide:")
        for slide_num, tokens in scan["literal_tokens"]["by_slide"].items():
            print(f"  - slide {slide_num}: {', '.join(tokens)}")

    if scan["unsupported_tokens"]["by_token"]:
        print("\nUnsupported placeholder-looking tokens:")
        for token, slides in scan["unsupported_tokens"]["by_token"].items():
            print(f"  - {token}: slides {', '.join(str(s) for s in slides)}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a PPTX deck without mutating it.")
    parser.add_argument("pptx", help="Path to a .pptx deck")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--validate", action="store_true", help="Run optional OfficeCLI validation")
    parser.add_argument("--tokens", action="store_true", help="Print literal token locations by slide")
    parser.add_argument(
        "--fail-on-remaining",
        action="store_true",
        help="Exit 1 when supported literal placeholders remain",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    path = Path(args.pptx)

    try:
        scan = scan_pptx(path)
    except Exception as exc:
        print(f"inspect_pptx.py: {exc}", file=sys.stderr)
        return 2

    validation = None
    if args.validate:
        validation = validate_with_officecli(path)
        scan["officecli_validation"] = validation.to_dict()

    remaining = remaining_supported_tokens(scan)
    payload = {
        "path": str(path),
        "ok": not (args.fail_on_remaining and remaining),
        "remaining_supported_tokens": remaining,
        "scan": scan,
    }
    if validation is not None:
        payload["officecli_validation"] = validation.to_dict()

    if args.json:
        print(dump_json(payload))
    else:
        _print_text_summary(path, scan, args.tokens)
        if validation is not None:
            print(f"\nOfficeCLI: {validation.message}")

    if args.fail_on_remaining and remaining:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
