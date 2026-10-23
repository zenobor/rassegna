#!/usr/bin/env python3
"""
La Rassegna — una rassegna stampa italiana in stile giornale, ricevuta per email.

Legge i feed RSS delle testate italiane elencate in config.yaml, tiene solo gli
argomenti scelti, mette in prima pagina le notizie riprese da più fonti e invia
un'email HTML pensata per essere letta dal telefono.

Uso:
    python rassegna.py --configura              # scegli argomenti, giorni e ora
    python rassegna.py --anteprima                # crea anteprima.html, non invia nulla
    python rassegna.py --invia                    # crea e invia l'email
    python rassegna.py --demo --anteprima         # prova senza internet (dati di esempio)
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

QUI = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (compatible; LaRassegna/1.0; +https://github.com/)"
# Wikipedia limita gli user agent generici (errore 429): vuole un nome e un indirizzo.
UA_WIKIPEDIA = "LaRassegna/1.0 (https://github.com/zenobor/rassegna)"
FUSO = ZoneInfo("Europe/Rome")
log = logging.getLogger("rassegna")

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]

# Le scelte possibili: le stesse nel modulo su GitHub e in --configura.
OPZIONI_GIORNI = {
    "Dal lunedì al venerdì": [0, 1, 2, 3, 4],
    "Tutti i giorni": [0, 1, 2, 3, 4, 5, 6],
    "Solo sabato e domenica": [5, 6],
}
ORARI = [f"{ora:02d}:00" for ora in range(5, 23)]
# Il workflow parte qualche minuto prima dell'ora scelta, così l'email arriva puntuale.
ANTICIPO_MINUTI = 5

# Parole troppo comuni per decidere se due titoli parlano della stessa notizia
STOPWORDS = set("""
il lo la i gli le un uno una di a da in con su per tra fra e o ma che chi non si
del dello della dei degli delle al allo alla ai agli alle dal dalla dai dalle nel
nella nei nelle sul sulla sui sulle è sono ha hanno come dopo anche più oggi
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
    priorita: int = 10
    altre_fonti: list[dict[str, str]] = field(default_factory=list)

    @property
    def paragrafi_sommario(self) -> list[str]:
        return [p.strip() for p in self.sommario.split("\n\n") if p.strip()]

    @property
    def sottotitolo(self) -> str:
        paragrafi = self.paragrafi_sommario
        return paragrafi[0] if len(paragrafi) > 1 else ""

    @property
    def testo_articolo(self) -> str:
        paragrafi = self.paragrafi_sommario
        return "\n\n".join(paragrafi[1:] if len(paragrafi) > 1 else paragrafi)

    @property
    def estratto_breve(self) -> str:
        """La prima frase del riassunto, per la sezione In breve."""
        testo = self.paragrafi_sommario[0] if self.paragrafi_sommario else ""
        frase = re.match(r".{40,}?[.!?](?=\s|$)", testo)
        testo = frase.group(0) if frase else testo
        if len(testo) > 220:
            testo = testo[:220].rsplit(" ", 1)[0] + "…"
        return testo

    @property
    def ricco(self) -> bool:
        """Il feed offre un riassunto vero, non solo una riga."""
        return len(self.sommario) >= 200

    @property
    def parole(self) -> set[str]:
        testo = re.sub(r"[^\w\s]", " ", self.titolo.lower())
        return {p for p in testo.split() if len(p) > 3 and p not in STOPWORDS}


# --------------------------------------------------------------------------- #
#  Utilità
# --------------------------------------------------------------------------- #
def pulisci_html(testo: str) -> str:
    """Pulisce un sommario RSS preservando i paragrafi forniti dal feed."""
    testo = html.unescape(testo or "")
    testo = re.sub(r"(?i)<\s*(?:br\s*/?|/p|/div)\s*>", "\n", testo)
    testo = re.sub(r"<[^>]+>", " ", testo)
    paragrafi = [re.sub(r"\s+", " ", p).strip() for p in testo.splitlines()]
    return "\n\n".join(p for p in paragrafi if p)


