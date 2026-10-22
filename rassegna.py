#!/usr/bin/env python3
"""
La Rassegna — rassegna stampa quotidiana in stile giornale, via email.

Legge i feed RSS elencati in config.yaml, raggruppa le notizie per sezione,
mette in prima pagina quelle riprese da più fonti e invia un'email HTML
pensata per essere letta dal telefono.

Uso:
    python rassegna.py --configura              # configura argomenti e orario
    python rassegna.py --anteprima                # crea anteprima.html, non invia nulla
    python rassegna.py --invia                    # crea e invia l'email
    python rassegna.py --demo --anteprima         # prova senza internet (dati di esempio)
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import re
import smtplib
import ssl
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import feedparser
import requests
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

QUI = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; LaRassegna/1.0; +https://github.com/)"
log = logging.getLogger("rassegna")

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
GIORNI_ID = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
FINESTRA_INVIO_MINUTI = 15

# Parole troppo comuni per decidere se due titoli parlano della stessa notizia
STOPWORDS = set("""
il lo la i gli le un uno una di a da in con su per tra fra e o ma che chi non si
del dello della dei degli delle al allo alla ai agli alle dal dalla dai dalle nel
nella nei nelle sul sulla sui sulle è sono ha hanno come dopo anche più oggi
the a an of to in on for and or but with from by at is are was were has have
after over new says said will be as it its this that
""".split())


# --------------------------------------------------------------------------- #
#  Modello dati
# --------------------------------------------------------------------------- #
@dataclass
class Articolo:
    titolo: str
    link: str
    sommario: str
    fonte: str
    scheda: str
    data: datetime
    immagine: str | None = None
    sezione: str = ""
    nome_sezione: str = ""
    altre_fonti: list[str] = field(default_factory=list)

    @property
    def parole(self) -> set[str]:
        testo = re.sub(r"[^\w\s]", " ", self.titolo.lower())
        return {p for p in testo.split() if len(p) > 3 and p not in STOPWORDS}


# --------------------------------------------------------------------------- #
#  Utilità
# --------------------------------------------------------------------------- #
def pulisci_html(testo: str) -> str:
    """Toglie tag e spazi doppi da un sommario RSS."""
    testo = re.sub(r"<[^>]+>", " ", testo or "")
    testo = html.unescape(testo)
    return re.sub(r"\s+", " ", testo).strip()


def accorcia(testo: str, n: int = 600) -> str:
    if len(testo) <= n:
        return testo
    taglio = testo[:n].rsplit(" ", 1)[0]
    return taglio.rstrip(",;:.") + "…"


def sommario_feed(voce) -> str:
    """Sceglie l'estratto più ricco pubblicato dal feed, senza recuperare l'articolo."""
    testi = [voce.get("summary", ""), voce.get("description", "")]
    testi.extend(elemento.get("value", "") for elemento in voce.get("content", []) or [])
    estratti = [pulisci_html(testo) for testo in testi if testo]
    return accorcia(max(estratti, key=len, default=""))


def data_in_italiano(d: datetime) -> str:
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"


def compila_parola_chiave(kw: str) -> re.Pattern:
    """Parole corte = parola intera; lunghe = anche inizio di parola."""
    kw = kw.strip().lower()
    fine = r"\b" if len(kw) <= 4 else ""
    return re.compile(r"\b" + re.escape(kw) + fine, re.IGNORECASE)


# --------------------------------------------------------------------------- #
#  Raccolta notizie
# --------------------------------------------------------------------------- #
def immagine_dal_feed(voce) -> str | None:
    for chiave in ("media_content", "media_thumbnail"):
        for m in voce.get(chiave, []) or []:
            if m.get("url"):
                return m["url"]
    for l in voce.get("links", []) or []:
        if l.get("rel") == "enclosure" and str(l.get("type", "")).startswith("image"):
            return l.get("href")
    # alcuni feed mettono un <img> dentro il sommario
    m = re.search(r'<img[^>]+src="([^"]+)"', voce.get("summary", "") or "")
    return m.group(1) if m else None


def immagine_dalla_pagina(url: str) -> str | None:
    """Legge il tag og:image dalla pagina dell'articolo."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8)
        r.raise_for_status()
    except requests.RequestException:
        return None
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
        r.text[:200_000], re.IGNORECASE)
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image',
            r.text[:200_000], re.IGNORECASE)
    return html.unescape(m.group(1)) if m else None


