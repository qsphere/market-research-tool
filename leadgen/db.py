"""SQLite connection, versioned migrations, and the repository layer."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any


class DuplicateRecordError(Exception):
    """Raised when a unique constraint rejects a repeated insert."""


class NotFoundError(LookupError):
    """Raised when a requested row does not exist."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def connect(path: str | Path) -> sqlite3.Connection:
    # check_same_thread=False: searches run in a worker thread. Callers share one connection
    # and the Repository serialises access with a lock.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migration_files() -> list[tuple[int, str]]:
    found = []
    for entry in resources.files("leadgen.migrations").iterdir():
        if entry.name.endswith(".sql"):
            found.append((int(entry.name.split("_", 1)[0]), entry.read_text(encoding="utf-8")))
    return sorted(found)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; return the current schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, sql in _migration_files():
        if number <= version:
            continue
        conn.executescript("BEGIN;\n" + sql + f"\nPRAGMA user_version = {number};\nCOMMIT;")
        version = number
    return version


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


LEAD_FIELDS = (
    "name", "kind", "category", "address", "phone", "phone_original", "extra_phones",
    "website", "website_original", "lat", "lon",
)  # fmt: skip


def area_key(text: str) -> str:
    """Case/punctuation/whitespace-insensitive key for an area string."""
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return " ".join(cleaned.split())


