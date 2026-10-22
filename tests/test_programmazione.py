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

    def test_estratto_usa_il_sommario_rss_completo_senza_limite_fisso(self):
        dettagli = "La testata spiega i fatti, il contesto e le conseguenze. " * 45
        voce = {
            "summary": "<p>Estratto breve.</p>",
            "description": "<p>" + dettagli + "</p>",
            "content": [{"value": "<p>Corpo completo non incluso nel digest.</p>"}],
        }
        estratto = sommario_feed(voce)
        self.assertEqual(estratto, dettagli.strip())
        self.assertGreater(len(estratto), 1800)
        self.assertNotIn("<p>", estratto)
        self.assertNotIn("Corpo completo", estratto)

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
                rassegna.feedparser,
                "parse",
                return_value=SimpleNamespace(entries=voci, feed={}),
            ):
                articoli = rassegna.leggi_feed(
                    {
                        "nome": "Test",
                        "file_demo": "feed.xml",
                        "lingua": "it",
                        "priorita": 5,
                    },
                    adesso - timedelta(days=1),
                    Path(directory),
                )
        self.assertEqual([articolo.titolo for articolo in articoli], ["Articolo con dettagli"])
        self.assertEqual(articoli[0].lingua, "it")
        self.assertEqual(articoli[0].priorita, 5)

    def test_immagini_sono_accettate_solo_se_https(self):
        self.assertTrue(rassegna._url_immagine_valido("https://cdn.example.com/photo.jpg"))
        self.assertFalse(rassegna._url_immagine_valido("http://example.com/photo.jpg"))
        self.assertFalse(rassegna._url_immagine_valido("javascript:alert(1)"))

    def test_lingua_scelta_traduce_gli_articoli_stranieri_e_conserva_gli_sconosciuti(self):
        articoli = [
            Articolo("Notizia italiana", "", "Testo", "Fonte", "", datetime.now(timezone.utc), lingua="it"),
            Articolo("English story", "", "Text", "Source", "", datetime.now(timezone.utc), lingua="en"),
            Articolo("Lingua non dichiarata", "", "Testo", "Fonte", "", datetime.now(timezone.utc)),
        ]
        self.assertEqual(rassegna.traduci_articoli(articoli, "tutte"), articoli)
        with patch.dict(os.environ, {"DEEPL_API_KEY": "test-key"}, clear=True), patch.object(
            rassegna.requests, "post",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"translations": [
                    {"text": "Translated Italian story"},
                    {"text": "Translated Italian summary"},
                ]},
            ),
        ) as post:
            risultato = rassegna.traduci_articoli(articoli, "EN-us")
        self.assertEqual(
            [a.titolo for a in risultato],
            ["Translated Italian story", "English story", "Lingua non dichiarata"],
        )
        self.assertEqual(risultato[0].sommario, "Translated Italian summary")
        self.assertEqual(risultato[0].tradotto_da, "it")
        self.assertEqual(risultato[1].lingua, "en")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "https://api.deepl.com/v2/translate")
        self.assertEqual(post.call_args.kwargs["data"]["target_lang"], "EN")
        self.assertEqual(post.call_args.kwargs["data"]["text"], ["Notizia italiana", "Testo"])

    def test_traduzione_necessita_chiave_deepl_per_articoli_stranieri(self):
        articolo = Articolo(
            "English story", "", "Text", "Source", "", datetime.now(timezone.utc), lingua="en"
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DEEPL_API_KEY"):
                rassegna.traduci_articoli([articolo], "it")

    def test_lingua_dichiarata_nell_articolo_prevale_su_quella_del_feed(self):
        self.assertEqual(
            rassegna.lingua_articolo(
                {"language": "EN-us"},
                {"language": "it"},
                {"lingua": "it"},
            ),
            "en",
        )

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

    def test_doppioni_preferiscono_articolo_originale_e_linkano_le_altre_fonti(self):
        data = datetime.now(timezone.utc)
        tradotto = Articolo(
            "Cyber attack hits major company",
            "https://translated.example/story",
            "Translated summary.",
            "Fonte estera",
            "Testata specializzata",
            data,
            lingua="it",
            tradotto_da="en",
        )
        originale = Articolo(
            "Cyber attack hits major company",
            "https://original.example/story",
            "Original summary.",
            "Fonte originale",
            "Agenzia ufficiale",
            data,
            lingua="it",
        )
        raggruppati = rassegna.raggruppa_doppioni([tradotto, originale])
        self.assertEqual(len(raggruppati), 1)
        self.assertIs(raggruppati[0], originale)
        self.assertEqual(
            raggruppati[0].altre_fonti,
            [{
                "nome": "Fonte estera",
                "link": "https://translated.example/story",
                "scheda": "Testata specializzata",
            }],
        )

    def test_configurazione_sezioni_rispetta_ordine_e_sezioni_brevi(self):
        cfg = rassegna.carica_configurazione(rassegna.QUI / "config.yaml")
        ids = [sezione["id"] for sezione in cfg["sezioni"]]
        self.assertEqual(
            ids,
            [
                "politica", "intelligence", "terrorismo", "geopolitica", "ibrida",
                "cyber", "tecnologia", "esteri", "economia", "scienza", "cultura",
            ],
        )
        self.assertEqual(cfg["max_in_breve"], 8)
        self.assertTrue(all(len(fonte["scheda"].split()) <= 6 for fonte in cfg["fonti"]))

    def test_impaginazione_mettere_in_evidenza_le_notizie_riprese_da_piu_fonti(self):
        data = datetime.now(timezone.utc)
        notizia_condivisa = Articolo(
            "Story reported by several outlets",
            "https://news.example/shared",
            "Shared summary.",
            "Quotidiano",
            "",
            data,
            sezione="cyber",
            altre_fonti=[{
                "nome": "Agenzia",
                "link": "https://news.example/agency",
                "scheda": "",
            }],
        )
        notizia_ufficiale = Articolo(
            "Official advisory",
            "https://official.example/advisory",
            "Official summary.",
            "Agenzia ufficiale",
            "",
            data,
            sezione="cyber",
            priorita=0,
        )
        pagina = rassegna.impagina(
            {
                "sezioni": [{"id": "cyber", "nome": "Cyber", "max_articoli": 2}],
                "max_prima_pagina": 2,
                "fonti": [],
            },
            [notizia_ufficiale, notizia_condivisa],
            data,
        )
        self.assertEqual(
            [articolo.titolo for articolo in pagina["prima"]],
            ["Story reported by several outlets", "Official advisory"],
        )

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
            altre_fonti=[{
                "nome": "Seconda fonte",
                "link": "https://second.example/story",
                "scheda": "Agenzia pubblica",
            }],
            tradotto_da="en",
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
            in_breve=[articolo],
            accadde_oggi=[],
        )
        self.assertIn("Notizia di prova", html_email)
        self.assertIn("Estratto completo pubblicato dal feed.", html_email)
        self.assertGreaterEqual(html_email.count("Estratto completo pubblicato dal feed."), 2)
        self.assertIn('Fonte: <a href="https://example.com/articolo"', html_email)
        self.assertIn(">Fonte di prova</a>", html_email)
        self.assertIn("Tradotto con DeepL da EN.", html_email)
        self.assertIn("https://example.com/articolo", html_email)
        self.assertIn('href="https://second.example/story"', html_email)
        self.assertIn("Seconda fonte", html_email)
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
                "en",
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
            self.assertEqual(preferenze["lingua_articoli"], "en")
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