def leggi_feed(fonte: dict, dal: datetime, demo_dir: Path | None) -> list[Articolo]:
    if demo_dir:
        sorgente = demo_dir / fonte["file_demo"] if "file_demo" in fonte else None
        if not sorgente or not sorgente.exists():
            return []
        dati = feedparser.parse(sorgente.read_bytes())
    else:
        try:
            r = requests.get(fonte["url"], headers={"User-Agent": UA}, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Feed non raggiungibile: %s (%s)", fonte["nome"], e)
            return []
        dati = feedparser.parse(r.content)

    articoli = []
    for v in dati.entries:
        t = v.get("published_parsed") or v.get("updated_parsed")
        if not t:
            continue
        data = datetime(*t[:6], tzinfo=timezone.utc)
        if data < dal:
            continue
        titolo = pulisci_html(v.get("title", ""))
        if not titolo or not v.get("link"):
            continue
        articoli.append(Articolo(
            titolo=titolo,
            link=v["link"],
            sommario=sommario_feed(v),
            fonte=fonte["nome"],
            scheda=fonte.get("scheda", ""),
            data=data,
            immagine=immagine_dal_feed(v),
            sezione=fonte.get("sezione", "esteri"),
        ))
    log.info("%-18s %3d articoli", fonte["nome"], len(articoli))
    return articoli


def classifica(
    articoli: list[Articolo],
    sezioni: list[dict],
    filtra_argomenti: bool = False,
) -> list[Articolo]:
    regole = [(s["id"], [compila_parola_chiave(k) for k in s.get("parole_chiave", [])])
              for s in sezioni]
    nomi = {s["id"]: s["nome"] for s in sezioni}
    selezionati = []
    for a in articoli:
        testo = f"{a.titolo} {a.sommario}"
        corrispondenza = False
        for sid, pattern in regole:
            if any(p.search(testo) for p in pattern):
                a.sezione = sid
                corrispondenza = True
                break
        if not corrispondenza and filtra_argomenti:
            continue
        if a.sezione not in nomi:
            a.sezione = sezioni[-1]["id"]
        a.nome_sezione = nomi[a.sezione]
        selezionati.append(a)
    return selezionati


def raggruppa_doppioni(articoli: list[Articolo], soglia: float = 0.45) -> list[Articolo]:
    """Unisce le notizie uguali riprese da fonti diverse.
    Tiene la versione con immagine e annota le altre fonti."""
    gruppi: list[list[Articolo]] = []
    for a in sorted(articoli, key=lambda x: x.data, reverse=True):
        pa = a.parole
        for g in gruppi:
            pg = g[0].parole
            if pa and pg and len(pa & pg) / len(pa | pg) >= soglia:
                g.append(a)
                break
        else:
            gruppi.append([a])

    risultato = []
    for g in gruppi:
        capo = max(g, key=lambda x: (x.immagine is not None, len(x.sommario)))
        capo.altre_fonti = sorted({x.fonte for x in g if x.fonte != capo.fonte})
        risultato.append(capo)
    return risultato


def accadde_oggi(oggi: datetime, lingua: str) -> list[dict]:
    url = (f"https://api.wikimedia.org/feed/v1/wikipedia/{lingua}/onthisday/"
           f"selected/{oggi.month:02d}/{oggi.day:02d}")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        r.raise_for_status()
        eventi = r.json().get("selected", [])
    except (requests.RequestException, ValueError):
        return []
    return [{"anno": e.get("year"), "testo": e.get("text", "")} for e in eventi[:3]]


def carica_configurazione(percorso: Path) -> dict:
    cfg = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"Configurazione non valida: {percorso}")
    preferenze = percorso.with_name("preferenze.yaml")
    if preferenze.exists():
        personali = yaml.safe_load(preferenze.read_text(encoding="utf-8"))
        if not isinstance(personali, dict):
            raise ValueError(f"Preferenze non valide: {preferenze}")
        cfg.update(personali)
    return cfg


