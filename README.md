# La Rassegna

[![Test La Rassegna](https://github.com/zenobor/rassegna/actions/workflows/tests.yml/badge.svg)](https://github.com/zenobor/rassegna/actions/workflows/tests.yml)

**A personal, newspaper-style news digest delivered by email.** Each person forks the
project, chooses their topics and schedule, and runs their own copy with GitHub Actions.
There is no shared account or central server.

La Rassegna reads public RSS feeds, groups and deduplicates stories, highlights articles
covered by multiple outlets, and sends a responsive HTML email with links to the original
publishers.

> **What the email contains:** titles and excerpts made available by each RSS feed (up to
> 600 characters), not full articles. The digest does not use AI, bypass paywalls, or
> reproduce full articles. The amount of detail depends on each publisher's feed and
> terms of use.

<p align="center"><img src="docs/anteprima.png" width="360" alt="La Rassegna email preview"></p>

## What you need

- A GitHub account and your own fork of this repository.
- Python 3.12 or newer on your computer for the setup wizard and local previews.
- An email account that allows SMTP sending. Gmail users need 2-Step Verification and
  a [Google App Password](https://myaccount.google.com/apppasswords).

## Set up your personal newspaper

### 1. Fork and clone the repository

Click **Fork** on GitHub. Then clone **your fork** (replace `YOUR-USERNAME`):

```powershell
git clone https://github.com/YOUR-USERNAME/rassegna.git
cd rassegna
```

### 2. Install dependencies and choose your topics

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe rassegna.py --configura
```

The guided setup asks for the newspaper name, time zone, delivery days and local time,
topics, and an optional email address. Enter topics one per line in this format:

```text
Cybersecurity | ransomware, data breach, phishing
Space | NASA, satellite, astronomy
```

Press Enter on an empty topic line to finish; press Enter on the first line to keep the
existing topics. With custom topics enabled, a story is included when its title or RSS
excerpt matches at least one keyword. Add useful alternatives and spelling variants;
sections are checked in order, so put more specific topics first.

The wizard writes:

- `preferenze.yaml`: your newspaper name, topics and schedule. These preferences are
  visible in your fork.
- `.github/workflows/rassegna.yml`: the GitHub Actions schedule, including daylight-saving
  changes for the selected time zone.
- `.env`: only the optional local recipient address. This file is ignored by Git and must
  never be committed.

### 3. Save your preferences on your fork

The wizard runs locally, so publish its generated schedule and preferences:

```powershell
git add preferenze.yaml .github/workflows/rassegna.yml
git commit -m "Configure my newspaper"
git push
```

### 4. Add email credentials to GitHub

In your fork, open **Settings → Secrets and variables → Actions → New repository secret**
and add:

| Secret | Value |
| --- | --- |
| `SMTP_USER` | The account used to send the email (for Gmail, your Gmail address) |
| `SMTP_PASSWORD` | The account's SMTP password; for Gmail, use an App Password |
| `MAIL_TO` | Your recipient address; multiple addresses can be comma-separated |

For a non-Gmail provider, also add `SMTP_HOST` and `SMTP_PORT` using that provider's
documented SMTP settings (for example, Outlook uses `smtp-mail.outlook.com` and port
`587`). The default is Gmail over TLS on port `465`.

Never put SMTP passwords or email addresses in `config.yaml`, `preferenze.yaml`, or a
public commit. If `MAIL_TO` is omitted, mail is sent to `SMTP_USER`.

### 5. Send a test and enable automatic delivery

In your fork, open **Actions**, enable workflows if GitHub asks, select **Rassegna
mattutina**, then click **Run workflow**. Check the run and your inbox. Scheduled delivery
uses the days and local time you chose. GitHub may start a scheduled run a few minutes
late; the program allows for delays of up to 45 minutes.

The repository also runs its automated tests on every push and pull request. Scheduled
email sending is skipped with a notice until `SMTP_USER` and `SMTP_PASSWORD` are set.

## Preview and test locally

These commands do not send any email:

```powershell
# Offline sample with fictional stories; writes anteprima-demo.html
.\.venv\Scripts\python.exe rassegna.py --demo --anteprima anteprima-demo.html

# Live RSS preview; requires an internet connection
.\.venv\Scripts\python.exe rassegna.py --anteprima
```

Open the generated HTML file in a browser. The demo stories and their links are fictional;
the demo banner labels them clearly. The live preview uses the feeds in `config.yaml`.

Run the automated checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile rassegna.py
```

To send an actual email from your own computer, copy `.env.example` to `.env`, enter your
SMTP credentials and recipient, then run:

```powershell
.\.venv\Scripts\python.exe rassegna.py --invia
```

This sends real email; use the preview commands above if you only want to inspect the
layout.

## Customize sources and layout

- `config.yaml`: RSS sources, default topic sections, look-back period, and article limits.
- `preferenze.yaml`: your newspaper name, personal topics, time zone, days, and delivery
  time.
- `templates/email.html.j2` and `templates/_fonte.html.j2`: the HTML email layout.
- `demo/`: fictional RSS feeds used for the offline preview.

To add a source, add its public RSS feed URL, a default section, and an accurate source
description to `config.yaml`. Verify the publisher's terms before using its feed. The
program links readers to original stories; it does not store or republish their full text.

## Troubleshooting

- **No email arrived:** check the Actions run log and spam folder. Confirm `SMTP_USER`,
  `SMTP_PASSWORD`, and `MAIL_TO` are spelled correctly and the provider allows SMTP.
- **“Email non configurata” in Actions:** add `SMTP_USER` and `SMTP_PASSWORD` as repository
  Secrets, then run the workflow again.
- **“Nessuna notizia corrisponde…”:** your topic keywords may be too specific or the feeds
  may not contain a matching story. Add synonyms or review the RSS sources.
- **A feed is unavailable:** the run log identifies unreachable feeds. That feed is skipped;
  the digest can still be sent if other feeds provide stories. RSS availability depends on
  each publisher; try its current public feed URL. A feed with no recent articles is normal.
- **No automatic runs:** scheduled workflows run from the repository's default branch.
  Confirm the workflow is enabled and that your latest preferences and workflow were
  pushed to your fork.

## How it works

```text
RSS feeds → date filter → topic matching → duplicate grouping → newspaper HTML → SMTP email
```

The app is a small Python script. GitHub Actions runs it on GitHub's hosted runner, so
your computer does not need to be on at delivery time. Each fork has its own settings and
email secrets.

## License

MIT © 2026 Zeno Borgnino. Feed excerpts, images, and linked articles remain subject to the
respective publishers' rights and terms. Use only feeds and excerpts in a way permitted
by those terms.
