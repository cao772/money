"""Local-only experiment queue. No external operations or approval authority."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY,
 title TEXT NOT NULL,
 acceptance TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','prepared','blocked')),
 worker TEXT,
 evidence TEXT,
 blocker TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 task_id TEXT NOT NULL REFERENCES tasks(id),
 action TEXT NOT NULL,
 at TEXT NOT NULL,
 detail TEXT NOT NULL
);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db

def require(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must not be blank")
    return value.strip()

def event(db, task_id, action, detail):
    db.execute("INSERT INTO events(task_id, action, at, detail) VALUES(?,?,?,?)",
               (task_id, action, now(), detail))

def enqueue(db, task_id, title, acceptance):
    task_id = require(task_id, "id")
    title = require(title, "title")
    acceptance = require(acceptance, "acceptance")
    stamp = now()
    with db:
        cur = db.execute(
            "INSERT INTO tasks(id,title,acceptance,status,created_at,updated_at) "
            "VALUES(?,?,?,'queued',?,?) ON CONFLICT(id) DO NOTHING",
            (task_id, title, acceptance, stamp, stamp))
        if cur.rowcount:
            event(db, task_id, "enqueue", "")
            return True
        old = db.execute("SELECT title, acceptance FROM tasks WHERE id=?", (task_id,)).fetchone()
        if tuple(old) != (title, acceptance):
            raise ValueError("task id already exists with different content")
        return False

def claim(db, worker):
    worker = require(worker, "worker")
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if row is None:
            return None
        task_id = row["id"]
        db.execute("UPDATE tasks SET status='running',worker=?,updated_at=? WHERE id=?",
                   (worker, now(), task_id))
        event(db, task_id, "claim", worker)
        return dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

def finish(db, task_id, worker, evidence, blocker=None):
    worker = require(worker, "worker")
    evidence = require(evidence, "evidence")
    status = "blocked" if blocker is not None else "prepared"
    if blocker is not None:
        blocker = require(blocker, "blocker")
    with db:
        cur = db.execute(
            "UPDATE tasks SET status=?,evidence=?,blocker=?,updated_at=? "
            "WHERE id=? AND status='running' AND worker=?",
            (status, evidence, blocker, now(), task_id, worker))
        if cur.rowcount != 1:
            raise ValueError("task is not running for this worker")
        event(db, task_id, status, json.dumps({"evidence": evidence, "blocker": blocker}, ensure_ascii=False))

def rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY created_at,id")]

def report(db):
    tasks = rows(db)
    counts = {s: 0 for s in ("queued", "running", "prepared", "blocked")}
    for t in tasks:
        counts[t["status"]] += 1
    return {"generated_at": now(), "task_counts": counts,
            "blocked": [t for t in tasks if t["status"] == "blocked"],
            "prepared": [t for t in tasks if t["status"] == "prepared"],
            "actual_revenue": None, "actual_cost": None,
            "note": "Task states are not publication, sales, settlement, or proof of income."}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=".local/money.db")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    add = sub.add_parser("enqueue")
    add.add_argument("id")
    add.add_argument("--title", required=True)
    add.add_argument("--acceptance", required=True)
    c = sub.add_parser("claim")
    c.add_argument("--worker", required=True)
    for cmd in ("finish", "block"):
        f = sub.add_parser(cmd)
        f.add_argument("id")
        f.add_argument("--worker", required=True)
        f.add_argument("--evidence", required=True)
        if cmd == "block":
            f.add_argument("--reason", required=True)
    sub.add_parser("list")
    sub.add_parser("report")
    a = p.parse_args()
    db = connect(a.db)
    try:
        if a.cmd == "init":
            result = {"initialized": True}
        elif a.cmd == "enqueue":
            result = {"created": enqueue(db, a.id, a.title, a.acceptance)}
        elif a.cmd == "claim":
            result = claim(db, a.worker)
        elif a.cmd in ("finish", "block"):
            finish(db, a.id, a.worker, a.evidence, getattr(a, "reason", None))
            result = {"id": a.id, "status": "blocked" if a.cmd == "block" else "prepared"}
        elif a.cmd == "list":
            result = rows(db)
        else:
            result = report(db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error) as exc:
        p.exit(2, str(exc) + "\n")
    finally:
        db.close()

if __name__ == "__main__":
    main()