def sommario_feed(voce) -> str:
    """Usa il sommario RSS più ricco, senza copiare il corpo completo dell'articolo."""
    testi = [voce.get("summary", ""), voce.get("description", "")]
    estratti = [pulisci_html(testo) for testo in testi if testo]
    return max(estratti, key=len, default="")


_MESI_RSS = {"gen": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "mag": "May",
             "giu": "Jun", "lug": "Jul", "ago": "Aug", "set": "Sep", "ott": "Oct",
             "nov": "Nov", "dic": "Dec"}


def data_rss_italiana(testo: str):
    """Legge date RSS scritte in italiano, es. 'gio, 22 ott 2026 17:24:57 GMT'."""
    m = re.match(r"^\s*(?:[^\W\d]+\.?,\s*)?(\d{1,2})\s+([^\W\d]{3})[^\W\d]*\.?\s+(\d{4}\s+.+)$", testo)
    if not m or m.group(2).lower() not in _MESI_RSS:
        return None
    analizzata = email.utils.parsedate_tz(
        f"{m.group(1)} {_MESI_RSS[m.group(2).lower()]} {m.group(3)}"
    )
    return time.gmtime(email.utils.mktime_tz(analizzata)) if analizzata else None


feedparser.registerDateHandler(data_rss_italiana)


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
            if m.get("url") and _url_immagine_valido(m["url"]):
                return m["url"]
    for l in voce.get("links", []) or []:
        if (
            l.get("rel") == "enclosure"
            and str(l.get("type", "")).startswith("image")
            and _url_immagine_valido(l.get("href", ""))
        ):
            return l.get("href")
    # alcuni feed mettono un <img> dentro il sommario
    m = re.search(r'<img[^>]+src="([^"]+)"', voce.get("summary", "") or "")
    return m.group(1) if m and _url_immagine_valido(m.group(1)) else None


def _url_immagine_valido(url: str) -> bool:
    try:
        parti = urlsplit(url)
        return parti.scheme == "https" and bool(parti.netloc)
    except ValueError:
        return False


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
    if not m:
        return None
    immagine = html.unescape(m.group(1))
    return immagine if _url_immagine_valido(immagine) else None


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
    senza_data = 0
    senza_estratto_informativo = 0
    for v in dati.entries:
        t = v.get("published_parsed") or v.get("updated_parsed")
        if not t:
            senza_data += 1
            continue
        data = datetime(*t[:6], tzinfo=timezone.utc)
        if data < dal:
            continue
        titolo = pulisci_html(v.get("title", ""))
        if not titolo or not v.get("link"):
            continue
        sommario = sommario_feed(v)
        titolo_normalizzato = re.sub(r"\W+", "", titolo).casefold()
        sommario_normalizzato = re.sub(r"\W+", "", sommario).casefold()
        if not sommario or sommario_normalizzato == titolo_normalizzato:
            senza_estratto_informativo += 1
            continue
        articoli.append(Articolo(
            titolo=titolo,
            link=v["link"],
            sommario=sommario,
            fonte=fonte["nome"],
            scheda=fonte.get("scheda", ""),
            data=data,
            immagine=immagine_dal_feed(v),
            sezione=fonte.get("argomento", "generale"),
            priorita=int(fonte.get("priorita", 10)),
        ))
    log.info("%-26s %3d notizie", fonte["nome"], len(articoli))
    if senza_estratto_informativo:
        log.info("%s: %d notizie senza riassunto ignorate", fonte["nome"], senza_estratto_informativo)
    if senza_data:
        log.warning("%s: %d notizie senza data leggibile ignorate", fonte["nome"], senza_data)
    return articoli


