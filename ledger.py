"""Reconciled provider statements. Amounts are in original currency, stored in minor units."""
import datetime
import json
import re
from decimal import Decimal
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
 id TEXT PRIMARY KEY, account TEXT NOT NULL, currency TEXT NOT NULL,
 starts TEXT NOT NULL, ends TEXT NOT NULL, sales INTEGER NOT NULL,
 refunds INTEGER NOT NULL, fees INTEGER NOT NULL, expenses INTEGER NOT NULL,
 payout INTEGER, evidence TEXT NOT NULL, payout_evidence TEXT
);
"""
CURRENCIES = {"CNY", "EUR", "USD"}


def label(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must be provided")
    return value.strip()


def minor(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,13}(\.[0-9]{1,2})?", value):
        raise ValueError(field + " must be a non-negative decimal string with at most two decimals")
    return int(Decimal(value) * 100)


def record(db, data):
    if not isinstance(data, dict):
        raise ValueError("expected a reconciled statement object")
    ident, account = label(data, "id"), label(data, "account")
    currency = label(data, "currency").upper()
    if currency not in CURRENCIES:
        raise ValueError("supported currencies: CNY, EUR, USD")
    start, end = [datetime.date.fromisoformat(label(data, k)).isoformat() for k in ("starts", "ends")]
    if start > end:
        raise ValueError("statement ends before it starts")
    amounts = [minor(data, k) for k in ("sales", "refunds", "fees", "expenses")]
    payout = None if data.get("payout") is None else minor(data, "payout")
    if payout is None and data.get("payout_evidence") is not None:
        raise ValueError("payout evidence requires a payout amount")
    values = (ident, account, currency, start, end, *amounts, payout, label(data, "evidence"),
              None if payout is None else label(data, "payout_evidence"))
    with db:
        db.execute("BEGIN IMMEDIATE")
        columns = "id,account,currency,starts,ends,sales,refunds,fees,expenses,payout,evidence,payout_evidence"
        prior = db.execute("SELECT " + columns + " FROM statements WHERE id=?", (ident,)).fetchone()
        if prior:
            if tuple(prior) != values:
                raise ValueError("statement id conflicts with an existing record")
            return False
        occupied = db.execute("SELECT id FROM statements WHERE account=? AND currency=? "
                              "AND starts<=? AND ends>=?", (account, currency, end, start)).fetchone()
        if occupied:
            raise ValueError("overlapping period for this account and currency")
        db.execute("INSERT INTO statements (" + columns + ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", values)
        return True


def import_file(db, filename):
    with Path(filename).open(encoding="utf-8") as source:
        return {"created": record(db, json.load(source))}


def amount(minor_units):
    sign = "-" if minor_units < 0 else ""
    whole, fraction = divmod(abs(minor_units), 100)
    return f"{sign}{whole}.{fraction:02}"


def summary(db):
    totals = {}
    for row in db.execute("SELECT currency,sales,refunds,fees,expenses,payout FROM statements"):
        cur, sales, refunds, fees, expenses, payout = row
        group = totals.setdefault(cur, {"statements": 0, "sales": 0, "refunds": 0, "fees": 0,
                                       "expenses": 0, "payout": 0, "payouts_known": 0})
        group["statements"] += 1
        group["sales"] += sales
        group["refunds"] += refunds
        group["fees"] += fees
        group["expenses"] += expenses
        if payout is not None:
            group["payouts_known"] += 1
            group["payout"] += payout
    result = {"actual_revenue": None, "actual_cost": None, "net_profit": None, "by_currency": {}}
    for currency, group in sorted(totals.items()):
        revenue = group["sales"] - group["refunds"]
        cost = group["fees"] + group["expenses"]
        for name, value in (("actual_revenue",revenue), ("actual_cost",cost), ("net_profit",revenue-cost)):
            if result[name] is None:
                result[name] = {}
            result[name][currency] = amount(value)
        detail = {k: amount(group[k]) for k in ("sales", "refunds", "fees", "expenses")}
        detail["statements"] = group["statements"]
        detail["settled"] = amount(group["payout"]) if group["payouts_known"] == group["statements"] else None
        result["by_currency"][currency] = detail
    return result
