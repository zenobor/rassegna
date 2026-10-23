# La Rassegna

[![Test della rassegna](https://github.com/zenobor/rassegna/actions/workflows/tests.yml/badge.svg)](https://github.com/zenobor/rassegna/actions/workflows/tests.yml)

La tua rassegna stampa italiana, impaginata come un giornale e spedita per email
all'ora che preferisci. Raccoglie le notizie dai feed RSS di ANSA, Rai News, Il Post,
Sky TG24, Il Sole 24 Ore, la Repubblica e altre testate italiane, tiene solo gli
argomenti che scegli e mette in prima pagina le notizie riprese da più fonti.

È gratuita e gira su GitHub, quindi le email arrivano anche a computer spento.
Si configura tutta dal terminale, rispondendo a qualche domanda.

<p align="center"><img src="docs/anteprima.png" width="300" alt="Anteprima della rassegna"></p>

## Come attivarla (5 minuti)

Ti servono un account GitHub (gratuito, puoi crearlo durante la configurazione) e un
indirizzo email da cui spedire la rassegna, per esempio Gmail.

**1. Installa Python** da [python.org](https://www.python.org/downloads/) (versione 3.12 o
successiva). Su Windows, durante l'installazione spunta **Add python.exe to PATH**.

**2. Scarica il progetto:** in questa pagina clicca **Code → Download ZIP** ed estrai la cartella.

**3. Apri il terminale nella cartella** (su Windows: tasto destro nella cartella →
**Apri nel terminale**) e lancia:

```
python -m pip install -r requirements.txt
python rassegna.py
```

Su macOS usa `python3` al posto di `python`.

**4. Rispondi alle domande.** Il programma:

- ti fa accedere a GitHub dal browser (e, se manca, installa la GitHub CLI ufficiale);
- crea la tua copia del progetto sul tuo account;
- ti chiede email e password e controlla subito che funzionino;
- ti fa scegliere argomenti, giorni e ora;
- attiva l'invio automatico e ti manda una rassegna di prova.

```
── Passo 2 di 4 · Email ──────────────────────────
Indirizzo email che spedisce la rassegna: mario@gmail.com
Password per le app (mentre scrivi non si vede nulla):
  ✓ Email verificata
Chi riceve la rassegna? [mario@gmail.com]:
```

Con Gmail serve una [password per le app](https://myaccount.google.com/apppasswords)
(richiede la verifica in due passaggi), non la tua password normale: il programma ti
spiega come crearla. La password viene salvata solo nei Secrets cifrati di GitHub, non
sul tuo computer.

**Per cambiare argomenti, orario o email** rilancia `python rassegna.py`: ti propone le
scelte attuali e ti basta premere Invio su quelle che non vuoi cambiare.

<details>
<summary>Preferisci fare tutto dal sito di GitHub, senza terminale?</summary>

1. Clicca **Fork → Create fork** in questa pagina.
2. Nella tua copia apri **Actions** e clicca **I understand my workflows, go ahead and enable them**.
3. In **Settings → Secrets and variables → Actions** aggiungi i secret `SMTP_USER`
   (il tuo Gmail), `SMTP_PASSWORD` (la password per le app) e, se vuoi, `MAIL_TO`
   (chi riceve, più indirizzi separati da virgola). Per altri provider aggiungi
   anche `SMTP_HOST` e `SMTP_PORT`.
4. Apri **Actions → Configura la rassegna → Run workflow** e scegli giorni, ora e argomenti.
5. Apri **Actions → Invia la rassegna → Run workflow** per ricevere subito una prova.

</details>

## Se qualcosa non va

- **Non è arrivata l'email:** controlla lo spam, poi apri la scheda **Actions** e l'ultima
  esecuzione di "Invia la rassegna". Se è rossa, il messaggio spiega cosa manca (di solito
  i Secrets dell'email).
- **Le email si sono fermate dopo qualche mese:** GitHub sospende le automazioni dei progetti
  senza attività da 60 giorni. Apri **Actions → Invia la rassegna** e clicca
  **Enable workflow**, oppure rilancia `python rassegna.py`, che le riattiva.
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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v                    # test
```
Su macOS e Linux usa `python3 -m venv .venv` e `.venv/bin/python` al posto di
`.\.venv\Scripts\python.exe`. Per provare l'invio in locale, copia `.env.example` in `.env`,
compilalo e usa `--invia`. Le anteprime non inviano email.

## Licenza

MIT © 2026 Zeno Borgnino. I riassunti RSS e i contenuti collegati restano soggetti alle
condizioni di ciascun editore.