def cron_programmazione(giorni: list[str], orario: str, fuso_orario: str) -> list[str]:
    ora, minuto = (int(parte) for parte in orario.split(":"))
    zona = ZoneInfo(fuso_orario)
    programmazioni = set()
    for mese in (1, 7):
        campione = datetime(2026, mese, 15, ora, minuto, tzinfo=zona)
        for giorno in giorni:
            indice = GIORNI_ID.index(giorno)
            scarto = (indice - campione.weekday()) % 7
            locale = campione + timedelta(days=scarto)
            utc = locale.astimezone(timezone.utc)
            giorno_utc = (utc.weekday() + 1) % 7
            programmazioni.add((utc.minute, utc.hour, giorno_utc))
    per_orario = {}
    for minuto_utc, ora_utc, giorno_utc in programmazioni:
        per_orario.setdefault((minuto_utc, ora_utc), set()).add(giorno_utc)
    return [
        f"{minuto_utc} {ora_utc} * * {','.join(map(str, sorted(giorni_utc)))}"
        for (minuto_utc, ora_utc), giorni_utc in sorted(per_orario.items())
    ]


def invio_programmato(ora: datetime, cfg: dict) -> bool:
    giorni = cfg.get("giorni_invio", GIORNI_ID)
    if GIORNI_ID[ora.weekday()] not in giorni:
        return False
    orario = datetime.strptime(cfg.get("ora_invio", "06:45"), "%H:%M")
    minuti_passati = ora.hour * 60 + ora.minute - (orario.hour * 60 + orario.minute)
    return 0 <= minuti_passati < FINESTRA_INVIO_MINUTI


def _giorno_id(valore: str) -> str:
    normalizzato = unicodedata.normalize("NFKD", valore.strip().lower())
    normalizzato = "".join(c for c in normalizzato if not unicodedata.combining(c))
    alias = {"lun": "lunedi", "mar": "martedi", "mer": "mercoledi",
             "gio": "giovedi", "ven": "venerdi", "sab": "sabato", "dom": "domenica"}
    giorno = alias.get(normalizzato, normalizzato)
    if giorno not in GIORNI_ID:
        raise ValueError(f"Giorno non riconosciuto: {valore}")
    return giorno


