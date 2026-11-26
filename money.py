"""Local-only experiment queue. No external operations or approval authority."""
import argparse
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ledger

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
CREATE TABLE IF NOT EXISTS leases (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id),
 token TEXT NOT NULL,
 expires_at TEXT NOT NULL
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
    db.executescript(SCHEMA + ledger.SCHEMA)
    return db

def require(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must not be blank")
    return value.strip()

def event(db, task_id, action, detail):
    db.execute("INSERT INTO events(task_id, action, at, detail) VALUES(?,?,?,?)",
               (task_id, action, now(), detail))

def enqueue(db, task_id, title, acceptance):
    with db:
        return insert_task(db, task_id, title, acceptance)

def insert_task(db, task_id, title, acceptance):
    """Insert inside the caller's transaction, including the audit event."""
    task_id = require(task_id, "id")
    title = require(title, "title")
    acceptance = require(acceptance, "acceptance")
    stamp = now()
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

def claim(db, worker, task_id=None, lease_minutes=None):
    worker = require(worker, "worker")
    if lease_minutes is not None and not 1 <= lease_minutes <= 10080:
        raise ValueError("lease duration must be between 1 and 10080 minutes")
    with db:
        db.execute("BEGIN IMMEDIATE")
        stamp = datetime.now(timezone.utc)
        row = db.execute(
            "SELECT t.id FROM tasks t LEFT JOIN leases l ON l.task_id=t.id "
            "WHERE (? IS NULL OR t.id=?) AND (t.status='queued' OR "
            "(? IS NOT NULL AND t.status='running' AND l.expires_at<=?)) "
            "ORDER BY t.created_at,t.id LIMIT 1",
            (task_id, task_id, lease_minutes, stamp.isoformat())).fetchone()
        if row is None:
            return None
        task_id = row["id"]
        db.execute("UPDATE tasks SET status='running',worker=?,updated_at=? WHERE id=?",
                   (worker, now(), task_id))
        event(db, task_id, "claim", worker)
        task = dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        if lease_minutes is not None:
            token = secrets.token_hex(16)
            expires = (stamp + timedelta(minutes=lease_minutes)).isoformat()
            db.execute("INSERT OR REPLACE INTO leases(task_id,token,expires_at) VALUES(?,?,?)",
                       (task_id, token, expires))
            task.update(lease_token=token, lease_expires_at=expires)
        return task

def finish(db, task_id, worker, evidence, blocker=None, lease_token=None):
    worker = require(worker, "worker")
    evidence = require(evidence, "evidence")
    status = "blocked" if blocker is not None else "prepared"
    if blocker is not None:
        blocker = require(blocker, "blocker")
    with db:
        db.execute("BEGIN IMMEDIATE")
        lease = db.execute("SELECT token,expires_at FROM leases WHERE task_id=?", (task_id,)).fetchone()
        if lease and (lease["token"] != lease_token or lease["expires_at"] <= now()):
            raise ValueError("a current lease token is required")
        cur = db.execute(
            "UPDATE tasks SET status=?,evidence=?,blocker=?,updated_at=? "
            "WHERE id=? AND status='running' AND worker=?",
            (status, evidence, blocker, now(), task_id, worker))
        if cur.rowcount != 1:
            raise ValueError("task is not running for this worker")
        db.execute("DELETE FROM leases WHERE task_id=?", (task_id,))
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
            **ledger.summary(db),
            "note": "Financial totals cover reconciled statements in their original currencies."}

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
    c.add_argument("--id", help="only claim this task")
    c.add_argument("--lease-minutes", type=int, help="allow recovery after the lease expires")
    for cmd in ("finish", "block"):
        f = sub.add_parser(cmd)
        f.add_argument("id")
        f.add_argument("--worker", required=True)
        f.add_argument("--evidence", required=True)
        f.add_argument("--lease-token")
        if cmd == "block":
            f.add_argument("--reason", required=True)
    sub.add_parser("list")
    sub.add_parser("report")
    statement = sub.add_parser("statement")
    statement.add_argument("file", help="private reconciled statement JSON")
    a = p.parse_args()
    db = connect(a.db)
    try:
        if a.cmd == "init":
            result = {"initialized": True}
        elif a.cmd == "enqueue":
            result = {"created": enqueue(db, a.id, a.title, a.acceptance)}
        elif a.cmd == "claim":
            result = claim(db, a.worker, a.id, a.lease_minutes)
        elif a.cmd in ("finish", "block"):
            finish(db, a.id, a.worker, a.evidence, getattr(a, "reason", None), a.lease_token)
            result = {"id": a.id, "status": "blocked" if a.cmd == "block" else "prepared"}
        elif a.cmd == "list":
            result = rows(db)
        elif a.cmd == "statement":
            result = ledger.import_file(db, a.file)
        else:
            result = report(db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        p.exit(2, str(exc) + "\n")
    finally:
        db.close()

if __name__ == "__main__":
    main()
