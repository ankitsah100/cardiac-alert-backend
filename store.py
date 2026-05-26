"""
DataStore
In-memory store for patients and readings.
For production: replace with InfluxDB (time-series) or PostgreSQL.
"""

from collections import defaultdict, deque
from typing import Optional


class DataStore:

    def __init__(self, max_history: int = 1000):
        self._patients: dict[str, dict] = {}
        self._readings: dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))

    # ── Patients ──────────────────────────────────────────────────

    def register_patient(self, data: dict):
        self._patients[data["patient_id"]] = data

    def get_patient(self, patient_id: str) -> Optional[dict]:
        return self._patients.get(patient_id)

    # ── Readings ──────────────────────────────────────────────────

    def save_reading(self, patient_id: str, reading: dict):
        self._readings[patient_id].append(reading)

    def get_history(self, patient_id: str, limit: int = 50) -> list:
        if patient_id not in self._readings:
            return []
        readings = list(self._readings[patient_id])
        return readings[-limit:]

    def get_latest(self, patient_id: str) -> Optional[dict]:
        readings = self._readings.get(patient_id)
        if not readings:
            return None
        return readings[-1]