def configura(percorso: Path) -> int:
    cfg = carica_configurazione(percorso)
    pref_path = percorso.with_name("preferenze.yaml")
    preferenze = yaml.safe_load(pref_path.read_text(encoding="utf-8")) if pref_path.exists() else {}
    preferenze = preferenze or {}

    print("Configura il tuo giornale. Premi Invio per mantenere il valore proposto.")
    testata = input(f"Nome della rassegna [{cfg.get('testata', 'La Rassegna')}]: ").strip()
    if testata:
        cfg["testata"] = testata

    while True:
        fuso = input(f"Fuso orario [{cfg.get('fuso_orario', 'Europe/Rome')}]: ").strip()
        fuso = fuso or cfg.get("fuso_orario", "Europe/Rome")
        try:
            ZoneInfo(fuso)
            break
        except ZoneInfoNotFoundError:
            print("Fuso non riconosciuto (esempio valido: Europe/Rome).")

    giorni_default = preferenze.get("giorni_invio", GIORNI_ID[:5])
    while True:
        testo_giorni = input(
            f"Giorni, separati da virgola [{', '.join(giorni_default)}]: "
        ).strip()
        if not testo_giorni:
            giorni = giorni_default
            break
        try:
            giorni = list(dict.fromkeys(_giorno_id(g) for g in testo_giorni.split(",")))
            if not giorni:
                raise ValueError("Indica almeno un giorno.")
            break
        except ValueError as e:
            print(e)

    orario_default = preferenze.get("ora_invio", "06:45")
    while True:
        orario = input(f"Orario locale HH:MM [{orario_default}]: ").strip() or orario_default
        try:
            datetime.strptime(orario, "%H:%M")
            break
        except ValueError:
            print("Orario non valido: usa il formato 06:45.")

    sezioni_default = preferenze.get("sezioni", cfg.get("sezioni", []))
    print("Argomenti: una riga per argomento nel formato Nome | parola1, parola2.")
    print("Invio vuoto sulla prima riga mantiene gli argomenti esistenti.")
    sezioni = []
    argomenti_personali = False
    while True:
        riga = input("Argomento: ").strip()
        if not riga:
            if sezioni:
                break
            sezioni = sezioni_default
            break
        if "|" in riga:
            nome, parole = (parte.strip() for parte in riga.split("|", 1))
            parole_chiave = [p.strip() for p in parole.split(",") if p.strip()]
        else:
            nome = riga
            parole_chiave = [riga]
        if not nome or not parole_chiave:
            print("Inserisci un nome e almeno una parola chiave.")
            continue
        base_id = re.sub(
            r"[^a-z0-9]+", "_",
            unicodedata.normalize("NFKD", nome.lower()).encode("ascii", "ignore").decode()
        ).strip("_") or f"argomento_{len(sezioni) + 1}"
        sid = base_id
        suffisso = 2
        while any(s["id"] == sid for s in sezioni):
            sid = f"{base_id}_{suffisso}"
            suffisso += 1
        sezioni.append({"id": sid, "nome": nome, "parole_chiave": parole_chiave})
        argomenti_personali = True

    workflow = QUI / ".github" / "workflows" / "rassegna.yml"
    if not workflow.exists():
        raise FileNotFoundError(f"Workflow GitHub Actions non trovato: {workflow}")
    testo_workflow = workflow.read_text(encoding="utf-8")
    pattern = re.compile(r"(?ms)^  schedule:\r?\n.*?(?=^  workflow_dispatch:)")
    if not pattern.search(testo_workflow):
        raise ValueError(f"Impossibile aggiornare la sezione schedule in {workflow}")
    cron = cron_programmazione(giorni, orario, fuso)

    cfg.update({
        "fuso_orario": fuso,
        "giorni_invio": giorni,
        "ora_invio": orario,
    })
    if sezioni:
        cfg["sezioni"] = sezioni
        preferenze["sezioni"] = sezioni
    if argomenti_personali:
        preferenze["sottotitolo"] = " · ".join(s["nome"] for s in sezioni)
    preferenze["filtra_argomenti"] = (
        argomenti_personali or preferenze.get("filtra_argomenti", False)
    )
    preferenze.update({
        "testata": cfg.get("testata", "La Rassegna"),
        "fuso_orario": fuso,
        "giorni_invio": giorni,
        "ora_invio": orario,
    })
    pref_path.write_text(
        yaml.safe_dump(preferenze, allow_unicode=True, sort_keys=False),
        encoding="utf-8"
    )

    blocco = "  schedule:\n    # Generato da python rassegna.py --configura.\n"
    blocco += "".join(f'    - cron: "{espressione}"\n' for espressione in cron)
    workflow.write_text(pattern.sub(blocco, testo_workflow, count=1), encoding="utf-8")

    while True:
        destinatario = input(
            "Email destinataria (facoltativa, non verrà salvata nel repository): "
        ).strip()
        if not destinatario or all(
            re.fullmatch(r"[^@\s,]+@[^@\s,]+\.[^@\s,]+", email.strip())
            for email in destinatario.split(",")
        ):
            break
        print("Indirizzo non valido: inserisci email separate da virgola.")
    if destinatario:
        env_path = QUI / ".env"
        righe = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        righe = [r for r in righe if not r.startswith("MAIL_TO=")]
        righe.append(f"MAIL_TO={destinatario}")
        env_path.write_text("\n".join(righe) + "\n", encoding="utf-8")
        print("Indirizzo salvato solo nel file locale .env.")
    print(f"Preferenze salvate in {pref_path}. Cron GitHub Actions aggiornato.")
    print("Per gli invii su GitHub, imposta MAIL_TO nei Secrets del tuo repository.")
    return 0


