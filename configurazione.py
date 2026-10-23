"""
La configurazione guidata: dal terminale imposta tutto quello che serve perché
la rassegna parta da sola su GitHub.

    python rassegna.py

Chiede accesso a GitHub, email, argomenti, giorni e ora; poi crea la copia del
progetto sul tuo account, attiva le automazioni, salva email e password come
Secrets cifrati e invia una rassegna di prova. Si può ripetere per cambiare idea.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import platform
import shutil
import smtplib
import ssl
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import rassegna

REPO_ORIGINALE = "zenobor/rassegna"

# Server di posta noti: (host, porta, dove creare la password per le app)
PROVIDER = {
    "gmail.com": ("smtp.gmail.com", 465, "https://myaccount.google.com/apppasswords"),
    "googlemail.com": ("smtp.gmail.com", 465, "https://myaccount.google.com/apppasswords"),
    "yahoo.com": ("smtp.mail.yahoo.com", 465, "https://login.yahoo.com/account/security"),
    "yahoo.it": ("smtp.mail.yahoo.com", 465, "https://login.yahoo.com/account/security"),
    "icloud.com": ("smtp.mail.me.com", 587, "https://account.apple.com"),
    "me.com": ("smtp.mail.me.com", 587, "https://account.apple.com"),
    "outlook.com": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "outlook.it": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "hotmail.com": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "hotmail.it": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "live.com": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "live.it": ("smtp-mail.outlook.com", 587, "https://account.microsoft.com/security"),
    "libero.it": ("smtp.libero.it", 465, None),
}

WORKFLOW_INVIO = "rassegna.yml"


class ErroreConfigurazione(Exception):
    """Un passo non è riuscito: il messaggio spiega cosa fare."""


# --------------------------------------------------------------------------- #
#  Domande
# --------------------------------------------------------------------------- #
def titolo(numero: int, testo: str) -> None:
    print(f"\n── Passo {numero} di 4 · {testo} " + "─" * max(0, 40 - len(testo)))


def ok(testo: str) -> None:
    print(f"  ✓ {testo}")


def chiedi(domanda: str, predefinito: str = "") -> str:
    suggerimento = f" [{predefinito}]" if predefinito else ""
    while True:
        risposta = input(f"{domanda}{suggerimento}: ").strip()
        if risposta or predefinito:
            return risposta or predefinito
        print("  Serve una risposta.")


def conferma(domanda: str, predefinito: bool = True) -> bool:
    scelte = "S/n" if predefinito else "s/N"
    while True:
        risposta = input(f"{domanda} [{scelte}]: ").strip().lower()
        if not risposta:
            return predefinito
        if risposta in ("s", "si", "sì", "y", "yes"):
            return True
        if risposta in ("n", "no"):
            return False
        print("  Rispondi s oppure n.")


def chiedi_destinatari(predefinito: str) -> str:
    while True:
        risposta = chiedi("Chi riceve la rassegna? (più indirizzi separati da virgola)",
                          predefinito)
        indirizzi = [d.strip() for d in risposta.split(",") if d.strip()]
        if indirizzi and all("@" in d and "." in d.split("@")[-1] for d in indirizzi):
            return ", ".join(indirizzi)
        print("  Scrivi indirizzi email validi, es. mario@gmail.com, anna@libero.it")


# --------------------------------------------------------------------------- #
#  Email
# --------------------------------------------------------------------------- #
def verifica_email(host: str, porta: int, utente: str, password: str) -> str | None:
    """Prova ad accedere al server di posta senza inviare nulla.
    Restituisce None se va bene, altrimenti un messaggio comprensibile."""
    contesto = ssl.create_default_context()
    try:
        if porta == 465:
            with smtplib.SMTP_SSL(host, porta, context=contesto, timeout=20) as s:
                s.login(utente, password)
        else:
            with smtplib.SMTP(host, porta, timeout=20) as s:
                s.starttls(context=contesto)
                s.login(utente, password)
    except smtplib.SMTPAuthenticationError:
        return "Email o password non accettate dal server."
    except (OSError, smtplib.SMTPException) as e:
        return f"Non riesco a collegarmi a {host}:{porta} ({e})."
    return None


def chiedi_email() -> dict[str, str]:
    """Chiede indirizzo e password e li verifica subito, finché funzionano."""
    while True:
        utente = chiedi("Indirizzo email che spedisce la rassegna (es. mario@gmail.com)")
        if "@" not in utente:
            print("  Non sembra un indirizzo email.")
            continue
        dominio = utente.rsplit("@", 1)[1].lower()
        if dominio in PROVIDER:
            host, porta, pagina = PROVIDER[dominio]
        else:
            print(f"  Non conosco il server di posta di {dominio}: lo trovi nelle istruzioni "
                  "del tuo provider (cerca \"SMTP\").")
            host = chiedi("Server SMTP (es. smtp.example.com)")
            porta = int(chiedi("Porta SMTP (465 o 587)", "465"))
            pagina = None

        if dominio in ("gmail.com", "googlemail.com"):
            print("\n  Serve una \"password per le app\" di Google, NON la tua password normale.")
            print("  1. Attiva la verifica in due passaggi sul tuo account Google")
            print(f"  2. Apri {pagina}")
            print("  3. Scrivi un nome (es. Rassegna), clicca Crea e copia le 16 lettere\n")
        elif pagina:
            print(f"\n  Molti provider richiedono una \"password per le app\": la crei da {pagina}\n")

        password = getpass.getpass("Password per le app (mentre scrivi non si vede nulla): ").strip()
        if dominio in ("gmail.com", "googlemail.com"):
            password = password.replace(" ", "")   # Google la mostra a gruppi di 4

        print("  Controllo l'accesso alla posta…")
        errore = verifica_email(host, porta, utente, password)
        if not errore:
            ok("Email verificata")
            return {"SMTP_USER": utente, "SMTP_PASSWORD": password,
                    "SMTP_HOST": host, "SMTP_PORT": str(porta)}
        print(f"  ✗ {errore}")
        if dominio in ("gmail.com", "googlemail.com"):
            print("    Controlla di aver usato la password per le app (16 lettere), "
                  "non quella normale.")
        print("  Riproviamo.\n")


# --------------------------------------------------------------------------- #
#  GitHub (tramite la GitHub CLI, "gh")
# --------------------------------------------------------------------------- #
def trova_gh() -> str | None:
    percorso = shutil.which("gh")
    if percorso:
        return percorso
    for candidato in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
                      Path("/opt/homebrew/bin/gh"), Path("/usr/local/bin/gh")):
        if candidato.exists():
            return str(candidato)
    return None


def installa_gh() -> str:
    """Trova la GitHub CLI o si offre di installarla."""
    gh = trova_gh()
    if gh:
        return gh
    sistema = platform.system()
    comando = None
    if sistema == "Windows" and shutil.which("winget"):
        comando = ["winget", "install", "--id", "GitHub.cli", "-e", "--source", "winget",
                   "--accept-package-agreements", "--accept-source-agreements"]
    elif sistema == "Darwin" and shutil.which("brew"):
        comando = ["brew", "install", "gh"]

    print("  Per collegarmi al tuo account GitHub serve un piccolo programma ufficiale, "
          "la GitHub CLI.")
    if comando and conferma("  Lo installo adesso?"):
        subprocess.run(comando)
        gh = trova_gh()
        if gh:
            ok("GitHub CLI installata")
            return gh
    raise ErroreConfigurazione(
        "Installa la GitHub CLI da https://cli.github.com, poi chiudi e riapri il terminale "
        "e rilancia: python rassegna.py")


class GitHub:
    def __init__(self, eseguibile: str):
        self.eseguibile = eseguibile

    def esegui(self, *argomenti: str, input: str | None = None, controlla: bool = True) -> str:
        r = subprocess.run([self.eseguibile, *argomenti], input=input, capture_output=True,
                           text=True, encoding="utf-8")
        if controlla and r.returncode:
            raise ErroreConfigurazione(f"GitHub ha risposto con un errore: "
                                       f"{(r.stderr or r.stdout).strip()}")
        return r.stdout.strip()

    def api(self, percorso: str, *argomenti: str, controlla: bool = True) -> str:
        return self.esegui("api", percorso, *argomenti, controlla=controlla)

    def accedi(self) -> str:
        """Fa il login se serve e restituisce il nome utente."""
        if subprocess.run([self.eseguibile, "auth", "status"], capture_output=True).returncode:
            print("  Si apre il browser: accedi a GitHub (o crea un account gratuito) e "
                  "incolla il codice che compare qui sotto.")
            r = subprocess.run([self.eseguibile, "auth", "login", "--web", "--hostname",
                                "github.com", "--git-protocol", "https"])
            if r.returncode:
                raise ErroreConfigurazione("Accesso a GitHub non completato.")
        return self.api("user", "--jq", ".login")

    def prepara_copia(self, utente: str) -> str:
        """Usa il progetto originale se è tuo, altrimenti crea (o ritrova) la tua copia."""
        if utente.lower() == REPO_ORIGINALE.split("/")[0].lower():
            return REPO_ORIGINALE
        repo = self.api(f"repos/{REPO_ORIGINALE}/forks", "-X", "POST",
                        "-F", "default_branch_only=true", "--jq", ".full_name")
        for _ in range(30):   # GitHub crea la copia in qualche secondo
            if subprocess.run([self.eseguibile, "api", f"repos/{repo}/contents/preferenze.yaml",
                               "--silent"], capture_output=True).returncode == 0:
                return repo
            time.sleep(2)
        raise ErroreConfigurazione(f"La copia {repo} non è ancora pronta: riprova tra un minuto.")

    def attiva_automazioni(self, repo: str) -> None:
        # Nelle copie GitHub tiene spente le automazioni finché non le si accende.
        self.api(f"repos/{repo}/actions/permissions", "-X", "PUT",
                 "-F", "enabled=true", "-f", "allowed_actions=all", controlla=False)
        for _ in range(30):
            righe = self.api(f"repos/{repo}/actions/workflows", "--jq",
                             '.workflows[] | "\\(.id) \\(.state)"', controlla=False)
            if righe:
                break
            time.sleep(2)
        else:
            raise ErroreConfigurazione("Non trovo le automazioni nella tua copia: "
                                       "riprova tra un minuto.")
        for riga in righe.splitlines():
            id_workflow, stato = riga.split()
            if stato != "active":
                self.api(f"repos/{repo}/actions/workflows/{id_workflow}/enable", "-X", "PUT")

    def salva_secret(self, repo: str, nome: str, valore: str) -> None:
        # Il valore passa da stdin, così non compare nella lista dei processi.
        self.esegui("secret", "set", nome, "--repo", repo, input=valore)

    def secret_presenti(self, repo: str) -> set[str]:
        testo = self.esegui("secret", "list", "--repo", repo, "--json", "name",
                            "--jq", ".[].name", controlla=False)
        return set(testo.split())

    def leggi_preferenze(self, repo: str) -> tuple[str, str]:
        """Restituisce (testo, sha) del file preferenze.yaml nella copia."""
        dati = json.loads(self.api(f"repos/{repo}/contents/preferenze.yaml"))
        return base64.b64decode(dati["content"]).decode("utf-8"), dati["sha"]

    def scrivi_preferenze(self, repo: str, testo: str, sha: str) -> None:
        contenuto = base64.b64encode(testo.encode("utf-8")).decode("ascii")
        self.api(f"repos/{repo}/contents/preferenze.yaml", "-X", "PUT",
                 "-f", "message=Aggiorna le preferenze della rassegna",
                 "-f", f"content={contenuto}", "-f", f"sha={sha}", "--silent")

    def invia_prova(self, repo: str) -> str:
        """Avvia 'Invia la rassegna', aspetta che finisca e restituisce l'esito."""
        # un minuto di margine, nel caso l'orologio del computer sia un po' avanti
        partenza = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)
        for tentativo in range(10):   # subito dopo l'attivazione può non essere pronta
            r = subprocess.run([self.eseguibile, "workflow", "run", WORKFLOW_INVIO,
                                "--repo", repo], capture_output=True, text=True)
            if not r.returncode:
                break
            time.sleep(3)
        else:
            raise ErroreConfigurazione(f"Non riesco ad avviare l'invio di prova: {r.stderr.strip()}")

        esecuzione = None
        for _ in range(20):
            elenco = json.loads(self.esegui(
                "run", "list", "--repo", repo, "--workflow", WORKFLOW_INVIO,
                "--event", "workflow_dispatch", "--limit", "5",
                "--json", "databaseId,createdAt,status,conclusion,url"))
            recenti = [e for e in elenco if e["createdAt"] >= partenza.isoformat().replace("+00:00", "Z")]
            if recenti:
                esecuzione = recenti[0]
                break
            time.sleep(3)
        if not esecuzione:
            raise ErroreConfigurazione(f"Invio avviato, ma non lo trovo: controlla su "
                                       f"https://github.com/{repo}/actions")

        print("  Preparo la rassegna di prova (di solito 1-2 minuti)", end="", flush=True)
        for _ in range(120):
            stato = json.loads(self.esegui("run", "view", str(esecuzione["databaseId"]),
                                           "--repo", repo, "--json", "status,conclusion,url"))
            if stato["status"] == "completed":
                print()
                if stato["conclusion"] == "success":
                    return ""
                registro = self.esegui("run", "view", str(esecuzione["databaseId"]), "--repo",
                                       repo, "--log-failed", controlla=False)
                righe = [r.split("\t")[-1] for r in registro.splitlines() if r.strip()][-8:]
                return "\n".join(righe) + f"\n\n  Dettagli: {stato['url']}"
            print(".", end="", flush=True)
            time.sleep(5)
        print()
        return f"L'invio sta richiedendo più del previsto: controlla su {esecuzione['url']}"


