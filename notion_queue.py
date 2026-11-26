"""Exchange private action cards and evidence with an authorized Notion connector."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

import money


SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_cards (
    task_id TEXT PRIMARY KEY REFERENCES tasks(id),
    page_id TEXT NOT NULL,
    card TEXT NOT NULL,
    confirmed_receipt TEXT,
    confirmed_at TEXT
);
"""


def load_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def page_id(value):
    try:
        return str(UUID(money.require(value, "page_id")))
    except ValueError as exc:
        raise ValueError("expected a Notion page UUID") from exc


def import_card(db, card):
    if not isinstance(card, dict):
        raise ValueError("expected an action card object")
    card = dict(card)
    card["page_id"] = page_id(card.get("page_id"))
    for name in ("task_id", "opportunity_id", "title", "acceptance"):
        card[name] = money.require(card.get(name), name)
    task_id = card["task_id"]
    encoded = json.dumps(card, ensure_ascii=False, sort_keys=True)
    with db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT card FROM notion_cards WHERE task_id=?", (task_id,)).fetchone()
        if prior:
            if prior["card"] != encoded:
                raise ValueError("task already exists with a different action card")
            return {"task_id": task_id, "created": False}
        if not money.insert_task(db, task_id, card["title"], card["acceptance"]):
            raise ValueError("task id already belongs to a local task")
        db.execute("INSERT INTO notion_cards(task_id,page_id,card) VALUES(?,?,?)",
                   (task_id, card["page_id"], encoded))
        return {"task_id": task_id, "created": True}


def receipt(db, task_id):
    task = db.execute(
        "SELECT t.status,t.updated_at,t.evidence,t.blocker,c.page_id,c.confirmed_receipt "
        "FROM tasks t JOIN notion_cards c ON c.task_id=t.id WHERE t.id=?", (task_id,)).fetchone()
    if not task or task["status"] not in ("prepared", "blocked"):
        raise ValueError("a finished or blocked imported task is required")
    body = "\n".join((task_id, task["status"], task["updated_at"], task["evidence"]))
    if task["blocker"]:
        body += "\n" + task["blocker"]
    digest = hashlib.sha256(body.encode()).hexdigest()
    marker = "Venture receipt " + digest
    return {
        "marker": marker,
        "confirmed": task["confirmed_receipt"] == digest,
        "request": {
            "page_id": task["page_id"], "command": "insert_content", "position": {"type": "end"},
            "content": body + "\n\n" + marker,
        },
    }


def confirm(db, task_id, snapshot):
    """Confirm only after the connector has read the receipt back from the mapped page."""
    item = receipt(db, task_id)
    target = item["request"]["page_id"]
    if not isinstance(snapshot, dict) or page_id(snapshot.get("id")) != target:
        raise ValueError("receipt readback came from a different page")
    body = money.require(snapshot.get("text"), "page text")
    if item["marker"] not in body:
        raise ValueError("receipt marker is missing from the remote page")
    digest = item["marker"].split()[-1]
    with db:
        db.execute("UPDATE notion_cards SET confirmed_receipt=?,confirmed_at=? "
                   "WHERE task_id=? AND confirmed_receipt IS NOT ?",
                   (digest, money.now(), task_id, digest))
    return {"task_id": task_id, "confirmed": True}


def open_db(path, dry_run):
    if not dry_run:
        db = money.connect(path)
    else:
        db = money.connect(":memory:")
        if Path(path).is_file():
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as original:
                original.backup(db)
    db.executescript(SCHEMA)
    return db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".local/money.db")
    commands = parser.add_subparsers(dest="cmd", required=True)
    add = commands.add_parser("import")
    add.add_argument("card", help="private JSON action card")
    add.add_argument("--dry-run", action="store_true")
    emit = commands.add_parser("receipt")
    emit.add_argument("id")
    ack = commands.add_parser("confirm")
    ack.add_argument("id")
    ack.add_argument("snapshot", help="private JSON containing the fetched page's id and text")
    args = parser.parse_args()
    try:
        with closing(open_db(args.db, getattr(args, "dry_run", False))) as db:
            if args.cmd == "import":
                result = import_card(db, load_json(args.card))
                result["dry_run"] = args.dry_run
            elif args.cmd == "receipt":
                result = receipt(db, args.id)
            else:
                result = confirm(db, args.id, load_json(args.snapshot))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