# --------------------------------------------------------------------------- #
#  Impaginazione
# --------------------------------------------------------------------------- #
def impagina(cfg: dict, articoli: list[Articolo], ora: datetime) -> dict:
    # Prima pagina: notizie riprese da più fonti, poi le più recenti con foto
    ordinati = sorted(
        articoli,
        key=lambda a: (len(a.altre_fonti), a.immagine is not None, a.data),
        reverse=True)
    prima = ordinati[: cfg.get("max_prima_pagina", 4)]
    usati = {id(a) for a in prima}

    sezioni, avanzi = [], []
    for s in cfg["sezioni"]:
        pezzi = [a for a in ordinati if a.sezione == s["id"] and id(a) not in usati]
        pezzi.sort(key=lambda a: (len(a.altre_fonti), a.data), reverse=True)
        n = cfg.get("max_per_sezione", 4)
        if pezzi[:n]:
            sezioni.append({"nome": s["nome"], "articoli": pezzi[:n]})
        avanzi += pezzi[n:]

    avanzi.sort(key=lambda a: a.data, reverse=True)
    return {
        "testata": cfg.get("testata", "La Rassegna"),
        "sottotitolo": cfg.get("sottotitolo", ""),
        "data": data_in_italiano(ora).upper(),
        "data_breve": data_in_italiano(ora),
        "numero": (ora.date() - datetime(ora.year, 1, 1).date()).days + 1,
        "prima": prima,
        "sezioni": sezioni,
        "in_breve": avanzi[: cfg.get("max_in_breve", 30)],
        "accadde_oggi": accadde_oggi(ora, cfg.get("lingua", "it")) if cfg.get("accadde_oggi") else [],
        "fonti": cfg["fonti"],
    }


def testo_semplice(p: dict) -> str:
    """Versione solo testo, per i client email che non mostrano l'HTML."""
    righe = [f"{p['testata'].upper()} – {p['data_breve']}", ""]
    blocchi = [("PRIMA PAGINA", p["prima"])] + [(s["nome"].upper(), s["articoli"]) for s in p["sezioni"]]
    for nome, arts in blocchi:
        righe.append(nome)
        for a in arts:
            if a.nome_sezione:
                righe.append(f"[{a.nome_sezione}]")
            righe.append(f"- {a.titolo} ({a.fonte})")
            if a.sommario:
                righe.append(f"  {a.sommario}")
            if a.altre_fonti:
                righe.append(f"  Ripresa anche da: {', '.join(a.altre_fonti)}")
            righe.append(f"  Leggi la notizia: {a.link}")
        righe.append("")
    if p["in_breve"]:
        righe.append("IN BREVE")
        for a in p["in_breve"]:
            testo = f"- {a.titolo} ({a.fonte})"
            if a.sommario:
                testo += f" — {a.sommario}"
            righe.append(f"{testo}\n  {a.link}")
    return "\n".join(righe)


