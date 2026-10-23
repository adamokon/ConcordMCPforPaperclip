"""One host SQLite journal. Never put the database on a shared/network filesystem."""

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path

from .policy import BridgeError


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise BridgeError("UNSAFE_DATABASE")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise BridgeError("SCHEMA_VERSION")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, spec TEXT NOT NULL,
              issue_id TEXT UNIQUE, identifier TEXT, state TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
              owner TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
              task_id TEXT NOT NULL, state TEXT NOT NULL, result TEXT, updated REAL NOT NULL,
              PRIMARY KEY(owner,key)
            );
            CREATE TABLE IF NOT EXISTS claims (
              repo TEXT NOT NULL, scope TEXT NOT NULL, task_id TEXT NOT NULL,
              PRIMARY KEY(repo,scope,task_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, sender TEXT NOT NULL,
              recipient TEXT NOT NULL, body TEXT NOT NULL, reply_to TEXT,
              state TEXT NOT NULL DEFAULT 'recorded', created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, profile TEXT NOT NULL,
              number INTEGER NOT NULL, state TEXT NOT NULL, run_id TEXT, evidence TEXT,
              UNIQUE(task_id,number)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS profile_slot ON attempts(profile)
              WHERE state IN ('dispatching','running','uncertain');
            CREATE TABLE IF NOT EXISTS manifests (
              task_id TEXT PRIMARY KEY, digest TEXT NOT NULL, manifest TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
              task_id TEXT NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL
            );
            PRAGMA user_version=1;
            """)

    @contextlib.contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("PRAGMA busy_timeout=10000")
        try:
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    @staticmethod
    def audit(c, actor, task, event, details=None):
        # Do not put descriptions, messages, request bodies or tokens in this audit.
        c.execute("INSERT INTO audit(at,actor,task_id,event,details) VALUES(?,?,?,?,?)",
                  (time.time(), actor, task, event, canonical(details or {})))

    def backup(self, destination: str):
        target = Path(destination)
        if target.exists():
            raise BridgeError("BACKUP_EXISTS")
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connect() as source:
            dest = sqlite3.connect(target)
            try:
                source.backup(dest)
            finally:
                dest.close()
