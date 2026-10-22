# 📰 La Rassegna

**Una rassegna stampa in stile giornale, ogni mattina nella tua email. Gratis, open source, senza server.**

La Rassegna legge i feed RSS di testate che scegli tu, ordina le notizie per sezione
(politica, intelligence, terrorismo, guerra ibrida, cyber, tecnologia, scienza…),
mette in prima pagina quelle riprese da più fonti e ti manda un'email impaginata come un
quotidiano, pensata per il telefono.

Accanto a ogni fonte c'è una piccola **scheda**: chi la possiede, come si finanzia, che orientamento ha.
Così sai sempre chi ti sta raccontando la notizia.

<p align="center"><img src="docs/anteprima.png" width="360" alt="Anteprima della rassegna"></p>

*(English: a self-hosted daily news digest. It reads RSS feeds, groups stories by topic, ranks
stories covered by several outlets on the front page and emails a newspaper-style HTML digest.
Runs for free on GitHub Actions.)*

---

## ✨ Cosa fa

- 🗞️ **Impaginazione da giornale**: testata, prima pagina, sezioni, "In breve", "Accadde oggi"
- 🔁 **Niente doppioni**: la stessa notizia da più testate viene unita ("ripresa anche da…")
- 🖼️ **Foto** prese dagli articoli stessi
- 🧭 **Trasparenza sulle fonti**: proprietà e orientamento accanto a ogni articolo
- ⏰ **Automatica**: gira ogni mattina su GitHub Actions, non serve un computer acceso
- 🛠️ **Personale**: scegli argomenti, destinatari, giorni e orario

---

## 🚀 Crea la tua rassegna

1. **Fai il fork** di questo repo: pulsante **Fork** in alto a destra.
2. Clona il tuo fork sul computer, installa i requisiti e avvia la configurazione guidata:

   ```bash
   git clone https://github.com/<il-tuo-utente>/rassegna.git
   cd rassegna
   pip install -r requirements.txt
   python rassegna.py --configura
   ```

   Scegli il nome del giornale, i tuoi argomenti e le relative parole chiave, il fuso orario,
   i giorni e l'ora. Gli articoli che non corrispondono agli argomenti scelti vengono esclusi.
   La procedura aggiorna `preferenze.yaml` e la programmazione GitHub Actions.
   L'indirizzo email viene salvato solo nel file locale `.env`, che non va pubblicato.
3. Pubblica sul tuo fork le impostazioni generate:

   ```bash
   git add preferenze.yaml .github/workflows/rassegna.yml
   git commit -m "Configura la mia rassegna"
   git push
   ```

4. **Crea una password per le app di Gmail**
   (serve la verifica in due passaggi attiva):
   vai su [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords),
   crea una password chiamata "Rassegna" e copia le 16 lettere.
5. Nel tuo fork vai su **Settings → Secrets and variables → Actions → New repository secret**
   e aggiungi:

   | Nome | Valore |
   |---|---|
   | `SMTP_USER` | il tuo indirizzo Gmail |
   | `SMTP_PASSWORD` | la password per le app (16 lettere) |
   | `MAIL_TO` | il tuo indirizzo destinatario (più indirizzi separati da virgola, se vuoi) |

6. Vai su **Actions**, abilita i workflow, apri **Rassegna mattutina** e premi **Run workflow** per inviare una prova.
7. Controlla la posta 📬. Da quel momento riceverai la rassegna nei giorni e all'ora scelti.

> Non usi Gmail? Aggiungi anche `SMTP_HOST` e `SMTP_PORT` del tuo provider
> (es. Outlook: `smtp-mail.outlook.com` e `587`).
> L'indirizzo destinatario e le credenziali SMTP vanno inseriti nei **Secrets** di GitHub,
> mai in `config.yaml` o `preferenze.yaml`.

---

## 🎛️ Personalizzala

La configurazione personale è in **`preferenze.yaml`**:

- `testata` – il nome del tuo giornale
- `giorni_invio` e `ora_invio` – giorni della settimana e ora locale
- `fuso_orario` – nome IANA, ad esempio `Europe/Rome`
- `sezioni` – argomenti personalizzati e parole chiave; sono salvati solo nel tuo fork
  e gli articoli fuori tema vengono filtrati

Puoi rigenerare questi valori in qualsiasi momento con `python rassegna.py --configura`.
Per intervenire manualmente, modifica `preferenze.yaml` e la sezione `schedule` di
`.github/workflows/rassegna.yml`; la procedura guidata aggiorna entrambi e gestisce l'ora
legale/solare. GitHub può ritardare l'avvio del workflow di qualche minuto.

Le fonti RSS e le impostazioni generali restano in **`config.yaml`**:

- **`fonti`** – aggiungi o togli feed RSS e scrivi la loro scheda
- **`sezioni`** – argomenti predefiniti, usati se non ne imposti di personali
- **`max_per_sezione`**, **`ore_indietro`**, **`accadde_oggi`**…

> Le schede delle fonti già presenti sono indicative: verificale e adattale al tuo giudizio.
> La rassegna non usa AI: mostra il testo breve reso disponibile da ciascun feed RSS (fino a
> 600 caratteri) e collega sempre all'articolo originale. La quantità di dettagli dipende
> dalla testata; non vengono scaricati o ripubblicati gli articoli integrali.

---

## 💻 Provarla sul tuo computer

```bash
git clone https://github.com/<il-tuo-utente>/rassegna.git
cd rassegna
pip install -r requirements.txt

# Configura giornale, argomenti, giorni, orario e destinatario
python rassegna.py --configura

# Anteprima con notizie di esempio, funziona anche offline
python rassegna.py --demo --anteprima

# Anteprima con le notizie vere di oggi (apri anteprima.html nel browser)
python rassegna.py --anteprima

# Invio dell'email: copia .env.example in .env, compilalo e poi
python rassegna.py --invia
```

---

## 🧩 Come funziona

```
feed RSS ──► lettura e filtro ultime 24h ──► sezione per parole chiave
        ──► unione doppioni ──► prima pagina (più fonti = più importante)
        ──► foto da og:image ──► template HTML ──► email (SMTP)
```

Tutto è in `rassegna.py` (circa 400 righe, commentate in italiano). Il layout è in
`templates/email.html.j2`.

---

## 🤝 Contribuire

Idee, nuove fonti e correzioni alle schede sono benvenute: apri una *issue* o una *pull request*.

## 📄 Licenza

MIT © 2026 Zeno Borgnino. I contenuti delle notizie appartengono alle rispettive testate:
la rassegna mostra titoli e brevi estratti dei feed RSS e rimanda alla fonte originale,
senza ripubblicare l'articolo integrale né aggirare paywall o limitazioni di accesso.
La disponibilità pubblica di un feed non sostituisce le condizioni d'uso della testata:
prima di aggiungere una fonte, verifica che i suoi termini consentano l'uso previsto.
Le immagini sono caricate dai siti originali e restano soggette ai relativi diritti.
