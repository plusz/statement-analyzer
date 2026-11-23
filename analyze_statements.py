#!/usr/bin/env python3
"""Analyze bank statement PDFs (e.g. Revolut credit card) and bank CSV exports.

Flags: foreign-currency transactions, known subscriptions, and merchants that
recur across >= 3 statement months (potential forgotten subscriptions).

Note: the CSV parser is built for mBank's Polish export format. Other banks
will need small adaptations - see parse_bank_csv() and FORMAT NOTES there.
"""

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber

# Known subscription / online service merchants (lowercase substrings)
SUBSCRIPTIONS = [
    "openai", "anthropic", "claude", "chatgpt", "perplexity", "mistral", "elevenlabs",
    "netflix", "spotify", "youtube", "disney", "hbo", "player.pl", "canal",
    "amazon", "aws", "google cloud", "google ads", "google one", "google *",
    "apple", "itunes", "microsoft", "office365", "github", "gitlab", "jetbrains",
    "atlassian", "windsurf", "cursor", "notion", "figma", "canva", "dropbox", "icloud",
    "linkedin", "deepl", "grammarly", "zoom", "slack", "nordvpn", "expressvpn", "surfshark",
    "bunny.net", "twilio", "cloudflare", "digitalocean", "heroku", "vercel", "netlify",
    "medium", "substack", "patreon", "adobe", "playstation", "xbox", "nintendo", "steam",
    "make.com", "openrouter", "huggingface", "replicate", "supabase",
]

DATE_RE = re.compile(r"^([A-Z][a-z]{2} \d{1,2}, \d{4})\s+(.*)$")
AMOUNT_RE = re.compile(r"([\d,]+\.\d{2}) PLN")
# The foreign-currency amount sits at the END of the "Revolut Rate" line
RATE_RE = re.compile(r"Revolut Rate.*?\s([€$£])\s*([\d,]+\.\d{2})\s*$")
TO_RE = re.compile(r"^To:\s*(.*)$")


def parse_revolut_pdf(path):
    """Extract transactions from a Revolut credit-card statement PDF."""
    txns = []
    current = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[1:]:
            for line in (page.extract_text() or "").split("\n"):
                line = line.strip()
                m = DATE_RE.match(line)
                if m:
                    amounts = AMOUNT_RE.findall(m.group(2))
                    desc = AMOUNT_RE.sub("", m.group(2)).strip().rstrip("-").strip()
                    if amounts:
                        current = {
                            "date": m.group(1),
                            "desc": desc,
                            "amount": float(amounts[0].replace(",", "")),
                            "foreign": None,
                            "to": "",
                            "src": path.name,
                        }
                        txns.append(current)
                        continue
                if current is None:
                    continue
                r = RATE_RE.search(line)
                if r:
                    current["foreign"] = f"{r.group(1)}{r.group(2)}"
                t = TO_RE.match(line)
                if t:
                    current["to"] = t.group(1).strip()
    return txns


def parse_bank_csv(path):
    """Parse mBank's 'lista operacji' CSV export.

    FORMAT NOTES (mBank Polish retail export):
      - skip preamble lines until the header '#Data operacji;#Opis operacji;...'
      - columns: date; description; account; category; amount ('-132,69 PLN')
      - card ops embed a type suffix, e.g. 'ZAKUP PRZY UZYCIU KARTY - INTERNET',
        'ZAKUP PRZY UZYCIU KARTY W KRAJU', 'ZAKUP PRZY UZYCIU KARTY ZA GRANICA'
      - amounts use a comma decimal separator and space thousands separator
    """
    txns = []
    started = False
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f, delimiter=";"):
            if not row:
                continue
            if row[0].startswith("#Data operacji"):
                started = True
                continue
            if not started or not re.match(r"^\d{4}-\d{2}-\d{2}$", row[0]):
                continue
            desc = re.sub(r"\s+", " ", row[1]).strip()
            kwota = row[4].strip() if len(row) > 4 else ""
            m = re.match(r"(-?[\d ]+,\d{2}) PLN", kwota)
            amount = float(m.group(1).replace(" ", "").replace(",", ".")) if m else None
            mt = re.search(r"(ZAKUP PRZY UŻYCIU KARTY[^\"]*|ZA GRANICĄ|PRZELEW \w+)", desc)
            typ = mt.group(1).strip() if mt else ""
            merch = re.split(r"\s{2,}| ZAKUP PRZY| PRZELEW ", desc)[0].strip()
            txns.append({
                "date": row[0], "desc": merch, "amount": amount,
                "typ": typ, "src": path.name,
            })
    return txns


