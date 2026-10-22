import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml

import rassegna
from rassegna import cron_programmazione, invio_programmato, sommario_feed


class ProgrammazioneTest(unittest.TestCase):
    def test_cron_italia_include_ora_legale_e_solare(self):
        cron = cron_programmazione(["lunedi"], "06:45", "Europe/Rome")
        self.assertEqual(cron, ["45 4 * * 1", "45 5 * * 1"])

    def test_ora_locale_e_giorno_scelto_determinano_l_invio(self):
        cfg = {"giorni_invio": ["lunedi"], "ora_invio": "06:45"}
        zona = ZoneInfo("Europe/Rome")
        self.assertTrue(invio_programmato(datetime(2026, 10, 26, 6, 52, tzinfo=zona), cfg))
        self.assertFalse(invio_programmato(datetime(2026, 10, 26, 7, 0, tzinfo=zona), cfg))
        self.assertFalse(invio_programmato(datetime(2026, 10, 27, 6, 50, tzinfo=zona), cfg))

    def test_mezzanotte_locale_programma_il_giorno_utc_precedente(self):
        cron = cron_programmazione(["lunedi"], "00:30", "Europe/Rome")
        self.assertEqual(cron, ["30 22 * * 0", "30 23 * * 0"])

    def test_estratto_usa_il_testo_piu_ricco_del_feed_e_lo_limita(self):
        voce = {
            "summary": "<p>Estratto breve.</p>",
            "content": [{"value": "<p>" + ("Dettagli della notizia. " * 40) + "</p>"}],
        }
        estratto = sommario_feed(voce)
        self.assertGreater(len(estratto), len("Estratto breve."))
        self.assertLessEqual(len(estratto), 600)
        self.assertNotIn("<p>", estratto)

    def test_configurazione_guidata_salva_preferenze_e_tutela_email(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text(yaml.safe_dump({
                "testata": "La Rassegna",
                "fuso_orario": "Europe/Rome",
                "sezioni": [],
            }), encoding="utf-8")
            workflow = root / ".github" / "workflows" / "rassegna.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "on:\n  schedule:\n    - cron: \"0 0 * * *\"\n"
                "  workflow_dispatch:\n",
                encoding="utf-8",
            )
            risposte = [
                "Il mio giornale",
                "Europe/Rome",
                "lun,mer",
                "07:20",
                "Cyber | malware, ransomware",
                "",
                "persona@example.com",
            ]
            with patch.object(rassegna, "QUI", root), patch(
                "builtins.input", side_effect=risposte
            ), patch("builtins.print"):
                self.assertEqual(rassegna.configura(config), 0)

            preferenze = yaml.safe_load((root / "preferenze.yaml").read_text(encoding="utf-8"))
            self.assertEqual(preferenze["giorni_invio"], ["lunedi", "mercoledi"])
            self.assertEqual(preferenze["sezioni"][0]["parole_chiave"], ["malware", "ransomware"])
            self.assertEqual(preferenze["sottotitolo"], "Cyber")
            self.assertNotIn("persona@example.com", (root / "preferenze.yaml").read_text(encoding="utf-8"))
            self.assertIn("MAIL_TO=persona@example.com", (root / ".env").read_text(encoding="utf-8"))
            self.assertEqual(rassegna.carica_configurazione(config)["testata"], "Il mio giornale")
            self.assertIn('20 5 * * 1,3', workflow.read_text(encoding="utf-8"))
            self.assertIn('20 6 * * 1,3', workflow.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
