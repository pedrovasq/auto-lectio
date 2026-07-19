import unittest
from datetime import date

from scripts.extract_ocp_psalms import (
    OcpEntry,
    PdfRefs,
    build_day_songs_payload,
    extract_pdf_entry_text,
    extract_refs_from_entry_text,
    parse_direct_usccb_sections,
    parse_celebration_index,
)


class OcpExtractionTests(unittest.TestCase):
    def test_parse_celebration_index_finds_entries_from_july_19_forward(self) -> None:
        text = """
233
XV Domingo del Tiempo Ordinario
12 de julio 168
XVI Domingo del Tiempo Ordinario
19 de julio 170
XVII Domingo del Tiempo Ordinario
26 de julio 172
The Exaltation of the Holy Cross
September 14 198
XXV Domingo del Tiempo Ordinario
20 de septiembre 200
"""

        entries = [
            entry
            for entry in parse_celebration_index(text, season_start_year=2026)
            if entry.date >= date(2026, 7, 19)
        ]

        self.assertEqual(
            [
                OcpEntry(date(2026, 7, 19), "XVI Domingo del Tiempo Ordinario", 170, "19 de julio"),
                OcpEntry(date(2026, 7, 26), "XVII Domingo del Tiempo Ordinario", 172, "26 de julio"),
                OcpEntry(date(2026, 9, 20), "XXV Domingo del Tiempo Ordinario", 200, "20 de septiembre"),
            ],
            entries,
        )

    def test_extract_refs_from_entry_text(self) -> None:
        text = """
Salmo Responsorial: Salmo 85, 5-6. 9-10. 15-16a
Aclamación Antes del Evangelio: Cfr Mateo 11, 25
"""

        refs = extract_refs_from_entry_text(text)

        self.assertEqual("Salmo 85, 5-6. 9-10. 15-16a", refs.psalm_ref)
        self.assertEqual("Cfr Mateo 11, 25", refs.acclamation_ref)

    def test_extract_pdf_entry_text_builds_reviewable_text(self) -> None:
        text = """
Salmo Responsorial: Salmo 85, 5-6. 9-10. 15-16a   Arr. de Example
Respuesta:
Tú,                Se         ñor,        e         res         bue    no y        cle        men te.
Teclado
Estrofas:
1. Tú, Señor, eres bueno y cle mente, rico en misericordia con los que
2. Todos los pueblos vendrán
          a postrarse en tu presencia, Se ñor, bendecirán
1. te in vocan. Señor, escucha mi o ra ción,
2. tu nombre: “Grande eres tú y haces ma ra villas;
1. atiende a la voz de mi súplica.
2. tú eres el úni co Dios”.
Aclamación Antes del Evangelio: Cfr Mateo 11, 25   Arr. de Example
Respuesta: No. 5
A le lu ya, a le lu ya, a le lu ya.
Versículo:
Bendito seas, Padre, Señor del cielo y de la tierra,
porque revelaste los secretos del Reino a la gen te sen cilla.
Letra del versículo © 1972
"""

        data = extract_pdf_entry_text(text)

        self.assertEqual("Salmo 85, 5-6. 9-10. 15-16a", data.refs.psalm_ref)
        self.assertEqual("Cfr Mateo 11, 25", data.refs.acclamation_ref)
        self.assertIn("R. Tú, Señor, eres bueno y clemente.", data.psalm_text)
        self.assertIn("Todos los pueblos vendrán a postrarse", data.psalm_text)
        self.assertEqual("Aleluya, Aleluya, Aleluya", data.acclamation_res)
        self.assertIn("gente sencilla", data.acclamation_verse)

    def test_pdf_cleanup_joins_syllable_hyphens_without_removing_real_words(self) -> None:
        text = """
Salmo Responsorial: Salmo 118, 57 y 72
Respuesta:
Mi Sol La Re Cuán - to a - mo tu vo - lun - tad, Se - ñor.
Teclado
Estrofas:
1. Mi porción es el Se - ñor, he resuelto guardar tus pa - la - bras.
4. Tus preceptos son admirables; á Española. Inicio 2 j la explicación de tus palabras i - lu - mina.
Aclamación Antes del Evangelio: Cfr Mateo 11, 25
Versículo:
Bendito seas, Padre.
Letra del versículo © 1972
"""

        data = extract_pdf_entry_text(text)

        self.assertIn("R. Cuánto amo tu voluntad, Señor.", data.psalm_text)
        self.assertIn("Mi porción es el Señor", data.psalm_text)
        self.assertNotIn("Mi Sol La Re", data.psalm_text)
        self.assertIn("la explicación de tus palabras ilumina", data.psalm_text)
        self.assertNotIn("Inicio 2 j", data.psalm_text)
        self.assertNotIn(" - ", data.psalm_text)

    def test_build_day_songs_payload_keeps_psalm_and_acclamation_contract(self) -> None:
        entry = OcpEntry(date(2026, 7, 19), "XVI Domingo del Tiempo Ordinario", 170, "19 de julio")
        reading_payload = {
            "meta": {
                "title": "Decimosexto Domingo del Tiempo Ordinario",
                "link": "https://example.test/071926.cfm",
            },
            "placeholders": {
                "{PSALM_REF}": "Salmo 85",
                "{PSALM_TXT}": "R. Tu, Senor, eres bueno.\nTu, Senor, eres bueno y clemente.",
                "{ACCLAMATION_RES}": "Aleluya, Aleluya, Aleluya",
                "{ACCLAMATION_VERSE}": "Bendito seas, Padre.",
            },
        }

        payload = build_day_songs_payload(
            entry,
            reading_payload,
            "book.pdf",
            PdfRefs(psalm_ref="Salmo 85, 5-6", acclamation_ref="Cfr Mateo 11, 25"),
        )

        self.assertEqual("2026-07-19", payload["meta"]["date"])
        self.assertEqual("Salmo 85", payload["placeholders"]["{PSALM_REF}"])
        self.assertEqual(["R. Tu, Senor, eres bueno.", "Tu, Senor, eres bueno y clemente."], payload["chunks"]["{PSALM_TXT}"])

    def test_parse_direct_usccb_sections(self) -> None:
        html = """
<html><body>
<h2 class="visually-hidden">Menu: Top Buttons</h2>
<h1 class="title-page">Lecturas de Hoy</h1>
<h2>XVII Domingo Ordinario</h2>
<h3>Primera lectura</h3>
<p>1 Reyes 3, 5. 7-12</p><p>Lectura limpia.</p>
<h3>Salmo Responsorial</h3>
<p>Salmo 118, 57 y 72</p>
<p>R. Yo amo, Señor, tus mandamientos.</p>
<p>A mí, Señor, lo que me toca</p>
<p>es cumplir tus preceptos.</p>
<h3>Aclamación antes del Evangelio</h3>
<p>Cfr Mateo 11, 25</p>
<p>R. Aleluya, aleluya.</p>
<p>Te doy gracias, Padre.</p>
<p>R. Aleluya.</p>
</body></html>
"""

        title, sections = parse_direct_usccb_sections(html)

        self.assertEqual("XVII Domingo Ordinario", title)
        self.assertIn(
            (
                "Salmo Responsorial Salmo 118, 57 y 72",
                "R. Yo amo, Señor, tus mandamientos.\nA mí, Señor, lo que me toca\nes cumplir tus preceptos.",
            ),
            sections,
        )
        self.assertIn(
            (
                "Aclamación antes del Evangelio Cfr Mateo 11, 25",
                "R. Aleluya, aleluya.\nTe doy gracias, Padre.\nR. Aleluya.",
            ),
            sections,
        )


if __name__ == "__main__":
    unittest.main()