def is_subscription(desc):
    d = (desc or "").lower()
    return next((s for s in SUBSCRIPTIONS if s.rstrip("*") in d), None)


def main():
    ap = argparse.ArgumentParser(description="Analyze statement PDFs and bank CSVs.")
    ap.add_argument("--pdfs", default="statements", help="directory with *statement*.pdf files")
    ap.add_argument("--csv", nargs="*", default=None,
                    help="bank CSV export(s); default: all *.csv in current dir")
    ap.add_argument("--pattern", default="*statement*.pdf", help="glob for statement PDFs")
    args = ap.parse_args()

    rev_txns = []
    for pdf in sorted(Path(args.pdfs).glob(args.pattern)):
        rev_txns += parse_revolut_pdf(pdf)

    csv_files = [Path(p) for p in args.csv] if args.csv else sorted(Path(".").glob("*.csv"))
    mb_txns = []
    for f in csv_files:
        mb_txns += parse_bank_csv(f)

    # --- A: foreign currency / abroad ---
    print("=" * 80)
    print("A. FOREIGN-CURRENCY / ABROAD TRANSACTIONS")
    print("=" * 80)
    print("\n-- PDF statements (foreign currency) --")
    for t in rev_txns:
        if t["foreign"]:
            print(f"  {t['date']:14} {t['desc'][:40]:40} {t['amount']:>10.2f} PLN  ({t['foreign']})  -> {t['to'][:40]}")
    print("\n-- Bank CSV (marked abroad) --")
    for t in mb_txns:
        if "ZA GRANIC" in (t["typ"] or "").upper():
            print(f"  {t['date']} {t['desc'][:50]:50} {t['amount']:>10.2f} PLN")

    # --- B: known subscriptions ---
    print("\n" + "=" * 80)
    print("B. SUBSCRIPTIONS / ONLINE SERVICES (known list)")
    print("=" * 80)
    sub_map = defaultdict(lambda: {"count": 0, "total": 0.0, "months": set(), "examples": []})
    for t in rev_txns:
        if t["desc"].startswith("To ") or not t["amount"]:
            continue
        if is_subscription(t["desc"]) or is_subscription(t["to"]):
            k = t["desc"].strip()
            sub_map[k]["count"] += 1
            sub_map[k]["total"] += t["amount"]
            sub_map[k]["months"].add(t["date"].split(",")[0][:3] + " " + t["date"][-4:])
            if len(sub_map[k]["examples"]) < 3:
                sub_map[k]["examples"].append(f"{t['date']} {t['amount']:.2f}PLN ({t['src'][:20]})")
    for t in mb_txns:
        if t["amount"] is None or t["amount"] >= 0:
            continue
        if is_subscription(t["desc"]):
            k = t["desc"]
            sub_map[k]["count"] += 1
            sub_map[k]["total"] += abs(t["amount"])
            sub_map[k]["months"].add(t["date"][:7])
            if len(sub_map[k]["examples"]) < 3:
                sub_map[k]["examples"].append(f"{t['date']} {abs(t['amount']):.2f}PLN (csv)")

    for k in sorted(sub_map, key=lambda x: -sub_map[x]["total"]):
        v = sub_map[k]
        print(f"\n  {k[:45]:45} x{v['count']:>3}  total {v['total']:>10.2f} PLN  ({len(v['months'])} mo: {sorted(v['months'])})")
        for e in v["examples"]:
            print(f"      {e}")

    # --- C: recurring merchants ---
    print("\n" + "=" * 80)
    print("C. RECURRING MERCHANTS (>=3 months, PDFs, not on subscription list)")
    print("=" * 80)
    merch = defaultdict(lambda: {"count": 0, "total": 0.0, "months": set()})
    for t in rev_txns:
        if t["desc"].startswith("To ") or not t["amount"] or is_subscription(t["desc"]):
            continue
        k = t["desc"].strip()
        merch[k]["count"] += 1
        merch[k]["total"] += t["amount"]
        merch[k]["months"].add(t["date"].split(",")[0][:3] + " " + t["date"][-4:])
    for k in sorted(merch, key=lambda x: (-len(merch[x]["months"]), -merch[x]["total"])):
        v = merch[k]
        if len(v["months"]) >= 3:
            print(f"  {k[:50]:50} x{v['count']:>3}  {len(v['months'])} mo.  total {v['total']:>10.2f} PLN")

    print(f"\n\nPDF transactions: {len(rev_txns)}, CSV transactions: {len(mb_txns)}")


if __name__ == "__main__":
    main()
