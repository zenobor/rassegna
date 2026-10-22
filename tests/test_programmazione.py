import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import rassegna
from rassegna import Articolo, classifica, invio_programmato, sommario_feed

CATALOGO = [
    {"id": "politica", "nome": "Politica", "parole_chiave": ["governo"]},
    {"id": "tecnologia", "nome": "Tecnologia", "parole_chiave": ["ransomware"]},
    {"id": "sport", "nome": "Sport", "parole_chiave": ["calcio"]},
]


def articolo(titolo="Notizia", sommario="Testo.", **altro):
    valori = dict(link="https://example.com/" + titolo.replace(" ", "-"), fonte="Fonte",
                  scheda="", data=datetime(2026, 10, 22, 8, tzinfo=timezone.utc))
    valori.update(altro)
    return Articolo(titolo, valori.pop("link"), sommario, valori.pop("fonte"),
                    valori.pop("scheda"), valori.pop("data"), **valori)


def cartella_config(directory: str, preferenze: dict | None = None) -> Path:
    radice = Path(directory)
    config = radice / "config.yaml"
    config.write_text(yaml.safe_dump({"catalogo_argomenti": CATALOGO, "fonti": []},
                                     allow_unicode=True), encoding="utf-8")
    if preferenze is not None:
        (radice / "preferenze.yaml").write_text(
            yaml.safe_dump(preferenze, allow_unicode=True), encoding="utf-8")
    return config


class ProgrammazioneTest(unittest.TestCase):
    cfg = {"giorni": "Dal lunedì al venerdì", "ora": "07:00"}

    def test_invia_solo_nell_ora_scelta_con_ora_legale_e_solare(self):
        estate = datetime(2026, 7, 13, 5, 0, tzinfo=timezone.utc)    # lunedì, 07:00 a Roma
        inverno = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)   # lunedì, 07:00 a Roma
        self.assertTrue(invio_programmato(self.cfg, estate, "55 4 * * *"))
        self.assertFalse(invio_programmato(self.cfg, estate, "55 5 * * *"))
        self.assertTrue(invio_programmato(self.cfg, inverno, "55 5 * * *"))
        self.assertFalse(invio_programmato(self.cfg, inverno, "55 4 * * *"))

    def test_i_ritardi_di_github_non_fanno_perdere_l_edizione(self):
        in_ritardo = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)  # 3 ore e mezza dopo
        self.assertTrue(invio_programmato(self.cfg, in_ritardo, "55 5 * * *"))

    def test_rispetta_i_giorni_scelti(self):
        sabato = datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)
        self.assertFalse(invio_programmato(self.cfg, sabato, "55 5 * * *"))
        weekend = {"giorni": "Solo sabato e domenica", "ora": "07:00"}
        self.assertTrue(invio_programmato(weekend, sabato, "55 5 * * *"))

    def test_le_cron_del_workflow_coprono_tutti_gli_orari(self):
        workflow = (rassegna.QUI / ".github/workflows/rassegna.yml").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'cron: "([^"]+)"', workflow), rassegna.cron_orari())
        for mese in (1, 7):
            for orario in rassegna.ORARI:
                cfg = {"giorni": "Tutti i giorni", "ora": orario}
                locale = datetime(2026, mese, 15, int(orario[:2]), tzinfo=rassegna.FUSO)
                partenze = [c for c in rassegna.cron_orari()
                            if invio_programmato(cfg, locale.astimezone(timezone.utc), c)]
                self.assertEqual(len(partenze), 1, f"{orario} nel mese {mese}")

    def test_il_modulo_github_offre_le_stesse_scelte_del_programma(self):
        modulo = yaml.safe_load(
            (rassegna.QUI / ".github/workflows/configura.yml").read_text(encoding="utf-8")
        )
        campi = modulo[True]["workflow_dispatch"]["inputs"]  # YAML legge "on" come True
        catalogo = rassegna.carica_configurazione(rassegna.QUI / "config.yaml")["catalogo_argomenti"]
        self.assertEqual(campi["giorni"]["options"], list(rassegna.OPZIONI_GIORNI))
        self.assertEqual(campi["ora"]["options"], rassegna.ORARI)
        self.assertEqual(
            [(k, v["description"]) for k, v in campi.items() if v["type"] == "boolean"],
            [(a["id"], a["nome"]) for a in catalogo],
        )
        self.assertLessEqual(len(campi), 10)  # limite di GitHub per i moduli


