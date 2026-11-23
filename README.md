# statement-analyzer

Find forgotten subscriptions in your bank statements. Automatically.

Two small Python scripts:

1. **`fetch_statements.py`** — downloads PDF attachments (e.g. Revolut credit-card statements) from Gmail via IMAP.
2. **`analyze_statements.py`** — parses the PDFs plus your bank's CSV export and reports:
   - foreign-currency / abroad transactions,
   - known subscriptions (OpenAI, Netflix, iCloud…),
   - merchants recurring in ≥3 statement months (potential forgotten subscriptions).

## Why the label trick?

Gmail can limit IMAP folders to the **1,000 most recent messages** (*Settings → Forwarding and POP/IMAP → Folder Size Limits*). Older mail then vanishes from IMAP search entirely.

Workaround: create a Gmail **filter** (`from:no-reply@provider.com` → apply label, check *"Also apply filter to matching conversations"*). A label is its own IMAP folder with its own 1,000-message window — and the filter retroactively covers old mail.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env
```

1. Create an **app password**: `myaccount.google.com/apppasswords`
   (requires 2-Step Verification; name it e.g. `statements`)
2. Enable IMAP: Gmail ⚙ → *See all settings* → *Forwarding and POP/IMAP* → *Enable IMAP*.
3. In `.env` set:
   ```
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   GMAIL_USER=you@yourdomain.com
   ```

## Usage

```bash
# download PDFs from the 'revolut' label, newest 50 messages
python fetch_statements.py --label revolut --out statements --limit 50

# analyze PDFs in statements/ + every *.csv in the current dir
python analyze_statements.py --pdfs statements --csv mybank_export.csv
```

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--label` | `revolut` | Gmail label = IMAP folder to read |
| `--out` | `statements` | where PDFs land |
| `--limit` | `50` | N most recent messages (by Date) |
| `--query` | `ALL` | IMAP SEARCH criterion |
| `--pdfs` | `statements` | directory of statement PDFs |
| `--pattern` | `*statement*.pdf` | glob for statement PDFs |
| `--csv` | all `*.csv` | bank CSV export(s) |

## Bank formats

- **PDF**: tuned for Revolut credit-card statements (`Date Description amount PLN balance PLN` + `Revolut Rate` FX lines + `To:` merchant lines). Other issuers will need small regex tweaks in `parse_revolut_pdf()`.
- **CSV**: tuned for mBank's Polish `lista operacji` export (see FORMAT NOTES in `parse_bank_csv()`). Other banks need adaptation.

## Security

- Keep `.env` local — it's in `.gitignore`. Revoke the app password at `myaccount.google.com/apppasswords` when done.
- Statements contain sensitive data: keep them local, don't commit them, and anonymize before sharing output or feeding to cloud LLMs.
- The fetcher uses `readonly=True` — your mailbox is never modified.

## License

MIT — see [LICENSE](LICENSE).
