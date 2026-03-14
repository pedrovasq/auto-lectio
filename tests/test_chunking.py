import unittest

from chunking import chunk_text, rebalance_chunks


class ChunkingTests(unittest.TestCase):
    def test_chunk_text_avoids_tiny_dialogue_tail(self) -> None:
        text = (
            "La samaritana le contestó: “¿Cómo es que tú, siendo judío, me pides de beber a mí, "
            "que soy samaritana?” (Porque los judíos no tratan a los samaritanos)."
        )

        chunks = chunk_text(text)

        self.assertEqual(1, len(chunks))
        self.assertGreaterEqual(len(chunks[0]), 120)

    def test_chunk_text_rebalances_short_remainder(self) -> None:
        text = (
            "En aquellos días, el rey Salomón convocó en Jerusalén a todos los ancianos y jefes de Israel, "
            "para subir allá el arca de la alianza del Señor desde Sión, la ciudad de David. "
            "Todos los israelitas se congregaron en torno al rey Salomón para la fiesta de los tabernáculos, "
            "que se celebra el séptimo mes del año."
        )

        chunks = chunk_text(text)

        self.assertTrue(all(len(chunk) >= 80 for chunk in chunks), chunks)
        self.assertLessEqual(len(chunks), 3)

    def test_rebalance_chunks_merges_pathological_short_entries(self) -> None:
        original = [
            "En aquellos días, el rey Salomón convocó en Jerusalén a todos los ancianos y jefes de Israel,",
            "para subir allá el arca de la alianza del Señor desde Sión,",
            "la ciudad de David.",
            "Todos los israelitas se congregaron en torno al rey Salomón para la fiesta de los tabernáculos, que se celebra el séptimo mes del año.",
        ]

        chunks = rebalance_chunks(original)

        self.assertTrue(all(len(chunk) >= 80 for chunk in chunks), chunks)
        self.assertLess(len(chunks), len(original))


if __name__ == "__main__":
    unittest.main()
