import unittest
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

import rassegna
from rassegna import Articolo, classifica, cron_programmazione, invio_programmato, sommario_feed


class ProgrammazioneTest(unittest.TestCase):
    def test_cron_italia_include_ora_legale_e_solare(self):
        cron = cron_programmazione(["lunedi"], "06:45", "Europe/Rome")
        self.assertEqual(cron, ["45 4 * * 1", "45 5 * * 1"])

    def test_ora_locale_e_giorno_scelto_determinano_l_invio(self):
        cfg = {"giorni_invio": ["lunedi"], "ora_invio": "06:45"}
        zona = ZoneInfo("Europe/Rome")
        self.assertTrue(invio_programmato(datetime(2026, 10, 26, 6, 52, tzinfo=zona), cfg))
        self.assertTrue(invio_programmato(datetime(2026, 10, 26, 7, 15, tzinfo=zona), cfg))
        self.assertFalse(invio_programmato(datetime(2026, 10, 26, 7, 30, tzinfo=zona), cfg))
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
        self.assertGreater(len(estratto), 600)
        self.assertLessEqual(len(estratto), 1800)
        self.assertNotIn("<p>", estratto)

    def test_estratto_preserva_i_paragrafi_rss(self):
        self.assertEqual(
            rassegna.pulisci_html("<p>Primo fatto.</p><p>Il contesto segue.</p>"),
            "Primo fatto.\n\nIl contesto segue.",
        )

    def test_feed_ignora_articoli_senza_estratto(self):
        adesso = datetime.now(timezone.utc)
        voci = [
            {
                "title": "Solo un titolo",
                "link": "https://example.com/senza-estratto",
                "published_parsed": adesso.timetuple(),
            },
            {
                "title": "Solo un titolo ripetuto",
                "link": "https://example.com/titolo-ripetuto",
                "published_parsed": adesso.timetuple(),
                "summary": "Solo un titolo ripetuto",
            },
            {
                "title": "Articolo con dettagli",
                "link": "https://example.com/con-estratto",
                "published_parsed": adesso.timetuple(),
                "summary": "Il feed descrive i fatti e spiega cosa succede dopo.",
            },
        ]
        with TemporaryDirectory() as directory:
            feed = Path(directory) / "feed.xml"
            feed.write_text("<rss/>", encoding="utf-8")
            with patch.object(
                rassegna.feedparser, "parse", return_value=SimpleNamespace(entries=voci)
            ):
                articoli = rassegna.leggi_feed(
                    {"nome": "Test", "file_demo": "feed.xml"}, adesso - timedelta(days=1), Path(directory)
                )
        self.assertEqual([articolo.titolo for articolo in articoli], ["Articolo con dettagli"])

    def test_argomenti_personali_escludono_le_notizie_fuori_tema(self):
        articoli = [
            Articolo("Attacco ransomware", "", "Servizi interrotti", "Fonte", "", datetime.now(timezone.utc)),
            Articolo("Elezioni comunali", "", "Nuova giunta", "Fonte", "", datetime.now(timezone.utc)),
        ]
        sezioni = [{"id": "cyber", "nome": "Cybersecurity", "parole_chiave": ["ransomware"]}]
        risultato = classifica(articoli, sezioni, filtra_argomenti=True)
        self.assertEqual([a.titolo for a in risultato], ["Attacco ransomware"])
        self.assertEqual(risultato[0].nome_sezione, "Cybersecurity")

    def test_articoli_senza_parole_chiave_restano_nella_sezione_della_fonte(self):
        articolo = Articolo(
            "Notizia internazionale",
            "",
            "Un aggiornamento generale.",
            "Fonte",
            "",
            datetime.now(timezone.utc),
            sezione="esteri",
        )
        sezioni = [
            {"id": "cyber", "nome": "Cybersecurity", "parole_chiave": ["ransomware"]},
            {"id": "esteri", "nome": "Esteri", "parole_chiave": []},
        ]
        risultato = classifica([articolo], sezioni)
        self.assertEqual(risultato[0].sezione, "esteri")
        self.assertEqual(risultato[0].nome_sezione, "Esteri")

    def test_template_email_mostra_estratti_fonti_e_link_originali(self):
        articolo = Articolo(
            "Notizia di prova",
            "https://example.com/articolo",
            "Estratto completo pubblicato dal feed.",
            "Fonte di prova",
            "Testata indipendente",
            datetime.now(timezone.utc),
            sezione="cyber",
            nome_sezione="Cybersecurity",
        )
        env = Environment(
            loader=FileSystemLoader(rassegna.QUI / "templates"),
            autoescape=select_autoescape(["html", "j2"]),
        )
        html_email = env.get_template("email.html.j2").render(
            demo=False,
            testata="Il mio giornale",
            data_breve="giovedì 22 ottobre 2026",
            numero=295,
            sottotitolo="Cybersecurity",
            data="GIOVEDÌ 22 OTTOBRE 2026",
            prima=[articolo],
            sezioni=[],
            in_breve=[],
            accadde_oggi=[],
        )
        self.assertIn("Notizia di prova", html_email)
        self.assertIn("Estratto completo pubblicato dal feed.", html_email)
        self.assertIn("Fonte: Fonte di prova", html_email)
        self.assertIn("https://example.com/articolo", html_email)
        self.assertIn("Leggi alla fonte originale", html_email)

    def test_invio_email_costruisce_messaggio_e_usa_tls(self):
        ambiente = {
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "app-password",
            "MAIL_TO": "first@example.com, second@example.com",
        }
        with patch.dict(os.environ, ambiente, clear=True), patch.object(
            rassegna.smtplib, "SMTP_SSL"
        ) as smtp_ssl:
            sessione = smtp_ssl.return_value.__enter__.return_value
            rassegna.invia("Edizione di prova", "<p>HTML</p>", "Testo")

        smtp_ssl.assert_called_once()
        sessione.login.assert_called_once_with("sender@example.com", "app-password")
        messaggio = sessione.send_message.call_args.args[0]
        self.assertEqual(messaggio["From"], "sender@example.com")
        self.assertEqual(messaggio["To"], "sender@example.com")
        self.assertEqual(messaggio["Bcc"], "first@example.com, second@example.com")
        self.assertEqual(messaggio.get_body(preferencelist=("plain",)).get_content(), "Testo\n")
        self.assertEqual(messaggio.get_body(preferencelist=("html",)).get_content(), "<p>HTML</p>\n")

    def test_invio_email_usa_starttls_su_porta_alternativa(self):
        ambiente = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "app-password",
        }
        with patch.dict(os.environ, ambiente, clear=True), patch.object(
            rassegna.smtplib, "SMTP"
        ) as smtp:
            sessione = smtp.return_value.__enter__.return_value
            rassegna.invia("Edizione di prova", "<p>HTML</p>", "Testo")

        smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
        sessione.starttls.assert_called_once()
        sessione.login.assert_called_once_with("sender@example.com", "app-password")
        sessione.send_message.assert_called_once()

    def test_configurazione_guidata_salva_preferenze_e_tutela_email(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text(yaml.safe_dump({
                "testata": "Personal Digest Mail",
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
            self.assertTrue(preferenze["filtra_argomenti"])
            self.assertNotIn("persona@example.com", (root / "preferenze.yaml").read_text(encoding="utf-8"))
            self.assertIn("MAIL_TO=persona@example.com", (root / ".env").read_text(encoding="utf-8"))
            self.assertEqual(rassegna.carica_configurazione(config)["testata"], "Il mio giornale")
            self.assertIn('20 5 * * 1,3', workflow.read_text(encoding="utf-8"))
            self.assertIn('20 6 * * 1,3', workflow.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
