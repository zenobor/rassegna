# Personal Digest Mail

[![Test Personal Digest Mail](https://github.com/zenobor/rassegna/actions/workflows/tests.yml/badge.svg)](https://github.com/zenobor/rassegna/actions/workflows/tests.yml)

Your own newspaper-style email, built from public RSS feeds. Fork this project, choose
your topics and schedule, add email credentials, and GitHub Actions sends your digest.

Articles include the title and the best available RSS summary (up to 1,800 characters).
Stories without a summary are left out. No article scraping, AI-written details, or
paywall bypass: the detail depends on each publisher's feed.

<p align="center"><img src="docs/anteprima.png" width="360" alt="Personal Digest Mail email preview"></p>

## Set it up

1. Fork this repository on GitHub, then clone your fork:
   ```powershell
   git clone https://github.com/YOUR-USERNAME/rassegna.git
   cd rassegna
   ```
2. Install Python 3.12+ and configure your edition (topics, time zone, days, and time):
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe rassegna.py --configura
   ```
3. Push your settings to your fork:
```powershell
git add preferenze.yaml .github/workflows/rassegna.yml
git commit -m "Set up my digest"
git push
```
4. In **Settings → Secrets and variables → Actions**, add `SMTP_USER`, `SMTP_PASSWORD`,
   and `MAIL_TO`. Gmail requires a [Google App Password](https://myaccount.google.com/apppasswords).
   For other providers, also set `SMTP_HOST` and `SMTP_PORT`. Never commit credentials.

Then open **Actions → Personal Digest Mail → Run workflow** to test delivery.
Automatic emails follow the schedule you selected. GitHub Actions may run a little late.

## Preview and tests

Neither preview command sends email:
```powershell
# Offline sample with fictional stories
.\.venv\Scripts\python.exe rassegna.py --demo --anteprima anteprima-demo.html

# Live RSS preview
.\.venv\Scripts\python.exe rassegna.py --anteprima
```
Run the tests with:
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub also runs these tests automatically on every push and pull request.

## Customize and troubleshoot

- `preferenze.yaml`: topics and delivery schedule. Matching uses article titles and RSS summaries.
- `config.yaml`: RSS sources, sections, article limits, and look-back period.
- `templates/`: email design.
- A feed without a usable summary is skipped; unavailable feeds are reported in the Actions log.
- If no stories match, broaden your keywords or add RSS sources.
- If no email arrives, check the Actions log, spam folder, and SMTP secrets.

## License

MIT © 2026 Zeno Borgnino. RSS excerpts and linked content remain subject to each publisher's terms.
