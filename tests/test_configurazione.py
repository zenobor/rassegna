import smtplib
import unittest
from unittest.mock import MagicMock, patch

import configurazione
import rassegna

CONFIG = rassegna.QUI / "config.yaml"


def gh_finto(secret=frozenset(), preferenze="giorni: Tutti i giorni\nora: '09:00'\n"):
    gh = MagicMock()
    gh.accedi.return_value = "mario"
    gh.prepara_copia.return_value = "mario/rassegna"
    gh.leggi_preferenze.return_value = (preferenze, "sha123")
    gh.secret_presenti.return_value = set(secret)
    gh.invia_prova.return_value = ""
    return gh


def avvia_con(risposte, gh, password="abcd efgh ijkl mnop", verifica=None):
    with patch.object(configurazione, "installa_gh", return_value="gh"), \
            patch.object(configurazione, "GitHub", return_value=gh), \
            patch.object(configurazione, "verifica_email", return_value=verifica), \
            patch("builtins.input", side_effect=risposte), \
            patch.object(configurazione.getpass, "getpass", return_value=password), \
            patch("builtins.print"):
        return configurazione.avvia(CONFIG)


class ConfigurazioneGuidataTest(unittest.TestCase):
    def test_prima_configurazione_imposta_tutto(self):
        gh = gh_finto()
        risposte = [
            "mario@gmail.com",   # email
            "",                  # destinatari: lui stesso
            "1, 7",              # Politica e Sport
            "1",                 # dal lunedì al venerdì
            "3",                 # 07:00
            "",                  # rassegna di prova: sì
        ]
        self.assertEqual(avvia_con(risposte, gh), 0)

        secret = {c.args[1]: c.args[2] for c in gh.salva_secret.call_args_list}
        self.assertEqual(secret, {"SMTP_USER": "mario@gmail.com",
                                  "SMTP_PASSWORD": "abcdefghijklmnop",   # senza spazi
                                  "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "465",
                                  "MAIL_TO": "mario@gmail.com"})
        repo, testo, sha = gh.scrivi_preferenze.call_args.args
        self.assertEqual((repo, sha), ("mario/rassegna", "sha123"))
        self.assertIn("ora: 07:00", testo)
        self.assertIn("- sport", testo)
        gh.attiva_automazioni.assert_called_once_with("mario/rassegna")
        gh.invia_prova.assert_called_once_with("mario/rassegna")

    def test_ripetendola_tiene_email_e_propone_le_scelte_salvate(self):
        gh = gh_finto(secret={"SMTP_USER", "SMTP_PASSWORD"},
                      preferenze=rassegna.testo_preferenze("Tutti i giorni", "09:00", ["sport"]))
        risposte = ["", "", "", "", "n"]   # tiene email, argomenti, giorni, ora; niente prova
        self.assertEqual(avvia_con(risposte, gh), 0)
        gh.salva_secret.assert_not_called()
        gh.scrivi_preferenze.assert_not_called()   # nulla è cambiato
        gh.invia_prova.assert_not_called()

    def test_password_sbagliata_viene_richiesta_di_nuovo(self):
        with patch.object(configurazione, "verifica_email",
                          side_effect=["Email o password non accettate dal server.", None]), \
                patch("builtins.input", side_effect=["mario@gmail.com", "mario@gmail.com"]), \
                patch.object(configurazione.getpass, "getpass", side_effect=["sbagliata", "giusta"]), \
                patch("builtins.print"):
            email = configurazione.chiedi_email()
        self.assertEqual(email["SMTP_PASSWORD"], "giusta")

    def test_provider_sconosciuto_chiede_il_server(self):
        with patch.object(configurazione, "verifica_email", return_value=None) as verifica, \
                patch("builtins.input", side_effect=["io@azienda.it", "smtp.azienda.it", "587"]), \
                patch.object(configurazione.getpass, "getpass", return_value="segreta"), \
                patch("builtins.print"):
            email = configurazione.chiedi_email()
        verifica.assert_called_once_with("smtp.azienda.it", 587, "io@azienda.it", "segreta")
        self.assertEqual(email["SMTP_PORT"], "587")

    def test_prova_fallita_restituisce_errore(self):
        gh = gh_finto(secret={"SMTP_USER", "SMTP_PASSWORD"})
        gh.invia_prova.return_value = "Mancano SMTP_USER"
        self.assertEqual(avvia_con(["", "", "", "", ""], gh), 1)

    def test_errore_github_si_ferma_con_un_messaggio(self):
        gh = gh_finto()
        gh.accedi.side_effect = configurazione.ErroreConfigurazione("Accesso non completato.")
        self.assertEqual(avvia_con([], gh), 1)

    def test_ctrl_c_interrompe_senza_traceback(self):
        gh = gh_finto()
        with patch.object(configurazione, "installa_gh", return_value="gh"), \
                patch.object(configurazione, "GitHub", return_value=gh), \
                patch("builtins.input", side_effect=KeyboardInterrupt), \
                patch("builtins.print"):
            self.assertEqual(configurazione.avvia(CONFIG), 1)

    def test_destinatari_non_validi_vengono_richiesti(self):
        with patch("builtins.input", side_effect=["non-un-indirizzo", "a@x.it, b@y.com"]), \
                patch("builtins.print"):
            self.assertEqual(configurazione.chiedi_destinatari("io@x.it"), "a@x.it, b@y.com")

    def test_preferenze_salvate_illeggibili_usano_quelle_predefinite(self):
        cfg = rassegna.carica_configurazione(CONFIG)
        self.assertIs(configurazione.preferenze_attuali("ora: 25:00", cfg), cfg)
        self.assertIs(configurazione.preferenze_attuali(": : :", cfg), cfg)

    def test_verifica_email_traduce_gli_errori(self):
        with patch.object(configurazione.smtplib, "SMTP_SSL") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = \
                smtplib.SMTPAuthenticationError(535, b"no")
            self.assertIn("non accettate",
                          configurazione.verifica_email("smtp.gmail.com", 465, "a@b.it", "x"))
        with patch.object(configurazione.smtplib, "SMTP_SSL"):
            self.assertIsNone(configurazione.verifica_email("smtp.gmail.com", 465, "a@b.it", "x"))

    def test_senza_argomenti_parte_la_configurazione_guidata(self):
        with patch("sys.argv", ["rassegna.py"]), \
                patch.object(configurazione, "avvia", return_value=0) as avvia:
            self.assertEqual(rassegna.main(), 0)
        avvia.assert_called_once()


if __name__ == "__main__":
    unittest.main()