class PreferenzeTest(unittest.TestCase):
    def test_preferenze_dal_modulo_github(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory)
            modulo = {"giorni": "Tutti i giorni", "ora": "08:00",
                      "politica": True, "tecnologia": "true", "sport": False}
            self.assertEqual(rassegna.preferenze_da_modulo(config, modulo), 0)
            cfg = rassegna.carica_configurazione(config)
        self.assertEqual(cfg["giorni"], "Tutti i giorni")
        self.assertEqual(cfg["ora"], "08:00")
        self.assertEqual(cfg["argomenti"], ["politica", "tecnologia"])

    def test_il_modulo_senza_argomenti_non_salva_nulla(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory)
            modulo = {"giorni": "Tutti i giorni", "ora": "08:00", "politica": False}
            with self.assertLogs("rassegna", "ERROR"):
                self.assertEqual(rassegna.preferenze_da_modulo(config, modulo), 1)
            self.assertFalse((Path(directory) / "preferenze.yaml").exists())

    def test_configurazione_guidata_con_liste_numerate(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory)
            risposte = ["3, 1", "3", "4"]  # Sport e Politica, weekend, 08:00
            with patch("builtins.input", side_effect=risposte), patch("builtins.print"):
                self.assertEqual(rassegna.configura(config), 0)
            cfg = rassegna.carica_configurazione(config)
        self.assertEqual(cfg["argomenti"], ["politica", "sport"])
        self.assertEqual(cfg["giorni"], "Solo sabato e domenica")
        self.assertEqual(cfg["ora"], "08:00")

    def test_configurazione_guidata_ripropone_le_scelte_se_errate(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory)
            risposte = ["9", "", "", "99", ""]
            with patch("builtins.input", side_effect=risposte), patch("builtins.print"):
                rassegna.configura(config)
            cfg = rassegna.carica_configurazione(config)
        self.assertEqual(cfg["argomenti"], ["politica", "tecnologia", "sport"])
        self.assertEqual(cfg["ora"], "07:00")

    def test_preferenze_scritte_a_mano_vengono_controllate(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory, {"ora": "07:30"})
            with self.assertRaisesRegex(ValueError, "ora"):
                rassegna.carica_configurazione(config)
        with TemporaryDirectory() as directory:
            config = cartella_config(directory, {"argomenti": ["meteo"]})
            with self.assertRaisesRegex(ValueError, "argomento"):
                rassegna.carica_configurazione(config)

    def test_ora_senza_virgolette_e_accettata(self):
        with TemporaryDirectory() as directory:
            config = cartella_config(directory)
            (Path(directory) / "preferenze.yaml").write_text("ora: 10:00\n", encoding="utf-8")
            self.assertEqual(rassegna.carica_configurazione(config)["ora"], "10:00")

    def test_configurazione_del_repository_e_valida(self):
        cfg = rassegna.carica_configurazione(rassegna.QUI / "config.yaml")
        ids = {a["id"] for a in cfg["catalogo_argomenti"]}
        for fonte in cfg["fonti"]:
            self.assertIn(fonte["argomento"], ids | {"generale"}, fonte["nome"])
            self.assertTrue(fonte["url"].startswith("https://"), fonte["nome"])
            self.assertLessEqual(len(fonte["scheda"].split()), 6, fonte["nome"])
        coperti = {f["argomento"] for f in cfg["fonti"]}
        self.assertEqual(ids - coperti, set(), "ogni argomento ha almeno un feed tematico")