class Repository:
    """Thin data-access layer. All SQL is parameterized; a lock serialises thread access."""

    def __init__(self, conn: sqlite3.Connection, clock: Callable[[], datetime] = utcnow):
        self.conn = conn
        self._clock = clock
        self._lock = threading.RLock()

    def now(self) -> datetime:
        return self._clock()

    def _ts(self) -> str:
        return self.now().isoformat()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    # --- searches -------------------------------------------------------------------------
    def create_search(self, category: str, area: str) -> int:
        cur = self._exec(
            "INSERT INTO searches (category, area, area_key, created_at) VALUES (?,?,?,?)",
            (category, area, area_key(area), self._ts()),
        )
        return int(cur.lastrowid)

    def finish_search(
        self,
        search_id: int,
        status: str,
        message: str = "",
        failures: list[dict[str, str]] | None = None,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        self._exec(
            "UPDATE searches SET status=?, message=?, failures=?, candidates=?, finished_at=?"
            " WHERE id=?",
            (status, message, json.dumps(failures or []), json.dumps(candidates or []),
             self._ts(), search_id),
        )  # fmt: skip

    def set_search_choice(self, search_id: int, choice: str) -> None:
        """Make the cache key specific to the area the user picked from an ambiguous list."""
        row = self.get_search(search_id)
        self._exec(
            "UPDATE searches SET area_key=? WHERE id=?",
            (f"{area_key(row['area'])}|{choice}", search_id),
        )

    def restart_search(self, search_id: int) -> None:
        self._exec(
            "UPDATE searches SET status='running', message='', failures='[]', finished_at=NULL"
            " WHERE id=?",
            (search_id,),
        )

    def get_search(self, search_id: int) -> sqlite3.Row:
        row = self._one("SELECT * FROM searches WHERE id=?", (search_id,))
        if row is None:
            raise NotFoundError(f"search {search_id}")
        return row

    def list_searches(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM searches ORDER BY id DESC")

    def latest_finished_search(self, category: str, area: str) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM searches WHERE category=? AND area_key=?"
            " AND status IN ('done','partial') ORDER BY id DESC LIMIT 1",
            (category, area_key(area)),
        )

    # --- geocode cache --------------------------------------------------------------------
    def get_geocode(self, query: str) -> tuple[Any, datetime] | None:
        row = self._one(
            "SELECT result, fetched_at FROM geocode_cache WHERE query=?", (area_key(query),)
        )
        if row is None:
            return None
        return json.loads(row["result"]), datetime.fromisoformat(row["fetched_at"])

    def put_geocode(self, query: str, result: Any) -> None:
        self._exec(
            "INSERT INTO geocode_cache (query, result, fetched_at) VALUES (?,?,?)"
            " ON CONFLICT(query) DO UPDATE SET result=excluded.result,"
            " fetched_at=excluded.fetched_at",
            (area_key(query), json.dumps(result), self._ts()),
        )

    # --- raw records ----------------------------------------------------------------------
    def save_raw_record(
        self,
        search_id: int,
        source: str,
        source_record_id: str,
        payload: str,
        request: dict[str, Any],
    ) -> int:
        """Store a raw payload exactly as received (a string, never re-serialised)."""
        try:
            cur = self._exec(
                "INSERT INTO raw_records (source, search_id, source_record_id, payload, request,"
                " fetched_at) VALUES (?,?,?,?,?,?)",
                (source, search_id, source_record_id, payload, json.dumps(request), self._ts()),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError(f"{source}:{source_record_id}") from exc
        return int(cur.lastrowid)

    def get_raw_record(self, raw_id: int) -> sqlite3.Row:
        row = self._one("SELECT * FROM raw_records WHERE id=?", (raw_id,))
        if row is None:
            raise NotFoundError(f"raw record {raw_id}")
        return row

    def raw_records_for_search(self, search_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM raw_records WHERE search_id=? ORDER BY id", (search_id,))

    # --- leads ----------------------------------------------------------------------------
    @staticmethod
    def _lead_values(fields: dict[str, Any]) -> dict[str, Any]:
        unknown = set(fields) - set(LEAD_FIELDS)
        if unknown:
            raise ValueError(f"unknown lead fields: {sorted(unknown)}")
        out = dict(fields)
        if "extra_phones" in out and not isinstance(out["extra_phones"], str):
            out["extra_phones"] = json.dumps(out["extra_phones"])
        return out

    def insert_lead(self, **fields: Any) -> int:
        data = self._lead_values(fields)
        cols = ",".join(data)
        marks = ",".join("?" for _ in data)
        cur = self._exec(
            f"INSERT INTO leads ({cols}, created_at) VALUES ({marks}, ?)",  # noqa: S608
            (*data.values(), self._ts()),
        )
        return int(cur.lastrowid)

    def update_lead(self, lead_id: int, **fields: Any) -> None:
        data = self._lead_values(fields)
        if not data:
            return
        sets = ",".join(f"{k}=?" for k in data)
        cur = self._exec(
            f"UPDATE leads SET {sets} WHERE id=?",  # noqa: S608
            (*data.values(), lead_id),
        )
        if cur.rowcount == 0:
            raise NotFoundError(f"lead {lead_id}")

    def get_lead(self, lead_id: int) -> sqlite3.Row:
        row = self._one("SELECT * FROM leads WHERE id=?", (lead_id,))
        if row is None:
            raise NotFoundError(f"lead {lead_id}")
        return row

    def active_leads(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM leads WHERE merged_into IS NULL ORDER BY id")

    def mark_merged(self, loser_id: int, winner_id: int) -> None:
        self._exec("UPDATE leads SET merged_into=? WHERE id=?", (winner_id, loser_id))

    def resolve_lead(self, lead_id: int) -> int:
        seen: set[int] = set()
        while lead_id not in seen:
            seen.add(lead_id)
            row = self._one("SELECT merged_into FROM leads WHERE id=?", (lead_id,))
            if row is None:
                raise NotFoundError(f"lead {lead_id}")
            if row["merged_into"] is None:
                return lead_id
            lead_id = row["merged_into"]
        raise RuntimeError("merge cycle")  # pragma: no cover

    def find_lead_by_source_record(self, source: str, source_record_id: str) -> int | None:
        """Lead already built from this source record in an earlier search (follows merges)."""
        row = self._one(
            "SELECT ls.lead_id FROM lead_sources ls JOIN raw_records r ON r.id = ls.raw_record_id"
            " WHERE r.source=? AND r.source_record_id=? ORDER BY ls.lead_id LIMIT 1",
            (source, source_record_id),
        )
        return self.resolve_lead(row["lead_id"]) if row else None

    def link_source(self, lead_id: int, raw_record_id: int) -> None:
        self._exec(
            "INSERT OR IGNORE INTO lead_sources (lead_id, raw_record_id) VALUES (?,?)",
            (lead_id, raw_record_id),
        )

    def move_sources(self, from_lead: int, to_lead: int) -> None:
        self._exec(
            "INSERT OR IGNORE INTO lead_sources (lead_id, raw_record_id)"
            " SELECT ?, raw_record_id FROM lead_sources WHERE lead_id=?",
            (to_lead, from_lead),
        )

    def lead_sources(self, lead_id: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT r.* FROM lead_sources ls JOIN raw_records r ON r.id = ls.raw_record_id"
            " WHERE ls.lead_id=? ORDER BY r.id",
            (lead_id,),
        )

    def link_search_lead(self, search_id: int, lead_id: int) -> None:
        self._exec(
            "INSERT OR IGNORE INTO search_leads (search_id, lead_id) VALUES (?,?)",
            (search_id, lead_id),
        )

    def search_lead_ids(self, search_id: int) -> list[int]:
        """Leads of a search, following merges so merged leads show as their survivor."""
        rows = self._all(
            "SELECT lead_id FROM search_leads WHERE search_id=? ORDER BY lead_id", (search_id,)
        )
        out: list[int] = []
        for r in rows:
            lid = self.resolve_lead(r["lead_id"])
            if lid not in out:
                out.append(lid)
        return out

    # --- duplicate pairs ------------------------------------------------------------------
    def add_pair(self, lead_a: int, lead_b: int, score: float) -> bool:
        """Record a possible duplicate. Returns False if the pair already exists (any status)."""
        a, b = sorted((lead_a, lead_b))
        if a == b:
            raise ValueError("a lead cannot duplicate itself")
        cur = self._exec(
            "INSERT OR IGNORE INTO duplicate_pairs (lead_a, lead_b, score) VALUES (?,?,?)",
            (a, b, score),
        )
        return cur.rowcount == 1

    def pair_status(self, lead_a: int, lead_b: int) -> str | None:
        a, b = sorted((lead_a, lead_b))
        row = self._one("SELECT status FROM duplicate_pairs WHERE lead_a=? AND lead_b=?", (a, b))
        return row["status"] if row else None

    def get_pair(self, pair_id: int) -> sqlite3.Row:
        row = self._one("SELECT * FROM duplicate_pairs WHERE id=?", (pair_id,))
        if row is None:
            raise NotFoundError(f"pair {pair_id}")
        return row

    def set_pair_status(self, pair_id: int, status: str) -> None:
        if status not in ("pending", "merged", "rejected"):
            raise ValueError(f"bad status {status}")
        cur = self._exec("UPDATE duplicate_pairs SET status=? WHERE id=?", (status, pair_id))
        if cur.rowcount == 0:
            raise NotFoundError(f"pair {pair_id}")

    def pending_pairs(self) -> list[sqlite3.Row]:
        return self._all(
            "SELECT p.* FROM duplicate_pairs p"
            " JOIN leads a ON a.id = p.lead_a JOIN leads b ON b.id = p.lead_b"
            " WHERE p.status='pending' AND a.merged_into IS NULL AND b.merged_into IS NULL"
            " ORDER BY p.score DESC, p.id"
        )
