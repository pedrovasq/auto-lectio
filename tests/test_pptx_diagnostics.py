import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import inspect_pptx
import lint_template
from pptx_scan import CORE_REQUIRED_TOKENS, scan_pptx, validate_with_officecli


def write_fake_pptx(path: Path, slides: list[str]) -> None:
    with ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for index, text in enumerate(slides, start=1):
            zf.writestr(f"ppt/slides/slide{index}.xml", f"<slide>{text}</slide>")


def minimal_required_slides() -> list[str]:
    return [
        "{LITURGICAL_DAY}",
        "{FIRST_READING_REF}",
        "{FIRST_READING_TXT}",
        "{PSALM_REF}",
        "{PSALM_TXT}",
        "{ACCLAMATION_RES} {ACCLAMATION_VERSE}",
        "{GOSPEL_REF}",
        "{GOSPEL_TXT}",
    ]


class PptxScanTests(unittest.TestCase):
    def test_scanner_finds_literal_placeholders_by_slide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, ["{LITURGICAL_DAY}", "{GOSPEL_TXT}"])

            scan = scan_pptx(path)

            self.assertEqual(2, scan["slide_count"])
            self.assertEqual([1], scan["literal_tokens"]["by_token"]["{LITURGICAL_DAY}"])
            self.assertEqual([2], scan["literal_tokens"]["by_token"]["{GOSPEL_TXT}"])

    def test_scanner_finds_supported_shape_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(
                path,
                [
                    '<p:cNvPr id="1" name="AL_TOKEN_LITURGICAL_DAY"/>',
                    '<p:cNvPr id="2" name="AL_SEED_GOSPEL_TXT"/>',
                ],
            )

            scan = scan_pptx(path)

            self.assertEqual([1], scan["shape_names"]["by_name"]["AL_TOKEN_LITURGICAL_DAY"])
            self.assertEqual([2], scan["shape_names"]["by_name"]["AL_SEED_GOSPEL_TXT"])

    def test_scanner_reports_unsupported_placeholder_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, ["{FOO_BAR}", "{GOSPEL_TXT}"])

            scan = scan_pptx(path)

            self.assertEqual([1], scan["unsupported_tokens"]["by_token"]["{FOO_BAR}"])


class TemplateLintTests(unittest.TestCase):
    def test_linter_passes_minimal_required_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, minimal_required_slides())

            scan = scan_pptx(path)
            errors, warnings = lint_template.lint_template(scan)

            self.assertEqual([], errors)
            self.assertTrue(any("{SECOND_READING_REF}" in warning for warning in warnings))

    def test_linter_errors_on_duplicate_waterfall_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, [*minimal_required_slides(), "{GOSPEL_TXT}"])

            scan = scan_pptx(path)
            errors, _warnings = lint_template.lint_template(scan)

            self.assertTrue(any("duplicate waterfall seed {GOSPEL_TXT}: slides 8, 9" in error for error in errors))

    def test_linter_warns_not_errors_for_missing_second_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, minimal_required_slides())

            scan = scan_pptx(path)
            errors, warnings = lint_template.lint_template(scan)

            self.assertEqual([], errors)
            self.assertTrue(any("missing optional second reading placeholder {SECOND_READING_TXT}" in w for w in warnings))

    def test_linter_warns_on_unsupported_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            slides = minimal_required_slides()
            slides[0] += " {FOO_BAR}"
            write_fake_pptx(path, slides)

            scan = scan_pptx(path)
            errors, warnings = lint_template.lint_template(scan)

            self.assertEqual([], errors)
            self.assertTrue(any("unsupported placeholder-looking token {FOO_BAR}: slides 1" in w for w in warnings))

    def test_lint_cli_duplicate_fixture_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, [*minimal_required_slides(), "{GOSPEL_TXT}"])

            with contextlib.redirect_stdout(io.StringIO()):
                code = lint_template.main([str(path)])

            self.assertEqual(1, code)

    def test_required_tokens_constant_is_used_by_fixture(self) -> None:
        fixture_tokens = set(" ".join(minimal_required_slides()).split())
        for token in CORE_REQUIRED_TOKENS:
            self.assertIn(token, fixture_tokens)


class PptxInspectTests(unittest.TestCase):
    def test_inspector_reports_remaining_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rendered.pptx"
            write_fake_pptx(path, ["Done", "{GOSPEL_TXT}"])

            scan = scan_pptx(path)
            remaining = inspect_pptx.remaining_supported_tokens(scan)

            self.assertEqual({"{GOSPEL_TXT}": [2]}, remaining)

    def test_inspector_fail_on_remaining_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rendered.pptx"
            write_fake_pptx(path, ["Done", "{GOSPEL_TXT}"])

            with contextlib.redirect_stdout(io.StringIO()):
                code = inspect_pptx.main([str(path), "--fail-on-remaining"])

            self.assertEqual(1, code)

    def test_inspector_fail_on_remaining_passes_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rendered.pptx"
            write_fake_pptx(path, ["Done"])

            with contextlib.redirect_stdout(io.StringIO()):
                code = inspect_pptx.main([str(path), "--fail-on-remaining"])

            self.assertEqual(0, code)

    def test_officecli_validation_helper_handles_missing_binary(self) -> None:
        result = validate_with_officecli("dummy.pptx", executable="officecli-definitely-missing")

        self.assertFalse(result.attempted)
        self.assertFalse(result.ok)
        self.assertIn("not on PATH", result.message)


if __name__ == "__main__":
    unittest.main()
