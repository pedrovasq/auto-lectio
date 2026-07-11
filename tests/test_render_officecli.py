import shutil
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from render import (
    OfficeCli,
    OfficeCliError,
    _officecli_path_from_json,
    build_prune_plans,
    chunks_for_key,
    render_with_officecli,
)


def write_fake_pptx(path: Path, slides: list[str]) -> None:
    with ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for index, text in enumerate(slides, start=1):
            zf.writestr(f"ppt/slides/slide{index}.xml", f"<slide>{text}</slide>")


class FakeOfficeCli:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def check_available(self) -> None:
        self.calls.append(("check",))

    def open(self, deck_path: Path) -> None:
        self.calls.append(("open", deck_path.name))

    def close(self, deck_path: Path) -> None:
        self.calls.append(("close", deck_path.name))

    def replace(self, deck_path: Path, scope: str, token: str, value: str) -> None:
        self.calls.append(("replace", scope, token, value))

    def set_shape_text(self, deck_path: Path, slide_num: int, shape_name: str, value: str) -> None:
        self.calls.append(("set_shape_text", slide_num, shape_name, value))

    def clone_slide_after(self, deck_path: Path, source_slide_num: int, after_slide_num: int) -> int:
        self.calls.append(("clone", source_slide_num, after_slide_num))
        return after_slide_num + 1

    def remove_slide(self, deck_path: Path, slide_num: int) -> None:
        self.calls.append(("remove", slide_num))


