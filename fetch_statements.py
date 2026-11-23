#!/usr/bin/env python3
"""Download PDF statement attachments from Gmail via IMAP.

Uses a Gmail label (which appears as an IMAP folder) to work around Gmail's
1,000-messages-per-folder IMAP limit. See README for setup steps.

Requires env vars (or a local .env file):
    GMAIL_USER           - your Gmail / Google Workspace address
    GMAIL_APP_PASSWORD   - a 16-char app password (myaccount.google.com/apppasswords)
"""

import argparse
import email
import imaplib
import os
import re
import sys
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path

IMAP_HOST = "imap.gmail.com"
ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env():
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "GMAIL_USER":
                user = user or v
            elif k == "GMAIL_APP_PASSWORD":
                password = password or v
    return user, password.replace(" ", "") if password else None


def decode_str(s):
    if not s:
        return ""
    out = []
    for text, enc in decode_header(s):
        out.append(text.decode(enc or "utf-8", "replace") if isinstance(text, bytes) else text)
    return "".join(out)


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def main():
    ap = argparse.ArgumentParser(description="Download PDF attachments from a Gmail label.")
    ap.add_argument("--label", default="revolut",
                    help="Gmail label / IMAP folder to read (default: revolut)")
    ap.add_argument("--out", default="statements",
                    help="output directory for PDFs (default: statements/)")
    ap.add_argument("--limit", type=int, default=50,
                    help="process the N most recent messages (default: 50)")
    ap.add_argument("--query", default="ALL",
                    help="IMAP SEARCH criterion (default: ALL)")
    args = ap.parse_args()

    user, password = load_env()
    if not user or not password:
        sys.exit("Set GMAIL_USER and GMAIL_APP_PASSWORD in .env or the environment")

    out_dir = Path(args.out)
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(user, password)

    typ, _ = mail.select(f'"{args.label}"', readonly=True)
    if typ != "OK":
        sys.exit(f"Label '{args.label}' not found as an IMAP folder. "
                 "Check Gmail settings or the label name.")
    typ, data = mail.search(None, args.query)
    if typ != "OK":
        sys.exit("IMAP search failed")
    ids = data[0].split()
    print(f"{len(ids)} messages found in label '{args.label}'")

    if args.limit:
        # UIDs in Gmail label folders are not reliably date-ordered,
        # so fetch headers first and pick the newest by Date.
        dated = []
        for num in ids:
            t, md = mail.fetch(num, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
            try:
                dt = parsedate_to_datetime(email.message_from_bytes(md[0][1]).get("Date"))
            except Exception:
                dt = None
            dated.append((dt, num))
        dated.sort(key=lambda x: x[0].timestamp() if x[0] else 0, reverse=True)
        ids = [num for _, num in dated[: args.limit]]
        print(f"Processing {len(ids)} most recent messages")

    saved = skipped = 0
    for num in ids:
        typ, msg_data = mail.fetch(num, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        subject = decode_str(msg.get("Subject"))
        try:
            date_tag = parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m")
        except Exception:
            date_tag = "unknown"

        for part in msg.walk():
            disp = part.get_content_disposition()
            fname = decode_str(part.get_filename())
            if disp != "attachment" and not fname:
                continue
            if part.get_content_type() != "application/pdf" and not fname.lower().endswith(".pdf"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{date_tag}_{safe_name(fname) if fname else 'statement.pdf'}"
            if out.exists():
                skipped += 1
                continue
            out.write_bytes(payload)
            saved += 1
            print(f"saved: {out.name}  <- {subject}")

    mail.logout()
    print(f"\nDone: {saved} new PDFs, {skipped} already existed.")


if __name__ == "__main__":
    main()