def classifica(articoli: list[Articolo], argomenti: list[dict], scelti: list[str]) -> list[Articolo]:
    """Assegna ogni notizia a un argomento e tiene solo quelli scelti.

    Le notizie dei feed tematici (es. ANSA Sport) restano nel loro argomento;
    quelle dei feed generali vanno nell'argomento con più parole chiave
    trovate (quelle nel titolo contano il triplo; a parità vince il primo)."""
    regole = [(a["id"], [compila_parola_chiave(k) for k in a.get("parole_chiave", [])])
              for a in argomenti]
    nomi = {a["id"]: a["nome"] for a in argomenti}
    selezionati = []
    for a in articoli:
        if a.sezione not in nomi:
            punteggi = [
                (sum(3 * bool(p.search(a.titolo)) + bool(p.search(a.sommario)) for p in pattern), aid)
                for aid, pattern in regole
            ]
            migliore = max(punteggi, key=lambda x: x[0], default=(0, ""))
            a.sezione = migliore[1] if migliore[0] else ""
        if a.sezione in scelti:
            a.nome_sezione = nomi[a.sezione]
            selezionati.append(a)
    return selezionati


def raggruppa_doppioni(articoli: list[Articolo], soglia: float = 0.45) -> list[Articolo]:
    """Unisce le notizie uguali riprese da fonti diverse.
    Tiene la versione col riassunto migliore e annota le altre fonti."""
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
        capo = max(
            g,
            key=lambda x: (x.ricco, -x.priorita, x.immagine is not None, len(x.sommario)),
        )
        fonti = {
            x.fonte: {"nome": x.fonte, "link": x.link, "scheda": x.scheda}
            for x in g if x.fonte != capo.fonte
        }
        capo.altre_fonti = sorted(fonti.values(), key=lambda fonte: fonte["nome"])
        risultato.append(capo)
    return risultato


def accadde_oggi(oggi: datetime) -> list[dict]:
    url = (f"https://api.wikimedia.org/feed/v1/wikipedia/it/onthisday/"
           f"selected/{oggi.month:02d}/{oggi.day:02d}")
    try:
        r = requests.get(url, headers={"User-Agent": UA_WIKIPEDIA}, timeout=10)
        r.raise_for_status()
        eventi = r.json().get("selected", [])
    except (requests.RequestException, ValueError) as e:
        log.warning("'Accadde oggi' saltato: Wikipedia non risponde (%s)", e)
        return []
    return [{"anno": e.get("year"), "testo": e.get("text", "")} for e in eventi[:3]]


# --------------------------------------------------------------------------- #
#  Preferenze e programmazione
# --------------------------------------------------------------------------- #
def carica_configurazione(percorso: Path) -> dict:
    cfg = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError(f"Configurazione non valida: {percorso}")
    preferenze = percorso.with_name("preferenze.yaml")
    if preferenze.exists():
        personali = yaml.safe_load(preferenze.read_text(encoding="utf-8")) or {}
        if not isinstance(personali, dict):
            raise ValueError(f"Preferenze non valide: {preferenze}")
        cfg.update(personali)
    cfg.setdefault("giorni", "Dal lunedì al venerdì")
    cfg.setdefault("ora", "07:00")
    cfg.setdefault("argomenti", [a["id"] for a in cfg["catalogo_argomenti"]])
    if isinstance(cfg["ora"], int):
        # YAML legge 07:00 senza virgolette come minuti (420)
        cfg["ora"] = f"{cfg['ora'] // 60:02d}:{cfg['ora'] % 60:02d}"
    controlla_preferenze(cfg)
    return cfg


def controlla_preferenze(cfg: dict) -> None:
    ids = [a["id"] for a in cfg["catalogo_argomenti"]]
    if cfg["giorni"] not in OPZIONI_GIORNI:
        raise ValueError(f"preferenze.yaml: 'giorni' deve essere uno tra {list(OPZIONI_GIORNI)}")
    if str(cfg["ora"]) not in ORARI:
        raise ValueError(f"preferenze.yaml: 'ora' deve essere un'ora intera tra {ORARI[0]} e {ORARI[-1]}")
    sconosciuti = [a for a in cfg["argomenti"] if a not in ids]
    if sconosciuti or not cfg["argomenti"]:
        raise ValueError(f"preferenze.yaml: scegli almeno un argomento tra {ids}")


def salva_preferenze(percorso: Path, giorni: str, ora: str, argomenti: list[str]) -> None:
    testo = (
        "# Le tue preferenze. Il modo più semplice per cambiarle è su GitHub:\n"
        "# Actions → Configura la rassegna → Run workflow.\n"
        + yaml.safe_dump({"giorni": giorni, "ora": ora, "argomenti": argomenti},
                         allow_unicode=True, sort_keys=False)
    )
    percorso.write_text(testo, encoding="utf-8")


