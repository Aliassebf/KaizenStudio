"""Accès SQLite de Kaizen Studio.

- connexions FERMÉES en sortie de ``with`` (pas de fuite de descripteurs sous Windows) ;
- mode WAL + ``busy_timeout`` (analyse en tâche de fond + requêtes HTTP simultanées) ;
- ``init_db()`` exécuté une seule fois par fichier de base, migrations versionnées
  (``PRAGMA user_version``), index de performance, date de dernière activité projet.

API publique inchangée : ``get_connection``, ``init_db``, ``row_to_dict``, ``fetch_all``.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from . import config as _config
from .config import ensure_directories

# Les tests remplacent app.db.DATABASE_PATH : toujours le relire à l'exécution.
DATABASE_PATH = _config.DATABASE_PATH

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


class _ClosingConnection(sqlite3.Connection):
    """Connexion qui commit/rollback PUIS se ferme en sortie de bloc ``with``."""

    def __exit__(self, exc_type, exc, tb):  # type: ignore[override]
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _database_path() -> Path:
    return Path(DATABASE_PATH)


def get_connection() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


_BASE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        takt_s REAL NOT NULL,
        owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        cree_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        nom TEXT NOT NULL,
        video_path TEXT,
        roi TEXT,
        fenetre_debut REAL DEFAULT 0,
        fenetre_fin REAL,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS phases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id INTEGER NOT NULL,
        ordre INTEGER NOT NULL,
        debut_s REAL NOT NULL,
        fin_s REAL NOT NULL,
        type_auto TEXT NOT NULL,
        description TEXT,
        categorie TEXT,
        commentaire TEXT,
        chrono_reel_s REAL,
        mouvement_moyen_pct REAL,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        nom TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_project_operations_name
    ON project_operations(project_id, nom COLLATE NOCASE)
    """,
    """
    CREATE TABLE IF NOT EXISTS video_annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id INTEGER NOT NULL,
        operation_id INTEGER,
        debut_s REAL NOT NULL CHECK (debut_s >= 0),
        fin_s REAL NOT NULL CHECK (fin_s > debut_s),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE,
        FOREIGN KEY(operation_id) REFERENCES project_operations(id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_video_annotations_station_time "
    "ON video_annotations(station_id, debut_s, fin_s)",
    """
    CREATE TABLE IF NOT EXISTS cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id INTEGER NOT NULL,
        debut_s REAL NOT NULL CHECK (debut_s >= 0),
        fin_s REAL NOT NULL CHECK (fin_s > debut_s),
        source TEXT NOT NULL CHECK (source IN ('manual', 'auto')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (station_id, debut_s, fin_s),
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        cle TEXT PRIMARY KEY,
        valeur TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ergonomic_assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id INTEGER NOT NULL,
        time_s REAL NOT NULL CHECK (time_s >= 0),
        rula_score INTEGER CHECK (rula_score BETWEEN 1 AND 7),
        reba_score INTEGER CHECK (reba_score BETWEEN 1 AND 15),
        evaluator TEXT NOT NULL,
        factors_notes TEXT NOT NULL,
        posture_snapshot_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (rula_score IS NOT NULL OR reba_score IS NOT NULL),
        FOREIGN KEY(station_id) REFERENCES stations(id) ON DELETE CASCADE
    )
    """,
)

_DEFAULT_SETTINGS = {
    "purge_days": "90",
    "allow_outbound_network": "false",
    "video_max_mb": "2048",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migration_1_legacy_columns(conn: sqlite3.Connection) -> None:
    _add_column(conn, "projects", "owner_user_id", "INTEGER REFERENCES users(id) ON DELETE CASCADE")
    _add_column(conn, "stations", "video_duration_s", "REAL")
    _add_column(conn, "stations", "video_fps", "REAL")
    _add_column(conn, "stations", "motion_signal_json", "TEXT")
    _add_column(conn, "stations", "motion_threshold_pct", "REAL")
    _add_column(conn, "stations", "posture_signal_json", "TEXT")
    _add_column(
        conn,
        "stations",
        "dataset_split",
        "TEXT NOT NULL DEFAULT 'excluded' CHECK (dataset_split IN ('train', 'validation', 'excluded'))",
    )
    _add_column(conn, "stations", "analysis_configuration_json", "TEXT NOT NULL DEFAULT '{}'")


def _migration_2_backfill_operations(conn: sqlite3.Connection) -> None:
    """Reprise UNIQUE des descriptions de phases (avant : à chaque requête)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO project_operations (project_id, nom)
        SELECT DISTINCT st.project_id, TRIM(ph.description)
        FROM phases AS ph
        JOIN stations AS st ON st.id = ph.station_id
        WHERE ph.description IS NOT NULL
          AND TRIM(ph.description) <> ''
          AND ph.description NOT LIKE 'Activité détectée%'
          AND ph.description NOT LIKE 'Arrêt détecté%'
          AND ph.description NOT LIKE 'Phase fusionnée%'
        """
    )


def _migration_3_indexes_and_activity(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stations_project ON stations(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_phases_station_ordre ON phases(station_id, ordre)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cycles_station ON cycles(station_id, debut_s)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ergonomic_station_time ON ergonomic_assessments(station_id, time_s)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id, cree_le)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id)")
    _add_column(conn, "projects", "derniere_activite_le", "TEXT")
    conn.execute("UPDATE projects SET derniere_activite_le = cree_le WHERE derniere_activite_le IS NULL")


_MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _migration_1_legacy_columns,
    _migration_2_backfill_operations,
    _migration_3_indexes_and_activity,
)
SCHEMA_VERSION = len(_MIGRATIONS)


def init_db(force: bool = False) -> None:
    """Crée/migre la base. Idempotent ; coûteux une seule fois par fichier."""
    ensure_directories()
    path = _database_path()
    key = str(path.resolve())
    if not force and key in _initialized_paths and path.exists():
        return
    with _init_lock:
        if not force and key in _initialized_paths and path.exists():
            return
        with get_connection() as conn:
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.OperationalError:
                pass
            for statement in _BASE_SCHEMA:
                conn.execute(statement)
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            for index, migration in enumerate(_MIGRATIONS, start=1):
                if index > current:
                    migration(conn)
                    conn.execute(f"PRAGMA user_version = {index}")
            for key_name, value in _DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings (cle, valeur) VALUES (?, ?)", (key_name, value))
            conn.execute("DELETE FROM user_sessions WHERE datetime(expires_at) <= CURRENT_TIMESTAMP")
        _initialized_paths.add(key)


def touch_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Marque l'activité d'un projet (évite sa purge alors qu'il est utilisé)."""
    conn.execute("UPDATE projects SET derniere_activite_le = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def fetch_all(query: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]
