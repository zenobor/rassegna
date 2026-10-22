# La Rassegna

[![Test della rassegna](https://github.com/zenobor/rassegna/actions/workflows/tests.yml/badge.svg)](https://github.com/zenobor/rassegna/actions/workflows/tests.yml)

La tua rassegna stampa italiana, impaginata come un giornale e spedita per email
all'ora che preferisci. Raccoglie le notizie dai feed RSS di ANSA, Rai News, Il Post,
Sky TG24, Il Sole 24 Ore, la Repubblica e altre testate italiane, tiene solo gli
argomenti che scegli e mette in prima pagina le notizie riprese da più fonti.

È gratuita, funziona interamente su GitHub e **non serve installare nulla**.

<p align="center"><img src="docs/anteprima.png" width="300" alt="Anteprima della rassegna"></p>

## Come attivarla (10 minuti)

**1. Copia il progetto.** Con un account GitHub gratuito, clicca **Fork** in alto a destra
in questa pagina, poi **Create fork**.

**2. Accendi le automazioni.** Nella tua copia apri la scheda **Actions** e clicca
**I understand my workflows, go ahead and enable them**.

**3. Collega la tua email.** Vai in **Settings → Secrets and variables → Actions** e,
con **New repository secret**, aggiungi:

| Nome | Cosa scrivere |
| --- | --- |
| `SMTP_USER` | L'indirizzo Gmail che spedisce la rassegna |
| `SMTP_PASSWORD` | Una [password per le app di Google](https://myaccount.google.com/apppasswords) (serve la verifica in due passaggi). Non la tua password normale! |
| `MAIL_TO` | Facoltativo: chi riceve la rassegna, anche più indirizzi separati da virgola. Se manca, la ricevi tu |

Usi un altro servizio email? Aggiungi anche `SMTP_HOST` e `SMTP_PORT` del tuo provider.

**4. Scegli cosa ricevere.** Apri **Actions → Configura la rassegna → Run workflow**.
Si apre un modulo dove scegli giorni, ora e argomenti:

- **Giorni:** dal lunedì al venerdì, tutti i giorni, oppure solo sabato e domenica
- **Ora:** dalle 05:00 alle 22:00 (ora italiana)
- **Argomenti:** Politica · Esteri · Economia e lavoro · Tecnologia e sicurezza informatica ·
  Scienza e salute · Cultura e spettacoli · Sport · Cronaca

Clicca il pulsante verde **Run workflow** e hai finito. Per cambiare idea in futuro,
ripeti questo passaggio.

**5. Prova subito.** Apri **Actions → Invia la rassegna → Run workflow**: in un paio di
minuti ricevi la prima edizione. Da quel momento arriva da sola nei giorni e all'ora scelti.

## Se qualcosa non va

- **Non è arrivata l'email:** controlla lo spam, poi apri la scheda **Actions** e l'ultima
  esecuzione di "Invia la rassegna". Se è rossa, il messaggio spiega cosa manca (di solito
  i Secrets dell'email).
- **Le email si sono fermate dopo qualche mese:** GitHub sospende le automazioni dei progetti
  senza attività da 60 giorni. Apri **Actions → Invia la rassegna** e clicca
  **Enable workflow**, oppure ripeti "Configura la rassegna".
- **Nella scheda Actions vedi molte esecuzioni brevi:** è normale. Il programma controlla
  ogni ora se è il momento di inviare e, se non lo è, si ferma in meno di un minuto.
- **Una fonte non dà notizie:** ogni esecuzione elenca nel log quante notizie arrivano da
  ciascuna testata. Un feed può cambiare indirizzo: correggilo o toglilo in `config.yaml`.
- Ogni esecuzione salva una copia dell'email, scaricabile per 7 giorni.

## Per chi vuole personalizzare

- `config.yaml` contiene le fonti, le parole chiave di ogni argomento e quante notizie
  mostrare. Le note accanto alle fonti sono indicative: verificale e correggile.
- `templates/` contiene la grafica dell'email.
- Le notizie dei feed tematici (es. ANSA Sport) restano nel loro argomento; quelle dei feed
  generali (es. Il Post) vengono assegnate in base alle parole chiave.
- La rassegna mostra il titolo e il riassunto pubblicato nel feed RSS di ogni testata, con il
  link all'articolo originale. Non copia gli articoli completi e non aggira i paywall.
  Raggruppare le notizie simili non è una verifica dei fatti.

### Provare sul proprio computer

Serve [Python 3.12+](https://www.python.org/downloads/). Su Windows (PowerShell):
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe rassegna.py --demo --anteprima anteprima-demo.html   # esempio offline
.\.venv\Scripts\python.exe rassegna.py --anteprima                              # notizie vere, in anteprima.html
.\.venv\Scripts\python.exe rassegna.py --configura                              # scelte dal terminale
.\.venv\Scripts\python.exe -m unittest discover -s tests -v                    # test
```
Su macOS e Linux usa `python3 -m venv .venv` e `.venv/bin/python` al posto di
`.\.venv\Scripts\python.exe`. Per provare l'invio in locale, copia `.env.example` in `.env`,
compilalo e usa `--invia`. Le anteprime non inviano email.

## Licenza

MIT © 2026 Zeno Borgnino. I riassunti RSS e i contenuti collegati restano soggetti alle
condizioni di ciascun editore.