class NotizieTest(unittest.TestCase):
    def test_estratto_usa_il_sommario_rss_completo_senza_limite_fisso(self):
        dettagli = "La testata spiega i fatti, il contesto e le conseguenze. " * 45
        voce = {
            "summary": "<p>Estratto breve.</p>",
            "description": "<p>" + dettagli + "</p>",
            "content": [{"value": "<p>Corpo completo non incluso nel digest.</p>"}],
        }
        estratto = sommario_feed(voce)
        self.assertEqual(estratto, dettagli.strip())
        self.assertNotIn("Corpo completo", estratto)

    def test_estratto_preserva_i_paragrafi_rss(self):
        self.assertEqual(
            rassegna.pulisci_html("<p>Primo fatto.</p><p>Il contesto segue.</p>"),
            "Primo fatto.\n\nIl contesto segue.",
        )

    def test_date_rss_in_italiano(self):
        voce = rassegna.feedparser.parse(
            b"<rss><channel><item><title>x</title>"
            b"<pubDate>gio, 22 ott 2026 17:24:57 GMT</pubDate></item></channel></rss>"
        ).entries[0]
        self.assertEqual(tuple(voce.published_parsed[:6]), (2026, 10, 22, 17, 24, 57))

    def test_feed_ignora_articoli_senza_estratto(self):
        adesso = datetime.now(timezone.utc)
        voci = [
            {"title": "Solo un titolo", "link": "https://example.com/a",
             "published_parsed": adesso.timetuple()},
            {"title": "Titolo ripetuto", "link": "https://example.com/b",
             "published_parsed": adesso.timetuple(), "summary": "Titolo ripetuto"},
            {"title": "Articolo con dettagli", "link": "https://example.com/c",
             "published_parsed": adesso.timetuple(),
             "summary": "Il feed descrive i fatti e spiega cosa succede dopo."},
        ]
        with TemporaryDirectory() as directory:
            (Path(directory) / "feed.xml").write_text("<rss/>", encoding="utf-8")
            with patch.object(rassegna.feedparser, "parse",
                              return_value=SimpleNamespace(entries=voci, feed={})):
                articoli = rassegna.leggi_feed(
                    {"nome": "Test", "file_demo": "feed.xml", "argomento": "sport", "priorita": 5},
                    adesso - timedelta(days=1),
                    Path(directory),
                )
        self.assertEqual([a.titolo for a in articoli], ["Articolo con dettagli"])
        self.assertEqual(articoli[0].sezione, "sport")
        self.assertEqual(articoli[0].priorita, 5)

    def test_immagini_sono_accettate_solo_se_https(self):
        self.assertTrue(rassegna._url_immagine_valido("https://cdn.example.com/photo.jpg"))
        self.assertFalse(rassegna._url_immagine_valido("http://example.com/photo.jpg"))
        self.assertFalse(rassegna._url_immagine_valido("javascript:alert(1)"))

    def test_classifica_tiene_solo_gli_argomenti_scelti(self):
        notizie = [
            articolo("Il governo approva il decreto", sezione="generale"),
            articolo("Attacco ransomware a un ospedale", sezione="generale"),
            articolo("Notizia senza parole chiave", sezione="generale"),
            articolo("Il governo e lo sport", sezione="sport"),  # feed tematico
            articolo("Calcio, risultati", sezione="sport"),
        ]
        scelti = classifica(notizie, CATALOGO, ["politica", "tecnologia"])
        self.assertEqual(
            [(a.titolo, a.nome_sezione) for a in scelti],
            [("Il governo approva il decreto", "Politica"),
             ("Attacco ransomware a un ospedale", "Tecnologia")],
        )

    def test_doppioni_tengono_il_riassunto_migliore_e_citano_le_altre_fonti(self):
        breve = articolo("Attacco hacker colpisce una grande azienda", "Una riga.",
                         fonte="Agenzia", priorita=1)
        ricco = articolo("Attacco hacker colpisce una grande azienda", "Spiegazione. " * 20,
                         fonte="Quotidiano", priorita=2, link="https://quotidiano.example/a")
        raggruppati = rassegna.raggruppa_doppioni([breve, ricco])
        self.assertEqual(len(raggruppati), 1)
        self.assertIs(raggruppati[0], ricco)
        self.assertEqual([f["nome"] for f in raggruppati[0].altre_fonti], ["Agenzia"])