def cron_orari() -> list[str]:
    """Le cron del workflow: una per ogni ora UTC che può corrispondere a un orario
    della lista, con l'ora legale e con l'ora solare."""
    ore_utc = set()
    for mese in (1, 7):
        for orario in ORARI:
            locale = datetime(2026, mese, 15, int(orario[:2]), tzinfo=FUSO)
            partenza = (locale - timedelta(minutes=ANTICIPO_MINUTI)).astimezone(timezone.utc)
            ore_utc.add((partenza.hour, partenza.minute))
    return [f"{minuto} {ora} * * *" for ora, minuto in sorted(ore_utc)]


def invio_programmato(cfg: dict, adesso: datetime, cron: str | None = None) -> bool:
    """Dice se questa esecuzione programmata deve inviare l'edizione.

    GitHub passa l'espressione cron che ha avviato il workflow: da quella si ricava
    l'ora prevista, quindi i ritardi di GitHub non contano."""
    giorni = OPZIONI_GIORNI[cfg["giorni"]]
    ora_scelta = int(str(cfg["ora"])[:2])
    adesso_utc = adesso.astimezone(timezone.utc)
    try:
        minuto_cron, ora_cron = (int(parte) for parte in cron.split()[:2])
    except (AttributeError, ValueError):
        locale = adesso.astimezone(FUSO)
        return locale.weekday() in giorni and locale.hour == ora_scelta
    previsto = adesso_utc.replace(hour=ora_cron, minute=minuto_cron, second=0, microsecond=0)
    if previsto > adesso_utc:
        previsto -= timedelta(days=1)
    edizione = (previsto + timedelta(minutes=ANTICIPO_MINUTI)).astimezone(FUSO)
    return edizione.weekday() in giorni and (edizione.hour, edizione.minute) == (ora_scelta, 0)


def _scegli(domanda: str, opzioni: list[str], attuale: str) -> str:
    for i, opzione in enumerate(opzioni, 1):
        print(f"  {i}. {opzione}")
    while True:
        risposta = input(f"{domanda} [{opzioni.index(attuale) + 1}]: ").strip()
        if not risposta:
            return attuale
        if risposta.isdigit() and 1 <= int(risposta) <= len(opzioni):
            return opzioni[int(risposta) - 1]
        print(f"Scrivi un numero da 1 a {len(opzioni)}.")


def configura(percorso: Path) -> int:
    cfg = carica_configurazione(percorso)
    catalogo = cfg["catalogo_argomenti"]
    print("Configura la tua rassegna. Premi Invio per tenere la scelta attuale.\n")

    print("Argomenti:")
    for i, argomento in enumerate(catalogo, 1):
        segno = "x" if argomento["id"] in cfg["argomenti"] else " "
        print(f"  {i}. [{segno}] {argomento['nome']}")
    while True:
        risposta = input("Numeri degli argomenti che vuoi ricevere, separati da virgola "
                         "(es. 1,2,5): ").strip()
        if not risposta:
            argomenti = cfg["argomenti"]
            break
        numeri = [n.strip() for n in risposta.split(",") if n.strip()]
        if numeri and all(n.isdigit() and 1 <= int(n) <= len(catalogo) for n in numeri):
            scelti = {catalogo[int(n) - 1]["id"] for n in numeri}
            argomenti = [a["id"] for a in catalogo if a["id"] in scelti]
            break
        print(f"Scrivi uno o più numeri da 1 a {len(catalogo)}, separati da virgola.")

    print("\nGiorni di invio:")
    giorni = _scegli("Numero", list(OPZIONI_GIORNI), cfg["giorni"])
    print("\nOra di invio:")
    ora = _scegli("Numero", ORARI, str(cfg["ora"]))

    pref_path = percorso.with_name("preferenze.yaml")
    salva_preferenze(pref_path, giorni, ora, argomenti)
    print(f"\nFatto! Preferenze salvate in {pref_path.name}.")
    print("Per usarle negli invii automatici, carica il file su GitHub (git commit e git push).")
    return 0


