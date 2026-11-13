"""Small SQLite persistence layer for the local demo."""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
DB_PATH = Path(os.getenv("DATABASE_PATH", str(Path(__file__).resolve().parents[1] / "data" / "vendor_onboarding.sqlite3")))

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, full_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('vendor','reviewer','admin')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS applications(application_ref TEXT PRIMARY KEY, state TEXT NOT NULL, decision_status TEXT, version INTEGER NOT NULL DEFAULT 0, owner_user_id TEXT REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS application_versions(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, version INTEGER NOT NULL, submission_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(application_ref, version), FOREIGN KEY(application_ref) REFERENCES applications(application_ref));
        CREATE TABLE IF NOT EXISTS evaluations(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, version INTEGER NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(application_ref) REFERENCES applications(application_ref));
        CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, slot_id TEXT NOT NULL, original_filename TEXT NOT NULL, sha256 TEXT NOT NULL, stored_path TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, version INTEGER NOT NULL, seq INTEGER NOT NULL, event_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS validation_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, version INTEGER NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(application_ref) REFERENCES applications(application_ref));
        CREATE INDEX IF NOT EXISTS idx_validation_runs_app ON validation_runs(application_ref, id DESC);
        CREATE TABLE IF NOT EXISTS reviewer_comments(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, author_user_id TEXT NOT NULL, author_name TEXT NOT NULL, comment TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'COMMENT', created_at TEXT NOT NULL, FOREIGN KEY(application_ref) REFERENCES applications(application_ref), FOREIGN KEY(author_user_id) REFERENCES users(id));
        CREATE INDEX IF NOT EXISTS idx_reviewer_comments_app ON reviewer_comments(application_ref, id DESC);
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, application_ref TEXT NOT NULL, actor_user_id TEXT NOT NULL, actor_name TEXT NOT NULL, actor_role TEXT NOT NULL, action TEXT NOT NULL, from_state TEXT, to_state TEXT, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, FOREIGN KEY(application_ref) REFERENCES applications(application_ref), FOREIGN KEY(actor_user_id) REFERENCES users(id));
        CREATE INDEX IF NOT EXISTS idx_audit_logs_app ON audit_logs(application_ref, id DESC);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(applications)").fetchall()}
        if "owner_user_id" not in columns:
            db.execute("ALTER TABLE applications ADD COLUMN owner_user_id TEXT REFERENCES users(id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_applications_owner ON applications(owner_user_id)")