# --------------------------------------------------------------------------- #
#  Invio
# --------------------------------------------------------------------------- #
def carica_env(percorso: Path) -> None:
    """Legge un file .env (solo per l'uso in locale). Non sovrascrive variabili già impostate."""
    if not percorso.exists():
        return
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if riga and not riga.startswith("#") and "=" in riga:
            k, v = riga.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def invia(oggetto: str, corpo_html: str, corpo_testo: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    porta = int(os.environ.get("SMTP_PORT", "465"))
    utente = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    destinatari = [d.strip() for d in os.environ.get("MAIL_TO", utente).split(",") if d.strip()]
    mittente = os.environ.get("MAIL_FROM", utente)

    msg = EmailMessage()
    msg["Subject"] = oggetto
    msg["From"] = mittente
    msg["To"] = mittente
    msg["Bcc"] = ", ".join(destinatari)   # i destinatari non si vedono tra loro
    msg.set_content(corpo_testo)
    msg.add_alternative(corpo_html, subtype="html")

    contesto = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=contesto, timeout=30) as s:
            s.login(utente, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls(context=contesto)
            s.login(utente, password)
            s.send_message(msg)
    log.info("Email inviata a %d destinatari", len(destinatari))


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Rassegna stampa quotidiana via email")
    ap.add_argument("--config", default=str(QUI / "config.yaml"))
    ap.add_argument("--configura", action="store_true", help="configura argomenti, giorni e orario")
    ap.add_argument("--anteprima", nargs="?", const="anteprima.html", metavar="FILE",
                    help="salva l'HTML in un file (default: anteprima.html)")
    ap.add_argument("--invia", action="store_true", help="invia l'email")
    ap.add_argument("--demo", action="store_true", help="usa i feed di esempio in demo/, senza internet")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.configura:
        return configura(Path(args.config))
    if not args.anteprima and not args.invia:
        ap.error("scegli --anteprima e/o --invia")

    cfg = carica_configurazione(Path(args.config))
    tz = ZoneInfo(cfg.get("fuso_orario", "Europe/Rome"))
    ora = datetime.now(tz)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not invio_programmato(ora, cfg):
        log.info("Nessun invio previsto oggi a quest'ora.")
        return 0

    demo_dir = None
    if args.demo:
        demo_dir = QUI / "demo"
        cfg["fonti"] = yaml.safe_load((demo_dir / "fonti_demo.yaml").read_text(encoding="utf-8"))
        cfg["accadde_oggi"] = False
        cfg["cerca_immagini_nelle_pagine"] = False
        dal = datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        dal = datetime.now(timezone.utc) - timedelta(hours=cfg.get("ore_indietro", 26))

    articoli = []
    for f in cfg["fonti"]:
        articoli += leggi_feed(f, dal, demo_dir)
    if not articoli:
        log.error("Nessuna notizia trovata: controlla i feed in config.yaml")
        return 1

    articoli = classifica(articoli, cfg["sezioni"], cfg.get("filtra_argomenti", False))
    if not articoli:
        log.error("Nessuna notizia corrisponde agli argomenti scelti nei feed configurati.")
        return 1
    articoli = raggruppa_doppioni(articoli)
    pagina = impagina(cfg, articoli, ora)
    pagina["demo"] = args.demo

    if cfg.get("cerca_immagini_nelle_pagine"):
        in_vista = pagina["prima"] + [a for s in pagina["sezioni"] for a in s["articoli"]]
        for a in in_vista:
            if not a.immagine:
                a.immagine = immagine_dalla_pagina(a.link)

    env = Environment(loader=FileSystemLoader(QUI / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    corpo_html = env.get_template("email.html.j2").render(**pagina)
    oggetto = f"{pagina['testata']} – {pagina['data_breve']}"

    if args.anteprima:
        Path(args.anteprima).write_text(corpo_html, encoding="utf-8")
        log.info("Anteprima salvata in %s", args.anteprima)
    if args.invia:
        carica_env(QUI / ".env")
        for var in ("SMTP_USER", "SMTP_PASSWORD"):
            if not os.environ.get(var):
                log.error("Manca %s: impostalo nei Secrets di GitHub o nel file .env", var)
                return 1
        invia(oggetto, corpo_html, testo_semplice(pagina))
    return 0


if __name__ == "__main__":
    sys.exit(main())