def preferenze_da_modulo(percorso: Path, modulo: dict) -> int:
    """Salva le scelte fatte nel modulo 'Configura la rassegna' di GitHub Actions."""
    cfg = carica_configurazione(percorso)
    argomenti = [a["id"] for a in cfg["catalogo_argomenti"]
                 if str(modulo.get(a["id"], "false")).lower() == "true"]
    cfg.update({"giorni": modulo.get("giorni"), "ora": modulo.get("ora"), "argomenti": argomenti})
    try:
        controlla_preferenze(cfg)
    except ValueError as e:
        log.error("%s", e)
        return 1
    salva_preferenze(percorso.with_name("preferenze.yaml"), cfg["giorni"], cfg["ora"], argomenti)
    nomi = [a["nome"] for a in cfg["catalogo_argomenti"] if a["id"] in argomenti]
    riepilogo = (f"Preferenze salvate: {cfg['giorni'].lower()} alle {cfg['ora']}.\n"
                 f"Argomenti: {', '.join(nomi)}.")
    log.info(riepilogo)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"### Preferenze salvate\n\n{riepilogo}\n")
    return 0


# --------------------------------------------------------------------------- #
#  Impaginazione
# --------------------------------------------------------------------------- #
def impagina(cfg: dict, articoli: list[Articolo], ora: datetime) -> dict:
    def rilevanza(a: Articolo):
        # prima le notizie riprese da più fonti, poi quelle con un vero riassunto
        return (len(a.altre_fonti), a.ricco, -a.priorita, a.immagine is not None, a.data)

    ordinati = sorted(articoli, key=rilevanza, reverse=True)
    prima = ordinati[: cfg.get("max_prima_pagina", 4)]
    usati = {id(a) for a in prima}

    argomenti = [a for a in cfg["catalogo_argomenti"] if a["id"] in cfg["argomenti"]]
    sezioni, avanzi = [], []
    for s in argomenti:
        pezzi = [a for a in ordinati if a.sezione == s["id"] and id(a) not in usati]
        n = max(0, int(cfg.get("max_per_argomento", 5)))
        if pezzi[:n]:
            sezioni.append({"nome": s["nome"], "articoli": pezzi[:n]})
        avanzi += pezzi[n:]

    # In breve: le più recenti, ma al massimo due per fonte, così non domina chi pubblica di più
    avanzi.sort(key=lambda a: a.data, reverse=True)
    in_breve, per_fonte = [], {}
    for a in avanzi:
        if per_fonte.get(a.fonte, 0) < 2:
            in_breve.append(a)
            per_fonte[a.fonte] = per_fonte.get(a.fonte, 0) + 1
    return {
        "testata": cfg.get("testata", "La Rassegna"),
        "sottotitolo": " · ".join(s["nome"] for s in argomenti),
        "data": data_in_italiano(ora).upper(),
        "data_breve": data_in_italiano(ora),
        "anno": ora.year,
        "numero": (ora.date() - datetime(ora.year, 1, 1).date()).days + 1,
        "prima": prima,
        "sezioni": sezioni,
        "in_breve": in_breve[: cfg.get("max_in_breve", 8)],
        "accadde_oggi": accadde_oggi(ora) if cfg.get("accadde_oggi") else [],
    }


def testo_semplice(p: dict) -> str:
    """Versione solo testo, per i client email che non mostrano l'HTML."""
    righe = [f"{p['testata'].upper()} – {p['data_breve']}", ""]
    blocchi = [("PRIMA PAGINA", p["prima"])] + [(s["nome"].upper(), s["articoli"]) for s in p["sezioni"]]
    for nome, arts in blocchi:
        righe.append(nome)
        for a in arts:
            if a.nome_sezione and nome == "PRIMA PAGINA":
                righe.append(f"[{a.nome_sezione}]")
            righe.append(f"- {a.titolo} ({a.fonte})")
            if a.sommario:
                righe.append(f"  {a.sommario}")
            if a.altre_fonti:
                nomi_fonti = ", ".join(fonte["nome"] for fonte in a.altre_fonti)
                righe.append(f"  Ripresa anche da: {nomi_fonti}")
            righe.append(f"  Leggi la notizia: {a.link}")
        righe.append("")
    if p["in_breve"]:
        righe.append("IN BREVE")
        for a in p["in_breve"]:
            testo = f"- {a.titolo} ({a.fonte})"
            if a.estratto_breve:
                testo += f" — {a.estratto_breve}"
            righe.append(f"{testo}\n  {a.link}")
    return "\n".join(righe)


