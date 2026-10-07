from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import hashlib

from .models import Paper


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def default_home():
    if os.getenv("PAPER2MD_HOME"):
        return Path(os.environ["PAPER2MD_HOME"]).expanduser()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "paper2md"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "paper2md"


class Store:
    def __init__(self, home=None):
        self.home = Path(home) if home is not None else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.database = self.home / "papers.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS aliases (alias TEXT PRIMARY KEY, id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bundles (paper_id TEXT, cache_key TEXT, path TEXT,
                    created TEXT, PRIMARY KEY(paper_id, cache_key));
            """)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=30)) as db:
            with db:
                yield db

    def save_paper(self, paper, db=None):
        if db is None:
            with self.connect() as connection:
                self.save_paper(paper, connection)
            return
        db.execute("INSERT OR REPLACE INTO papers VALUES (?, ?)", (paper.id, json.dumps(paper.to_dict())))
        for alias in paper.aliases:
            db.execute("INSERT OR REPLACE INTO aliases VALUES (?, ?)", (alias, paper.id))

    def save_search(self, metadata, papers):
        sid = "s_" + uuid.uuid4().hex[:12]
        data = {"schema_version": 1, **metadata, "search_id": sid, "searched_at": timestamp(),
                "results": [{**p.to_dict(), "selection_id": f"{sid}:{i}"} for i, p in enumerate(papers, 1)]}
        with self.connect() as db:
            for paper in papers:
                self.save_paper(paper, db)
            db.execute("INSERT INTO searches VALUES (?, ?)", (sid, json.dumps(data)))
        return data

    def resolve(self, identifier):
        with self.connect() as db:
            if identifier.startswith("s_") and ":" in identifier:
                sid, index = identifier.rsplit(":", 1)
                row = db.execute("SELECT data FROM searches WHERE id=?", (sid,)).fetchone()
                if row:
                    records = json.loads(row[0])["results"]
                    if index.isdigit() and 1 <= int(index) <= len(records):
                        return Paper.from_dict(records[int(index) - 1])
                raise ValueError("ID de seleção desconhecido; use o selection_id retornado pela busca.")
            row = db.execute("SELECT data FROM papers WHERE id=?", (identifier,)).fetchone()
            if row is None:
                row = db.execute("SELECT data FROM papers WHERE id=(SELECT id FROM aliases WHERE alias=?)", (identifier,)).fetchone()
            if row:
                return Paper.from_dict(json.loads(row[0]))
        raise ValueError("Paper não salvo; forneça um ID canônico, link ou selection_id válido.")

    def save_bundle(self, paper_id, cache_key, path):
        path = str(Path(path).resolve())
        with self.connect() as db:
            db.execute("DELETE FROM bundles WHERE path=?", (path,))
            db.execute("INSERT OR REPLACE INTO bundles VALUES (?, ?, ?, ?)",
                       (paper_id, cache_key, path, timestamp()))

    def bundle(self, paper_id, cache_key=None):
        with self.connect() as db:
            if cache_key:
                row = db.execute("SELECT path FROM bundles WHERE paper_id=? AND cache_key=?", (paper_id, cache_key)).fetchone()
            else:
                row = db.execute("SELECT path FROM bundles WHERE paper_id=? ORDER BY created DESC LIMIT 1", (paper_id,)).fetchone()
        return Path(row[0]) if row and Path(row[0]).is_dir() else None

    @contextmanager
    def lock(self, key, timeout=30):
        directory = self.home / "locks"
        directory.mkdir(exist_ok=True)
        path = directory / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ValueError(f"Paper em processamento. Se o processo anterior encerrou, remova o lock {path.name} em {directory}.")
                time.sleep(0.2)
        try:
            os.write(fd, str(os.getpid()).encode())
            yield
        finally:
            os.close(fd)
            path.unlink(missing_ok=True)
