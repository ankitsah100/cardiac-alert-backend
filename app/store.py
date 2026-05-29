"""
DataStore — SQLite backed persistent storage.
Data survives Railway restarts.
"""

import sqlite3
import json
import os
from typing import Optional

DB_PATH = os.environ.get("DB_PATH", "/tmp/cardiac.db")


class DataStore:

    def __init__(self):
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_readings_patient
                ON readings(patient_id, created_at)
            """)

    # ── Patients ──────────────────────────────────────────────────

    def register_patient(self, data: dict):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO patients(patient_id, data)
                VALUES (?, ?)
            """, (data["patient_id"], json.dumps(data)))

    def get_patient(self, patient_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM patients WHERE patient_id = ?",
                (patient_id,)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    # ── Readings ──────────────────────────────────────────────────

    def save_reading(self, patient_id: str, reading: dict):
        import time
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO readings(patient_id, data, created_at)
                VALUES (?, ?, ?)
            """, (patient_id, json.dumps(reading), time.time()))

    def get_history(self, patient_id: str, limit: int = 50) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT data FROM readings
                WHERE patient_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (patient_id, limit)).fetchall()
        return [json.loads(r["data"]) for r in reversed(rows)]

    def get_latest(self, patient_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT data FROM readings
                WHERE patient_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (patient_id,)).fetchone()
        return json.loads(row["data"]) if row else None