class OfficeCliRenderTests(unittest.TestCase):
    def test_officecli_clone_path_parses_json_data(self) -> None:
        self.assertEqual(
            "/slide[94]",
            _officecli_path_from_json('{"success":true,"data":"Copied to /slide[94]"}'),
        )

    def test_waterfall_uses_officecli_clone_and_scoped_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "template.pptx"
            output = tmp_path / "output.pptx"
            write_fake_pptx(template, ["{LITURGICAL_DAY}", "{ENTRANCE_TXT}"])
            original_bytes = template.read_bytes()
            fake = FakeOfficeCli()

            render_with_officecli(
                template_path=template,
                out_path=output,
                placeholders={"{LITURGICAL_DAY}": "Domingo"},
                chunks_map={"{ENTRANCE_TXT}": ["Uno", "Dos", "Tres"]},
                office=fake,
            )

            self.assertEqual(original_bytes, template.read_bytes())
            self.assertTrue(output.exists())
            self.assertIn(("replace", "/", "{LITURGICAL_DAY}", "Domingo"), fake.calls)
            self.assertIn(("clone", 2, 2), fake.calls)
            self.assertIn(("clone", 3, 3), fake.calls)
            self.assertIn(("replace", "/slide[2]", "{ENTRANCE_TXT}", "Uno"), fake.calls)
            self.assertIn(("replace", "/slide[3]", "{ENTRANCE_TXT}", "Dos"), fake.calls)
            self.assertIn(("replace", "/slide[4]", "{ENTRANCE_TXT}", "Tres"), fake.calls)
            self.assertEqual(("close", "output.pptx"), fake.calls[-1])

    def test_duplicate_seed_slide_fails_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "template.pptx"
            output = tmp_path / "output.pptx"
            write_fake_pptx(template, ["{GOSPEL_TXT}", "{GOSPEL_TXT}"])
            fake = FakeOfficeCli()

            with self.assertRaisesRegex(RuntimeError, "Expected exactly one seed slide"):
                render_with_officecli(
                    template_path=template,
                    out_path=output,
                    placeholders={"{GOSPEL_TXT}": "Texto"},
                    chunks_map={"{GOSPEL_TXT}": ["Texto"]},
                    office=fake,
                )

            self.assertEqual([("check",)], fake.calls)

    def test_named_shape_contract_uses_shape_text_setters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "template.pptx"
            output = tmp_path / "output.pptx"
            write_fake_pptx(
                template,
                [
                    '<p:cNvPr id="1" name="AL_TOKEN_LITURGICAL_DAY"/>',
                    '<p:cNvPr id="2" name="AL_SEED_ENTRANCE_TXT"/>',
                ],
            )
            fake = FakeOfficeCli()

            render_with_officecli(
                template_path=template,
                out_path=output,
                placeholders={"{LITURGICAL_DAY}": "Domingo"},
                chunks_map={"{ENTRANCE_TXT}": ["Uno", "Dos"]},
                office=fake,
            )

            self.assertIn(("set_shape_text", 1, "AL_TOKEN_LITURGICAL_DAY", "Domingo"), fake.calls)
            self.assertIn(("clone", 2, 2), fake.calls)
            self.assertIn(("set_shape_text", 2, "AL_SEED_ENTRANCE_TXT", "Uno"), fake.calls)
            self.assertIn(("set_shape_text", 3, "AL_SEED_ENTRANCE_TXT", "Dos"), fake.calls)
            self.assertNotIn(("replace", "/", "{LITURGICAL_DAY}", "Domingo"), fake.calls)

    def test_hymn_chunks_preserve_newlines(self) -> None:
        chunks = chunks_for_key(
            "{ENTRANCE_TXT}",
            placeholders={},
            chunks_map={"{ENTRANCE_TXT}": [" Linea 1\r\nLinea 2 ", "", "Linea 3"]},
        )

        self.assertEqual(["Linea 1\nLinea 2", "Linea 3"], chunks)

    def test_prune_plan_removes_empty_second_reading_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(
                path,
                [
                    "{FIRST_READING_TXT}",
                    "{SECOND_READING_REF}",
                    "{SECOND_READING_TXT}",
                    "Palabra de Dios R: Te alabamos, Señor",
                    "",
                    "Aleluya",
                ],
            )

            plans = build_prune_plans(path, placeholders={}, chunks_map={})

            self.assertIn(("empty {SECOND_READING_TXT}", (2, 3, 4, 5)), [(p.reason, p.slides) for p in plans])

    def test_prune_plan_keeps_second_reading_when_content_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, ["{SECOND_READING_REF}", "{SECOND_READING_TXT}", "Palabra de Dios"])

            plans = build_prune_plans(
                path,
                placeholders={"{SECOND_READING_TXT}": "Lectura"},
                chunks_map={},
            )

            self.assertEqual([], [p for p in plans if p.reason == "empty {SECOND_READING_TXT}"])

    def test_prune_plan_removes_empty_hymn_and_following_blank_spacer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, ["Intro", "{ENTRANCE_TXT}", "", "Next"])

            plans = build_prune_plans(path, placeholders={}, chunks_map={})

            self.assertIn(("empty {ENTRANCE_TXT}", (2, 3)), [(p.reason, p.slides) for p in plans])

    def test_prune_plan_keeps_hymn_when_chunk_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "template.pptx"
            write_fake_pptx(path, ["{ENTRANCE_TXT}", ""])

            plans = build_prune_plans(path, placeholders={}, chunks_map={"{ENTRANCE_TXT}": ["Canto"]})

            self.assertEqual([], [p for p in plans if p.reason == "empty {ENTRANCE_TXT}"])

    def test_pruning_removes_slides_before_replacements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "template.pptx"
            output = tmp_path / "output.pptx"
            write_fake_pptx(
                template,
                [
                    "{LITURGICAL_DAY}",
                    "{SECOND_READING_REF}",
                    "{SECOND_READING_TXT}",
                    "Palabra de Dios",
                    "",
                ],
            )
            fake = FakeOfficeCli()

            render_with_officecli(
                template_path=template,
                out_path=output,
                placeholders={"{LITURGICAL_DAY}": "Domingo"},
                chunks_map={},
                office=fake,
            )

            self.assertEqual(("open", "output.pptx"), fake.calls[1])
            self.assertEqual([("remove", 5), ("remove", 4), ("remove", 3), ("remove", 2)], fake.calls[2:6])
            self.assertEqual(("close", "output.pptx"), fake.calls[6])
            self.assertIn(("replace", "/", "{LITURGICAL_DAY}", "Domingo"), fake.calls[8:])

    def test_keep_empty_sections_skips_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "template.pptx"
            output = tmp_path / "output.pptx"
            write_fake_pptx(template, ["{SECOND_READING_REF}", "{SECOND_READING_TXT}", "Palabra de Dios"])
            fake = FakeOfficeCli()

            render_with_officecli(
                template_path=template,
                out_path=output,
                placeholders={},
                chunks_map={},
                office=fake,
                prune_empty=False,
            )

            self.assertNotIn(("remove", 1), fake.calls)
            self.assertNotIn(("remove", 2), fake.calls)
            self.assertIn(("replace", "/slide[2]", "{SECOND_READING_TXT}", ""), fake.calls)

    def test_officecli_missing_error_is_actionable(self) -> None:
        office = OfficeCli(executable="officecli-definitely-missing")

        with self.assertRaisesRegex(OfficeCliError, "officecli is required"):
            office.check_available()


@unittest.skipUnless(shutil.which("officecli"), "officecli is not installed")
class OfficeCliIntegrationTests(unittest.TestCase):
    def test_officecli_binary_reports_version(self) -> None:
        office = OfficeCli()
        office.check_available()


if __name__ == "__main__":
    unittest.main()