class ImpaginazioneTest(unittest.TestCase):
    cfg = {"catalogo_argomenti": CATALOGO, "argomenti": ["tecnologia", "politica"],
           "max_prima_pagina": 1}

    def test_prima_pagina_e_sezioni_seguono_gli_argomenti_scelti(self):
        condivisa = articolo("Ripresa da più fonti", sezione="tecnologia", nome_sezione="Tecnologia",
                             altre_fonti=[{"nome": "Altra", "link": "https://x.example", "scheda": ""}])
        politica = articolo("Notizia politica", sezione="politica", nome_sezione="Politica",
                            priorita=0)
        pagina = rassegna.impagina(self.cfg, [politica, condivisa],
                                   datetime(2026, 10, 22, tzinfo=rassegna.FUSO))
        self.assertEqual([a.titolo for a in pagina["prima"]], ["Ripresa da più fonti"])
        self.assertEqual([s["nome"] for s in pagina["sezioni"]], ["Politica"])
        self.assertEqual(pagina["sottotitolo"], "Politica · Tecnologia")
        self.assertEqual(pagina["data_breve"], "giovedì 22 ottobre 2026")

    def test_template_email_mostra_estratti_fonti_e_link_originali(self):
        notizia = articolo(
            "Notizia di prova", "Estratto completo pubblicato dal feed.",
            fonte="Fonte di prova", scheda="Testata indipendente",
            sezione="tecnologia", nome_sezione="Tecnologia",
            altre_fonti=[{"nome": "Seconda fonte", "link": "https://second.example/story",
                          "scheda": "Agenzia pubblica"}],
        )
        pagina = rassegna.impagina(self.cfg, [notizia], datetime(2026, 10, 22, tzinfo=rassegna.FUSO))
        pagina["in_breve"] = [notizia]
        html_email = rassegna.ambiente_template().get_template("email.html.j2").render(**pagina)
        self.assertGreaterEqual(html_email.count("Estratto completo pubblicato dal feed."), 2)
        self.assertIn('Fonte: <a href="https://example.com/Notizia-di-prova"', html_email)
        self.assertIn('href="https://second.example/story"', html_email)
        self.assertIn("Leggi alla fonte originale", html_email)
        self.assertIn("Anno 2026", html_email)
        self.assertIn("PRIMA PAGINA", rassegna.testo_semplice(pagina))


class InvioTest(unittest.TestCase):
    def test_invio_email_costruisce_messaggio_e_usa_tls(self):
        ambiente = {
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "app-password",
            "MAIL_TO": "first@example.com, second@example.com",
            "SMTP_HOST": "",  # un secret vuoto su GitHub vale come non impostato
        }
        with patch.dict(os.environ, ambiente, clear=True), patch.object(
            rassegna.smtplib, "SMTP_SSL"
        ) as smtp_ssl:
            sessione = smtp_ssl.return_value.__enter__.return_value
            rassegna.invia("Edizione di prova", "<p>HTML</p>", "Testo")

        self.assertEqual(smtp_ssl.call_args.args[:2], ("smtp.gmail.com", 465))
        sessione.login.assert_called_once_with("sender@example.com", "app-password")
        messaggio = sessione.send_message.call_args.args[0]
        self.assertEqual(messaggio["To"], "sender@example.com")
        self.assertEqual(messaggio["Bcc"], "first@example.com, second@example.com")
        self.assertEqual(messaggio.get_body(preferencelist=("plain",)).get_content(), "Testo\n")
        self.assertEqual(messaggio.get_body(preferencelist=("html",)).get_content(), "<p>HTML</p>\n")

    def test_invio_email_usa_starttls_su_porta_alternativa(self):
        ambiente = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
                    "SMTP_USER": "sender@example.com", "SMTP_PASSWORD": "app-password"}
        with patch.dict(os.environ, ambiente, clear=True), patch.object(
            rassegna.smtplib, "SMTP"
        ) as smtp:
            sessione = smtp.return_value.__enter__.return_value
            rassegna.invia("Edizione di prova", "<p>HTML</p>", "Testo")
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
        sessione.starttls.assert_called_once()
        sessione.send_message.assert_called_once()

    def test_senza_credenziali_si_ferma_subito_con_un_messaggio_chiaro(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            rassegna, "carica_env"
        ), patch.object(rassegna, "leggi_feed") as leggi, patch(
            "sys.argv", ["rassegna.py", "--invia"]
        ), self.assertLogs("rassegna", "ERROR") as registro:
            self.assertEqual(rassegna.main(), 1)
        leggi.assert_not_called()
        self.assertIn("Secrets", registro.output[0])


if __name__ == "__main__":
    unittest.main()