# --------------------------------------------------------------------------- #
#  La procedura completa
# --------------------------------------------------------------------------- #
def preferenze_attuali(testo: str, cfg: dict) -> dict:
    """Le scelte già salvate nella copia, da proporre come risposta predefinita."""
    try:
        salvate = yaml.safe_load(testo) or {}
        prova = {**cfg, **salvate}
        if isinstance(prova.get("ora"), int):
            prova["ora"] = f"{prova['ora'] // 60:02d}:{prova['ora'] % 60:02d}"
        rassegna.controlla_preferenze(prova)
        return prova
    except (yaml.YAMLError, ValueError, TypeError, AttributeError):
        return cfg


def avvia(percorso_config: Path) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    cfg = rassegna.carica_configurazione(percorso_config)
    print("\nLa Rassegna · configurazione guidata")
    print("Ti faccio qualche domanda e preparo tutto io. Puoi uscire quando vuoi con Ctrl+C.")
    print("Premi Invio per accettare la risposta tra parentesi quadre.")

    try:
        titolo(1, "Account GitHub")
        print("  La rassegna gira gratis su GitHub, anche a computer spento.")
        gh = GitHub(installa_gh())
        utente = gh.accedi()
        ok(f"Accesso come {utente}")
        repo = gh.prepara_copia(utente)
        ok(f"Il tuo progetto: https://github.com/{repo}")
        testo_salvato, sha = gh.leggi_preferenze(repo)
        cfg = preferenze_attuali(testo_salvato, cfg)

        titolo(2, "Email")
        presenti = gh.secret_presenti(repo)
        email = None
        if {"SMTP_USER", "SMTP_PASSWORD"} <= presenti and not conferma(
                "  L'email è già collegata. Vuoi cambiarla?", predefinito=False):
            print("  Tengo l'email già impostata.")
        else:
            email = chiedi_email()
            email["MAIL_TO"] = chiedi_destinatari(email["SMTP_USER"])

        titolo(3, "Cosa ricevere")
        giorni, ora, argomenti = rassegna.chiedi_preferenze(cfg)

        titolo(4, "Attivazione")
        if email:
            for nome, valore in email.items():
                gh.salva_secret(repo, nome, valore)
            ok("Email e password salvate nei Secrets cifrati di GitHub")
        nuovo_testo = rassegna.testo_preferenze(giorni, ora, argomenti)
        if nuovo_testo != testo_salvato:
            gh.scrivi_preferenze(repo, nuovo_testo, sha)
        ok(f"Preferenze salvate: {giorni.lower()} alle {ora}")
        gh.attiva_automazioni(repo)
        ok("Invio automatico attivato")

        if conferma("\nVuoi ricevere subito una rassegna di prova?"):
            esito = gh.invia_prova(repo)
            if esito:
                print(f"  ✗ La prova non è andata a buon fine:\n{esito}")
                return 1
            ok("Rassegna di prova inviata: controlla la posta (anche lo spam)")
    except ErroreConfigurazione as e:
        print(f"\n  ✗ {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n\nConfigurazione interrotta. Rilancia python rassegna.py per riprendere.")
        return 1

    print(f"\nFatto! La rassegna arriverà {giorni.lower()} alle {ora}.")
    print("Per cambiare argomenti, orario o email, rilancia: python rassegna.py")
    return 0
