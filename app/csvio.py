"""CSV export and import (with a preview step)."""
import csv
import datetime
import io
from decimal import Decimal, InvalidOperation

from .models import MAX_AMOUNT, MIN_AMOUNT, MIN_DATE, Transaction
from .services import q2, suggest_category

HEADER = ["date", "type", "name", "category", "amount", "payee", "account", "tags", "note"]
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
MAX_ROWS = 1000
MAX_BYTES = 512 * 1024


def safe_cell(value):
    """Neutralise spreadsheet formulas by prefixing risky text with an apostrophe."""
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def unsafe_cell(value):
    """Reverse safe_cell for values we exported ourselves."""
    if len(value) > 1 and value[0] == "'" and value[1] in "=+-@":
        return value[1:]
    return value


class Echo:
    def write(self, value):
        return value


def export_lines(queryset, bom=True):
    """Yield CSV text chunks for a streaming response."""
    writer = csv.writer(Echo())
    if bom:
        yield "﻿"
    yield writer.writerow(HEADER)
    for tx in queryset.iterator(chunk_size=500):
        yield writer.writerow([
            tx.date.isoformat(), tx.kind, safe_cell(tx.name), safe_cell(tx.category.name),
            f"{tx.amount:.2f}", safe_cell(tx.payee), safe_cell(tx.account.name if tx.account else ""),
            safe_cell("; ".join(t.name for t in tx.tags.all())), safe_cell(tx.note),
        ])


def _decode(raw):
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None


class CsvImportError(Exception):
    """A problem with the file as a whole (not a single row)."""


def parse(raw, user):
    """Parse CSV bytes into a list of row dicts, each with ``errors`` and ``duplicate`` flags."""
    if len(raw) > MAX_BYTES:
        raise CsvImportError("The file is too large (limit 512 KB).")
    text = _decode(raw)
    if text is None:
        raise CsvImportError("Could not read the file. Save it as UTF-8 CSV.")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise CsvImportError("The file is empty.")
    fields = {(f or "").strip().lower(): f for f in reader.fieldnames}
    missing = [h for h in ("date", "type", "name", "amount") if h not in fields]
    if missing:
        raise CsvImportError("Missing column(s): " + ", ".join(missing) + ". Expected: " + ", ".join(HEADER) + ".")

    categories = {c.name.lower(): c for c in user.categories.all()}
    accounts = {a.name.lower(): a for a in user.accounts.all()}
    existing = {
        (t.date, t.kind, t.name.lower(), t.category.name.lower(), t.amount)
        for t in Transaction.objects.filter(user=user).select_related("category")
    }
    seen = set()
    rows = []
    for number, raw_row in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise CsvImportError(f"Too many rows (limit {MAX_ROWS}).")
        def get(key):
            return unsafe_cell((raw_row.get(fields[key]) or "").strip()) if key in fields else ""

        if not any((v or "").strip() for v in raw_row.values() if isinstance(v, str)):
            continue
        errors = []
        row = {"line": number, "name": get("name"), "category": get("category"), "note": get("note"),
               "kind": get("type").lower(), "date": None, "amount": None,
               "payee": get("payee"), "account": get("account"),
               "tags": [t.strip() for t in get("tags").split(";") if t.strip()]}
        try:
            row["date"] = datetime.date.fromisoformat(get("date"))
            if row["date"] < MIN_DATE or row["date"] > datetime.date.today() + datetime.timedelta(days=1):
                errors.append("Date is out of range.")
        except ValueError:
            errors.append("Date must look like 2025-03-31.")
        if row["kind"] not in ("income", "expense"):
            errors.append("Type must be income or expense.")
        try:
            amount = Decimal(get("amount").replace(",", ""))
            if not amount.is_finite() or amount < MIN_AMOUNT or amount > MAX_AMOUNT or amount != q2(amount):
                raise InvalidOperation
            row["amount"] = q2(amount)
        except InvalidOperation:
            errors.append("Amount must be a positive number with at most 2 decimals.")
        if not row["name"] or len(row["name"]) > 120:
            errors.append("Name is required (max 120 characters).")
        if len(row["payee"]) > 80:
            errors.append("Payee is too long (max 80 characters).")
        if row["account"] and row["account"].lower() not in accounts:
            errors.append(f"Unknown account \u201c{row['account']}\u201d.")
        if len(row["tags"]) > 10 or any(len(t) > 30 for t in row["tags"]):
            errors.append("Use at most 10 tags of up to 30 characters.")
        row["rule_matched"] = False
        if not row["category"] and row["kind"] in ("income", "expense"):
            guess = suggest_category(user, f"{row['name']} {row['payee']}", row["kind"])
            if guess:
                row["category"] = guess.name
                row["rule_matched"] = True
        if not row["category"] or len(row["category"]) > 50:
            errors.append("Category is required (max 50 characters) unless a rule matches the description.")
        if len(row["note"]) > 1000:
            errors.append("Note is too long.")
        cat = categories.get(row["category"].lower())
        if cat and row["kind"] in ("income", "expense") and not cat.accepts(row["kind"]):
            errors.append(f"Category “{cat.name}” cannot be used for {row['kind']}.")
        row["new_category"] = bool(row["category"]) and cat is None
        row["errors"] = errors
        row["duplicate"] = False
        if not errors:
            key = (row["date"], row["kind"], row["name"].lower(), row["category"].lower(), row["amount"])
            row["duplicate"] = key in existing or key in seen
            seen.add(key)
        rows.append(row)
    if not rows:
        raise CsvImportError("The file has no data rows.")
    return rows


def serialise(rows):
    return [
        {**r, "date": r["date"].isoformat() if r["date"] else None,
         "amount": str(r["amount"]) if r["amount"] is not None else None}
        for r in rows
    ]


def deserialise(rows):
    return [
        {**r, "date": datetime.date.fromisoformat(r["date"]) if r["date"] else None,
         "amount": Decimal(r["amount"]) if r["amount"] is not None else None}
        for r in rows
    ]
