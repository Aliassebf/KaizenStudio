"""Registre des tâches d'analyse en mémoire, thread-safe, avec purge automatique.

Remplace le couple ``analysis_jobs`` (dict) + ``analysis_jobs_lock`` de main.py :
- l'ancien dict grandissait indéfiniment et gardait en RAM les signaux de
  mouvement et TOUTES les postures de chaque analyse (plusieurs Mo par tâche) ;
- ici les tâches terminées sont purgées après ``FINISHED_TTL_SECONDS`` et les
  gros résultats sont libérés dès qu'ils ont été lus par le navigateur.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

FINISHED_TTL_SECONDS = 30 * 60
ACTIVE_STATUSES = frozenset({"queued", "running"})
_HEAVY_KEYS = ("motion_samples", "posture_samples")


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def create(self, station_id: int, kind: str, **extra: Any) -> str:
        """Crée une tâche ; lève RuntimeError si une tâche est déjà active sur le poste."""
        with self._lock:
            self._prune_locked()
            if any(
                job["station_id"] == station_id and job["status"] in ACTIVE_STATUSES
                for job in self._jobs.values()
            ):
                raise RuntimeError("Une analyse est déjà en cours pour ce poste.")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                "id": job_id,
                "station_id": station_id,
                "kind": kind,
                "status": "queued",
                "progress": 0,
                "error": None,
                "created_at": time.time(),
                "finished_at": None,
                **extra,
            }
            return job_id

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if "progress" in changes:
                changes["progress"] = max(int(job.get("progress") or 0), int(changes["progress"]))
            job.update(changes)
            if job["status"] not in ACTIVE_STATUSES and job["finished_at"] is None:
                job["finished_at"] = time.time()

    def set_progress(self, job_id: str, fraction: float) -> None:
        self.update(job_id, progress=min(99, int(fraction * 100)))

    def get(self, job_id: str, release_heavy: bool = False) -> dict[str, Any] | None:
        """Copie de la tâche. ``release_heavy`` libère les gros résultats une fois lus."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            snapshot = dict(job)
            if release_heavy and job["status"] not in ACTIVE_STATUSES:
                for key in _HEAVY_KEYS:
                    if key in job:
                        job[key] = []
            return snapshot

    def station_of(self, job_id: str) -> int | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else int(job["station_id"])

    def active_station_ids(self) -> set[int]:
        with self._lock:
            return {int(job["station_id"]) for job in self._jobs.values() if job["status"] in ACTIVE_STATUSES}

    def has_active(self, station_ids: set[int] | int) -> bool:
        ids = {station_ids} if isinstance(station_ids, int) else station_ids
        return bool(self.active_station_ids() & ids)

    # ------------------------------------------------------------------ #
    def _prune_locked(self) -> None:
        limit = time.time() - FINISHED_TTL_SECONDS
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job["finished_at"] is not None and job["finished_at"] < limit
        ]
        for job_id in expired:
            del self._jobs[job_id]


jobs = JobRegistry()