def ambiente_template() -> Environment:
    return Environment(loader=FileSystemLoader(QUI / "templates"),
                       autoescape=select_autoescape(["html", "j2"]))


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
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    porta = int(os.environ.get("SMTP_PORT") or "465")
    utente = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    destinatari = [d.strip() for d in (os.environ.get("MAIL_TO") or utente).split(",") if d.strip()]
    mittente = os.environ.get("MAIL_FROM") or utente

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
    ap = argparse.ArgumentParser(description="Rassegna stampa italiana via email")
    ap.add_argument("--config", default=str(QUI / "config.yaml"))
    ap.add_argument("--configura", action="store_true", help="scegli argomenti, giorni e ora")
    ap.add_argument("--da-modulo", action="store_true",
                    help="salva le preferenze dal modulo di GitHub Actions (variabile MODULO)")
    ap.add_argument("--anteprima", nargs="?", const="anteprima.html", metavar="FILE",
                    help="salva l'HTML in un file (predefinito: anteprima.html)")
    ap.add_argument("--invia", action="store_true", help="invia l'email")
    ap.add_argument("--demo", action="store_true", help="usa i feed di esempio in demo/, senza internet")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if args.configura:
            return configura(Path(args.config))
        if args.da_modulo:
            return preferenze_da_modulo(Path(args.config), json.loads(os.environ.get("MODULO", "{}")))
        cfg = carica_configurazione(Path(args.config))
    except ValueError as e:
        log.error("%s", e)
        return 1
    if not args.anteprima and not args.invia:
        ap.error("scegli --anteprima e/o --invia")

    ora = datetime.now(FUSO)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not invio_programmato(
        cfg, ora, os.environ.get("GITHUB_SCHEDULE")
    ):
        log.info("Nessun invio previsto a quest'ora: la rassegna parte %s alle %s.",
                 cfg["giorni"].lower(), cfg["ora"])
        return 0

    carica_env(QUI / ".env")
    if args.invia:
        mancanti = [v for v in ("SMTP_USER", "SMTP_PASSWORD") if not os.environ.get(v)]
        if mancanti:
            log.error("Mancano %s: aggiungili su GitHub in Settings → Secrets and variables "
                      "→ Actions (o nel file .env per le prove in locale).", " e ".join(mancanti))
            return 1

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
        log.error("Nessuna notizia trovata: controlla la connessione e le fonti in config.yaml.")
        return 1
    articoli = classifica(articoli, cfg["catalogo_argomenti"], cfg["argomenti"])
    if not articoli:
        log.error("Nessuna notizia sugli argomenti scelti nelle ultime ore.")
        return 1
    articoli = raggruppa_doppioni(articoli)
    pagina = impagina(cfg, articoli, ora)
    pagina["demo"] = args.demo

    if cfg.get("cerca_immagini_nelle_pagine"):
        in_vista = pagina["prima"] + [a for s in pagina["sezioni"] for a in s["articoli"]]
        for a in in_vista:
            if not a.immagine:
                a.immagine = immagine_dalla_pagina(a.link)

    corpo_html = ambiente_template().get_template("email.html.j2").render(**pagina)
    oggetto = f"{pagina['testata']} – {pagina['data_breve']}"

    if args.anteprima:
        Path(args.anteprima).write_text(corpo_html, encoding="utf-8")
        log.info("Anteprima salvata in %s", args.anteprima)
    if args.invia:
        invia(oggetto, corpo_html, testo_semplice(pagina))
    return 0


if __name__ == "__main__":
    sys.exit(main())
