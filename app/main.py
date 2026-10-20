from __future__ import annotations

import os
import json
import asyncio
import re
import sqlite3
import logging
import math
import threading
import uuid
import ipaddress
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import (
    SESSION_COOKIE,
    SESSION_HOURS,
    create_session,
    get_session_user,
    hash_password,
    clear_failed_logins,
    login_is_rate_limited,
    record_failed_login,
    revoke_session,
    user_count,
    _DUMMY_PASSWORD_HASH,
    verify_password,
)
from .config import EXPORT_ROOT, MODEL_ROOT, VIDEO_ROOT, ensure_directories, server_bind_configuration
from .analysis.base import AnalysisParams
from .analysis.motion import MotionAnalysisBackend, parse_roi, segment_motion_signal, serialize_roi
from .analysis.operation_learning import (
    MIN_SUGGESTION_CONFIDENCE,
    OperationLearningError,
    OperationSample,
    load_operation_model,
    predict_operation,
    train_operation_model,
)
from .analysis.posture import analyze_posture_video
from .analysis.video import open_video_capture, orient_video_frame
from .ergonomics.scoring import score_posture, summarize_series
from .db import get_connection, init_db, touch_project
from .core.files import managed_file_path
from .models import (
    AdminAccountCreate,
    AnalysisRequest,
    AnalysisConfigurationUpdate,
    AnalysisSettingsUpdate,
    CycleCreate,
    ErgonomicAssessmentCreate,
    ErgonomicScoringRequest,
    LocalAccountCreate,
    PasswordReset,
    PasswordUpdate,
    PostureAnalysisRequest,
    ProjectOperationCreate,
    ProjectOperationUpdate,
    PhaseCreate,
    PhaseMerge,
    PhaseSplit,
    PhaseUpdate,
    ProjectCreate,
    ProjectUpdate,
    DatasetSplitUpdate,
    ResegmentRequest,
    StationCreate,
    VideoAnnotationCreate,
    VideoAnnotationUpdate,
)
from .services.excel_export import export_project_workbook
from .services.cycle_analysis import cycle_duration_statistics, suggest_cycles


analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kaizen-analysis")
analysis_jobs: dict[str, dict[str, Any]] = {}
analysis_jobs_lock = threading.Lock()
logger = logging.getLogger(__name__)
PURGE_INTERVAL_SECONDS = 24 * 60 * 60


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_initialized()
    purge_task = asyncio.create_task(_scheduled_retention_purge())
    try:
        yield
    finally:
        purge_task.cancel()
        try:
            await purge_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Kaizen Studio", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.middleware("http")
async def protect_private_responses(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.middleware("http")
async def require_local_account(request: Request, call_next):
    path = request.url.path
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Origine de requête non autorisée."}, status_code=403)
    public_paths = {
        "/api/health",
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
    }
    if path.startswith("/static/") or path in public_paths:
        return await call_next(request)

    accounts_exist = user_count() > 0
    if not accounts_exist:
        if path in {"/", "/setup", "/login"}:
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Créez le compte administrateur initial."}, status_code=503)
        return RedirectResponse("/setup", status_code=303)

    token = request.cookies.get(SESSION_COOKIE)
    user = get_session_user(token)
    if user is None:
        if path in {"/", "/login", "/setup"}:
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Authentification requise."}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    request.state.user = user
    if path in {"/login", "/setup"}:
        return RedirectResponse("/", status_code=303)

    if path.startswith(("/api/settings", "/api/maintenance/", "/api/exports", "/api/admin/")) or path == "/admin/users":
        if not user["is_admin"]:
            return JSONResponse({"detail": "Droits administrateur requis."}, status_code=403)

    project_match = (
        re.match(r"^/api/projects/(\d+)(?:/|$)", path)
        or re.match(r"^/projects/(\d+)/summary$", path)
    )
    station_match = (
        re.match(r"^/api/stations/(\d+)(?:/|$)", path)
        or re.match(r"^/review/(\d+)$", path)
    )
    owner_id = None
    if project_match:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT owner_user_id FROM projects WHERE id = ?",
                (int(project_match.group(1)),),
            ).fetchone()
        owner_id = int(row["owner_user_id"]) if row and row["owner_user_id"] is not None else None
    elif station_match:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT p.owner_user_id
                FROM stations s JOIN projects p ON p.id = s.project_id
                WHERE s.id = ?
                """,
                (int(station_match.group(1)),),
            ).fetchone()
        owner_id = int(row["owner_user_id"]) if row and row["owner_user_id"] is not None else None
    if project_match or station_match:
        resource_exists = owner_id is not None
        if not resource_exists or owner_id != int(user["id"]):
            return JSONResponse({"detail": "Projet ou poste introuvable."}, status_code=404)

    job_match = re.match(r"^/api/jobs/([a-f0-9]+)$", path)
    if job_match:
        with analysis_jobs_lock:
            job = analysis_jobs.get(job_match.group(1))
        if job is not None:
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT p.owner_user_id
                    FROM stations s JOIN projects p ON p.id = s.project_id
                    WHERE s.id = ?
                    """,
                    (int(job["station_id"]),),
                ).fetchone()
            if row is None or int(row["owner_user_id"]) != int(user["id"]):
                return JSONResponse({"detail": "Tâche d'analyse introuvable."}, status_code=404)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (project_match or station_match):
        _touch_project_activity(project_match, station_match)
    return await call_next(request)


def ensure_initialized() -> None:
    init_db()
    ensure_directories()


def _managed_file_path(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    resolved_root = root.resolve()
    resolved_path = Path(value).resolve()
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        return None
    return resolved_path


def _remove_managed_file(value: str | None, root: Path) -> bool:
    path = _managed_file_path(value, root)
    if path is None or not path.exists():
        return False
    if not path.is_file():
        raise OSError(f"Le chemin géré n'est pas un fichier : {path}")
    path.unlink()
    return True


def _operation_model_paths(project_id: int) -> tuple[Path, Path]:
    stem = f"project_{project_id}_operations"
    return MODEL_ROOT / f"{stem}.yml", MODEL_ROOT / f"{stem}.json"


def _video_identity(video_path: str) -> str:
    return os.path.normcase(str(Path(video_path).resolve()))


def _remove_operation_model(project_id: int) -> None:
    model_path, metadata_path = _operation_model_paths(project_id)
    temporary_paths = (
        model_path.with_name(f"{model_path.stem}.tmp.yml"),
        metadata_path.with_name(f"{metadata_path.stem}.tmp.json"),
    )
    for artifact in (model_path, metadata_path, *temporary_paths):
        if artifact.exists():
            artifact.unlink()


def _operation_learning_data(project_id: int) -> tuple[list[OperationSample], list[OperationSample], str]:
    with get_connection() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable.")
        stations = conn.execute(
            """
            SELECT id, video_path, roi, dataset_split
            FROM stations WHERE project_id = ? ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        annotations = conn.execute(
            """
            SELECT va.id, va.station_id, va.operation_id, va.debut_s, va.fin_s,
                   op.nom AS operation, st.video_path, st.roi, st.dataset_split
            FROM video_annotations va
            JOIN stations st ON st.id = va.station_id
            LEFT JOIN project_operations op ON op.id = va.operation_id
            WHERE st.project_id = ?
            ORDER BY va.station_id, va.debut_s, va.id
            """,
            (project_id,),
        ).fetchall()

    station_fingerprint = []
    for station in stations:
        if station["dataset_split"] not in {"train", "validation"}:
            continue
        file_info: dict[str, Any] = {"exists": False}
        if station["video_path"]:
            try:
                stat = Path(station["video_path"]).stat()
                file_info = {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            except OSError:
                file_info = {"exists": False}
        station_fingerprint.append(
            {
                "id": station["id"],
                "split": station["dataset_split"],
                "roi": station["roi"],
                "video_identity": _video_identity(str(station["video_path"] or "")),
                "video": file_info,
            }
        )

    annotation_fingerprint = [
        {
            "id": row["id"],
            "station_id": row["station_id"],
            "operation_id": row["operation_id"],
            "operation": row["operation"],
            "start": row["debut_s"],
            "end": row["fin_s"],
        }
        for row in annotations
        if row["dataset_split"] in {"train", "validation"}
    ]
    signature_source = json.dumps(
        {"stations": station_fingerprint, "annotations": annotation_fingerprint},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()

    samples: dict[str, list[OperationSample]] = {"train": [], "validation": []}
    for row in annotations:
        if row["dataset_split"] not in samples or row["operation_id"] is None or not row["operation"]:
            continue
        samples[row["dataset_split"]].append(
            OperationSample(
                station_id=int(row["station_id"]),
                video_path=str(row["video_path"] or ""),
                roi=row["roi"],
                start_s=float(row["debut_s"]),
                end_s=float(row["fin_s"]),
                operation_id=int(row["operation_id"]),
                operation=str(row["operation"]),
            )
        )
    return samples["train"], samples["validation"], signature


def _operation_model_status(project_id: int, signature: str | None = None) -> dict[str, Any]:
    model_path, metadata_path = _operation_model_paths(project_id)
    if not model_path.is_file() or not metadata_path.is_file():
        return {
            "model_status": "not_trained",
            "is_stale": False,
            "message": "Aucun modèle local n'a encore été entraîné.",
        }
    try:
        _, metadata = load_operation_model(model_path, metadata_path)
    except (OSError, json.JSONDecodeError, OperationLearningError) as error:
        logger.warning("Le modèle local du projet %s est illisible : %s", project_id, error)
        return {
            "model_status": "invalid",
            "is_stale": True,
            "message": f"Les métadonnées du modèle sont illisibles : {error}",
        }
    stale = signature is not None and metadata.get("training_signature") != signature
    return {
        "model_status": "stale" if stale else "trained",
        "is_stale": stale,
        "trained_at": metadata.get("trained_at"),
        "validation": metadata.get("validation"),
        "training_examples": metadata.get("training_examples"),
        "training_counts": metadata.get("training_counts"),
        "excluded_operations": metadata.get("excluded_operations", []),
        "validation_untrained_operations": metadata.get("validation_untrained_operations", []),
        "message": (
            "Les annotations ou vidéos ont changé depuis l'entraînement ; réentraînez avant de proposer."
            if stale
            else "Classifieur local entraîné. Ses scores restent indicatifs et doivent être vérifiés."
        ),
    }


def purge_expired_projects() -> dict[str, int]:
    ensure_initialized()
    with get_connection() as conn:
        setting = conn.execute(
            "SELECT valeur FROM settings WHERE cle = 'purge_days'"
        ).fetchone()
        try:
            retention_days = int(setting["valeur"])
        except (TypeError, ValueError, KeyError) as error:
            raise RuntimeError("Le réglage purge_days est absent ou invalide.") from error
        if not 1 <= retention_days <= 3650:
            raise RuntimeError("Le réglage purge_days doit être compris entre 1 et 3650 jours.")
        expired_projects = conn.execute(
            "SELECT id FROM projects WHERE datetime(COALESCE(derniere_activite_le, cree_le)) < datetime('now', ?)",
            (f"-{retention_days} days",),
        ).fetchall()

    deleted_projects = 0
    deleted_videos = 0
    preserved_external_files = 0
    for project_row in expired_projects:
        project_id = int(project_row["id"])
        with analysis_jobs_lock:
            active_station_ids = {
                int(job["station_id"])
                for job in analysis_jobs.values()
                if job["status"] in {"queued", "running"}
            }
        with get_connection() as conn:
            station_rows = conn.execute(
                "SELECT id, video_path FROM stations WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        if any(int(station["id"]) in active_station_ids for station in station_rows):
            logger.warning("Purge différée : une analyse est en cours pour le projet %s.", project_id)
            continue

        try:
            _remove_operation_model(project_id)
            for station in station_rows:
                if station["video_path"] and _managed_file_path(station["video_path"], VIDEO_ROOT) is None:
                    preserved_external_files += 1
                    logger.warning(
                        "Purge : le fichier référencé par le poste %s est hors du dossier vidéo géré et sera conservé.",
                        station["id"],
                    )
                if _remove_managed_file(station["video_path"], VIDEO_ROOT):
                    deleted_videos += 1
            _remove_managed_file(str(EXPORT_ROOT / f"kaizen_studio_projet_{project_id}.xlsx"), EXPORT_ROOT)
            with get_connection() as conn:
                conn.execute(
                    """
                    DELETE FROM video_annotations
                    WHERE station_id IN (SELECT id FROM stations WHERE project_id = ?)
                    """,
                    (project_id,),
                )
                conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            deleted_projects += 1
        except OSError:
            logger.exception("Échec de la purge du projet %s ; ses données SQLite sont conservées.", project_id)

    return {
        "projects_deleted": deleted_projects,
        "videos_deleted": deleted_videos,
        "external_files_preserved": preserved_external_files,
    }


async def _scheduled_retention_purge() -> None:
    while True:
        try:
            result = await asyncio.to_thread(purge_expired_projects)
            if result["projects_deleted"]:
                logger.info(
                    "Purge de rétention : %s projet(s), %s vidéo(s) supprimés, %s fichier(s) externe(s) conservé(s).",
                    result["projects_deleted"],
                    result["videos_deleted"],
                    result["external_files_preserved"],
                )
        except Exception:
            logger.exception("La purge automatique des données a échoué.")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


# --- Correctifs revue Kaizen Studio (helpers) -------------------------------
_AUTO_PREFIXES = ("Activité détectée", "Arrêt détecté", "Phase fusionnée")
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi"}
_ALLOWED_SETTINGS = {"purge_days", "video_max_mb"}
_MAX_FINISHED_JOBS = 20
_REVIEWED_PHASES_MESSAGE = (
    "Des phases ont déjà été décrites, classées, commentées ou chronométrées. "
    "Relancer le calcul les remplacera : confirmez pour continuer."
)


def _prune_finished_jobs_locked() -> None:
    """À appeler sous analysis_jobs_lock : borne la mémoire des tâches terminées."""
    finished = [job_id for job_id, job in analysis_jobs.items() if job.get("status") not in {"queued", "running"}]
    for job_id in finished[: max(0, len(finished) - _MAX_FINISHED_JOBS)]:
        analysis_jobs.pop(job_id, None)


def _legacy_video_path(value: str | None) -> str | None:
    """Chemin vidéo fourni par l'API JSON : uniquement une vidéo, jamais diffusé hors dossier géré."""
    if value is None or not str(value).strip():
        return None
    if Path(str(value)).suffix.lower() not in _VIDEO_SUFFIXES:
        raise HTTPException(status_code=422, detail="Le chemin doit désigner une vidéo MP4, MOV ou AVI.")
    return str(value).strip()


def _validated_roi(value: str | None) -> str | None:
    try:
        return serialize_roi(parse_roi(value))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _station_has_reviewed_phases(conn, station_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM phases
        WHERE station_id = ?
          AND (chrono_reel_s IS NOT NULL
               OR COALESCE(TRIM(commentaire), '') <> ''
               OR COALESCE(categorie, 'Non classé') <> 'Non classé'
               OR (COALESCE(TRIM(description), '') <> ''
                   AND description NOT LIKE 'Activité détectée%'
                   AND description NOT LIKE 'Arrêt détecté%'
                   AND description NOT LIKE 'Phase fusionnée%'))
        LIMIT 1
        """,
        (station_id,),
    ).fetchone()
    return row is not None


def _reference_cycle_time(total_cycle: float, cycles) -> tuple[float, str]:
    """Temps de cycle de référence : médiane des cycles validés, sinon durée observée."""
    from statistics import median

    durations = [float(cycle["fin_s"]) - float(cycle["debut_s"]) for cycle in cycles]
    if durations:
        return float(median(durations)), "médiane des cycles validés"
    return float(total_cycle), "durée totale observée (aucun cycle validé)"


def _touch_project_activity(project_match, station_match) -> None:
    with get_connection() as conn:
        if project_match:
            project_id = int(project_match.group(1))
        else:
            row = conn.execute(
                "SELECT project_id FROM stations WHERE id = ?", (int(station_match.group(1)),)
            ).fetchone()
            project_id = int(row["project_id"]) if row else None
        if project_id is not None:
            touch_project(conn, project_id)


@app.get("/")
def index(request: Request):
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    if get_session_user(request.cookies.get(SESSION_COOKIE)) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/setup")
def setup_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "setup.html")


@app.get("/login")
def login_page() -> FileResponse:
    if user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return FileResponse(Path(__file__).parent / "static" / "login.html")


@app.get("/admin/users")
def admin_users_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "users.html")


@app.get("/review/{station_id}")
def review_page(station_id: int) -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "review.html")


@app.get("/projects/{project_id}/summary")
def summary_page(project_id: int) -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "summary.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    host = os.environ.get("KAIZEN_STUDIO_HOST", "127.0.0.1")
    uses_http_on_lan = host != "127.0.0.1" and not os.environ.get("KAIZEN_STUDIO_SSL_CERTFILE")
    return {
        "status": "ok",
        "service": "Kaizen Studio",
        "host": host,
        "local_only": host == "127.0.0.1",
        "network_default": False,
        "warning": "Les temps sont des estimations à valider par chronométrage réel.",
        "transport_warning": (
            "HTTP non chiffré : identifiants, vidéos et données peuvent être interceptés."
            if uses_http_on_lan
            else None
        ),
    }


@app.get("/api/auth/status")
def auth_status() -> dict[str, bool]:
    return {"setup_required": user_count() == 0}


@app.post("/api/auth/setup", status_code=status.HTTP_201_CREATED)
def setup_initial_admin(
    payload: LocalAccountCreate,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    ensure_initialized()
    try:
        is_local_request = bool(request.client) and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        is_local_request = False
    if not is_local_request:
        raise HTTPException(
            status_code=403,
            detail="Le premier administrateur doit être créé depuis le PC serveur lui-même.",
        )
    username = payload.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", username):
        raise HTTPException(
            status_code=422,
            detail="L'identifiant doit contenir 3 à 64 caractères (lettres, chiffres, ., _, @ ou -).",
        )
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(status_code=409, detail="Le compte administrateur initial existe déjà.")
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (username, hash_password(payload.password)),
        )
        user_id = int(cursor.lastrowid)
        conn.execute(
            "UPDATE projects SET owner_user_id = ? WHERE owner_user_id IS NULL",
            (user_id,),
        )
    _set_session_cookie(response, create_session(user_id))
    return {"id": user_id, "username": username, "is_admin": True}


@app.post("/api/auth/login")
def login(payload: LocalAccountCreate, request: Request, response: Response) -> dict[str, Any]:
    ensure_initialized()
    username = payload.username.strip()
    remote_ip = request.client.host if request.client else "unknown"
    if login_is_rate_limited(username, remote_ip):
        raise HTTPException(status_code=429, detail="Trop de tentatives. Réessayez dans 15 minutes.")
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash, is_admin FROM users WHERE username = ? COLLATE NOCASE AND is_active = 1",
            (username,),
        ).fetchone()
    password_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
    if not verify_password(payload.password, password_hash) or user is None:
        record_failed_login(username, remote_ip)
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")
    clear_failed_logins(username, remote_ip)
    _set_session_cookie(response, create_session(int(user["id"])))
    return {"id": int(user["id"]), "username": user["username"], "is_admin": bool(user["is_admin"])}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"status": "déconnecté"}


@app.get("/api/auth/me")
def current_account(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentification requise.")
    return user


@app.put("/api/auth/password")
def change_password(payload: PasswordUpdate, request: Request) -> dict[str, str]:
    user = request.state.user
    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (int(user["id"]),),
        ).fetchone()
        if row is None or not verify_password(payload.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="Le mot de passe actuel est incorrect.")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), int(user["id"])),
        )
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (int(user["id"]),))
    return {"status": "Mot de passe modifié. Reconnectez-vous."}


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_HOURS * 60 * 60,
        httponly=True,
        secure=(
            os.environ.get("KAIZEN_STUDIO_COOKIE_SECURE") == "1"
            or bool(os.environ.get("KAIZEN_STUDIO_SSL_CERTFILE"))
        ),
        samesite="strict",
        path="/",
    )


@app.get("/api/admin/users")
def list_local_accounts() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, is_active, created_at FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def create_local_account(payload: AdminAccountCreate) -> dict[str, Any]:
    username = payload.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", username):
        raise HTTPException(
            status_code=422,
            detail="L'identifiant doit contenir 3 à 64 caractères (lettres, chiffres, ., _, @ ou -).",
        )
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                (username, hash_password(payload.password), int(payload.is_admin)),
            )
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed" in str(error):
            raise HTTPException(status_code=409, detail="Cet identifiant existe déjà.") from error
        raise
    return {
        "id": user_id,
        "username": username,
        "is_admin": payload.is_admin,
        "is_active": True,
    }


@app.put("/api/admin/users/{user_id}/password")
def reset_local_account_password(user_id: int, payload: PasswordReset) -> dict[str, str]:
    with get_connection() as conn:
        user = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Compte introuvable.")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(payload.new_password), user_id),
        )
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    return {"status": "Mot de passe réinitialisé. L'utilisateur devra se reconnecter."}


@app.patch("/api/admin/users/{user_id}/active")
def set_local_account_active(user_id: int, payload: dict[str, bool], request: Request) -> dict[str, Any]:
    active = payload.get("is_active")
    if not isinstance(active, bool):
        raise HTTPException(status_code=422, detail="Le champ is_active doit être un booléen.")
    if user_id == int(request.state.user["id"]) and not active:
        raise HTTPException(status_code=422, detail="Vous ne pouvez pas désactiver votre propre compte.")
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Compte introuvable.")
        if not active and user["is_admin"]:
            active_admins = conn.execute(
                "SELECT COUNT(*) AS count FROM users WHERE is_admin = 1 AND is_active = 1"
            ).fetchone()["count"]
            if int(active_admins) <= 1:
                raise HTTPException(status_code=409, detail="Le dernier administrateur actif ne peut pas être désactivé.")
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(active), user_id))
        if not active:
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    return {"id": user_id, "username": user["username"], "is_admin": bool(user["is_admin"]), "is_active": active}


@app.get("/api/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, nom, takt_s, cree_le FROM projects WHERE owner_user_id = ? ORDER BY cree_le DESC",
            (int(request.state.user["id"]),),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/dashboard")
def get_dashboard(request: Request) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        projects = conn.execute(
            "SELECT id, nom, takt_s, cree_le FROM projects WHERE owner_user_id = ? ORDER BY cree_le DESC",
            (int(request.state.user["id"]),),
        ).fetchall()
        station_rows = conn.execute(
            """
            SELECT st.id, st.project_id, st.nom, st.video_path, st.video_duration_s, st.video_fps,
                   st.motion_signal_json, st.posture_signal_json,
                   COUNT(DISTINCT ph.id) AS phase_count,
                   (
                     SELECT ea.rula_score FROM ergonomic_assessments ea
                     WHERE ea.station_id = st.id AND ea.rula_score IS NOT NULL
                     ORDER BY ea.created_at DESC, ea.id DESC LIMIT 1
                   ) AS latest_rula_score,
                   (
                     SELECT ea.reba_score FROM ergonomic_assessments ea
                     WHERE ea.station_id = st.id AND ea.reba_score IS NOT NULL
                     ORDER BY ea.created_at DESC, ea.id DESC LIMIT 1
                   ) AS latest_reba_score,
                   (
                     SELECT COUNT(*) FROM ergonomic_assessments ea
                     WHERE ea.station_id = st.id
                   ) AS assessment_count
            FROM stations st
            LEFT JOIN phases ph ON ph.station_id = st.id
            JOIN projects p ON p.id = st.project_id
            WHERE p.owner_user_id = ?
            GROUP BY st.id
            ORDER BY st.id ASC
            """,
            (int(request.state.user["id"]),),
        ).fetchall()

    stations_by_project: dict[int, list[dict[str, Any]]] = {}
    for row in station_rows:
        station = dict(row)
        station["analysis_status"] = (
            "À analyser" if not station["motion_signal_json"]
            else "Suivi posture disponible" if station["posture_signal_json"]
            else "Mouvement analysé"
        )
        station["latest_rula_level"] = (
            _assessment_risk("RULA", int(station["latest_rula_score"]))
            if station["latest_rula_score"] is not None else None
        )
        station["latest_reba_level"] = (
            _assessment_risk("REBA", int(station["latest_reba_score"]))
            if station["latest_reba_score"] is not None else None
        )
        station["has_video"] = bool(station["video_path"])
        station.pop("video_path")
        station.pop("motion_signal_json")
        station.pop("posture_signal_json")
        stations_by_project.setdefault(int(station["project_id"]), []).append(station)

    result_projects = []
    for project_row in projects:
        project = dict(project_row)
        project_stations = stations_by_project.get(int(project["id"]), [])
        project["stations"] = project_stations
        project["station_count"] = len(project_stations)
        project["analyzed_station_count"] = sum(
            station["analysis_status"] != "À analyser" for station in project_stations
        )
        project["assessment_count"] = sum(
            int(station["assessment_count"]) for station in project_stations
        )
        result_projects.append(project)
    return {
        "project_count": len(result_projects),
        "station_count": sum(project["station_count"] for project in result_projects),
        "assessment_count": sum(project["assessment_count"] for project in result_projects),
        "projects": result_projects,
    }


@app.post("/api/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (nom, takt_s, owner_user_id) VALUES (?, ?, ?)",
            (payload.nom, float(payload.takt_s), int(request.state.user["id"])),
        )
        project_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, nom, takt_s, cree_le FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return dict(row)


@app.get("/api/projects/{project_id}")
def get_project(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute(
            "SELECT id, nom, takt_s, cree_le FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        stations = conn.execute(
            "SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin "
            "FROM stations WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        ).fetchall()
    project_dict = dict(project)
    project_dict["stations"] = [dict(station) for station in stations]
    return project_dict


@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE projects SET takt_s = ? WHERE id = ?",
            (float(payload.takt_s), project_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        project = conn.execute(
            "SELECT id, nom, takt_s, cree_le FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    return dict(project)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        stations = conn.execute(
            "SELECT id, video_path FROM stations WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    station_ids = {int(station["id"]) for station in stations}
    with analysis_jobs_lock:
        if any(
            int(job["station_id"]) in station_ids and job["status"] in {"queued", "running"}
            for job in analysis_jobs.values()
        ):
            raise HTTPException(status_code=409, detail="Impossible de supprimer le projet pendant une analyse.")
    unmanaged_video = False
    try:
        _remove_operation_model(project_id)
        for station in stations:
            if station["video_path"] and _managed_file_path(station["video_path"], VIDEO_ROOT) is None:
                unmanaged_video = True
            _remove_managed_file(station["video_path"], VIDEO_ROOT)
        _remove_managed_file(
            str(EXPORT_ROOT / f"kaizen_studio_projet_{project_id}.xlsx"),
            EXPORT_ROOT,
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Échec de suppression des fichiers locaux : {error}") from error
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM video_annotations
            WHERE station_id IN (SELECT id FROM stations WHERE project_id = ?)
            """,
            (project_id,),
        )
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    result = {"status": "deleted", "project_id": str(project_id)}
    if unmanaged_video:
        result["warning"] = "Un fichier référencé hors du dossier vidéo de Kaizen Studio n'a pas été supprimé."
    return result


@app.get("/api/projects/{project_id}/stations")
def list_stations(project_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin, video_duration_s, video_fps "
            "FROM stations WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/projects/{project_id}/operations")
def list_project_operations(project_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        rows = conn.execute(
            """
            SELECT op.id, op.nom,
                   (SELECT COUNT(*) FROM phases ph
                    JOIN stations st ON st.id = ph.station_id
                    WHERE st.project_id = op.project_id
                      AND LOWER(TRIM(ph.description)) = LOWER(op.nom)) AS occurrences,
                   (SELECT COUNT(*) FROM video_annotations va
                    JOIN stations st ON st.id = va.station_id
                    WHERE st.project_id = op.project_id AND va.operation_id = op.id) AS annotations
            FROM project_operations op
            WHERE op.project_id = ?
            ORDER BY op.nom COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/projects/{project_id}/operations", status_code=status.HTTP_201_CREATED)
def create_project_operation(project_id: int, payload: ProjectOperationCreate) -> dict[str, Any]:
    ensure_initialized()
    name = payload.nom.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Le nom de l'opération ne peut pas être vide.")
    with get_connection() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable.")
        existing = conn.execute(
            "SELECT id FROM project_operations WHERE project_id = ? AND nom = ? COLLATE NOCASE",
            (project_id, name),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Cette opération existe déjà dans le projet.")
        _remove_operation_model(project_id)
        cursor = conn.execute(
            "INSERT INTO project_operations (project_id, nom) VALUES (?, ?)",
            (project_id, name),
        )
        operation = conn.execute(
            "SELECT id, project_id, nom, created_at FROM project_operations WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(operation)


@app.patch("/api/projects/{project_id}/operations/{operation_id}")
def update_project_operation(
    project_id: int,
    operation_id: int,
    payload: ProjectOperationUpdate,
) -> dict[str, Any]:
    ensure_initialized()
    name = payload.nom.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Le nom de l'opération ne peut pas être vide.")
    with get_connection() as conn:
        operation = conn.execute(
            "SELECT id FROM project_operations WHERE id = ? AND project_id = ?",
            (operation_id, project_id),
        ).fetchone()
        if operation is None:
            raise HTTPException(status_code=404, detail="Opération introuvable.")
        duplicate = conn.execute(
            "SELECT id FROM project_operations WHERE project_id = ? AND nom = ? COLLATE NOCASE AND id <> ?",
            (project_id, name, operation_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Une opération porte déjà ce nom dans le projet.")
        _remove_operation_model(project_id)
        conn.execute(
            "UPDATE project_operations SET nom = ? WHERE id = ? AND project_id = ?",
            (name, operation_id, project_id),
        )
        updated = conn.execute(
            "SELECT id, project_id, nom, created_at FROM project_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
    return dict(updated)


@app.delete("/api/projects/{project_id}/operations/{operation_id}")
def delete_project_operation(project_id: int, operation_id: int) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        operation = conn.execute(
            "SELECT id, nom FROM project_operations WHERE id = ? AND project_id = ?",
            (operation_id, project_id),
        ).fetchone()
        if operation is None:
            raise HTTPException(status_code=404, detail="Opération introuvable.")
        used_by_annotation = conn.execute(
            "SELECT 1 FROM video_annotations WHERE operation_id = ? LIMIT 1",
            (operation_id,),
        ).fetchone()
        used_by_phase = conn.execute(
            """
            SELECT 1 FROM phases ph
            JOIN stations st ON st.id = ph.station_id
            WHERE st.project_id = ? AND ph.description = ? COLLATE NOCASE
            LIMIT 1
            """,
            (project_id, operation["nom"]),
        ).fetchone()
        if used_by_annotation or used_by_phase:
            raise HTTPException(
                status_code=409,
                detail="Cette opération est utilisée par des annotations ou des étapes et ne peut pas être supprimée.",
            )
        _remove_operation_model(project_id)
        conn.execute(
            "DELETE FROM project_operations WHERE id = ? AND project_id = ?",
            (operation_id, project_id),
        )
    return {"status": "Opération supprimée."}


@app.get("/api/projects/{project_id}/annotation-dataset")
def get_project_annotation_dataset(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute(
            "SELECT id, nom FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable.")
        split_rows = conn.execute(
            """
            SELECT dataset_split AS split, COUNT(*) AS videos,
                   SUM((SELECT COUNT(*) FROM video_annotations va WHERE va.station_id = st.id)) AS annotations
            FROM stations st
            WHERE project_id = ?
            GROUP BY dataset_split
            """,
            (project_id,),
        ).fetchall()
        operation_rows = conn.execute(
            """
            SELECT op.id, op.nom, COUNT(va.id) AS annotations,
                   SUM(CASE WHEN st.dataset_split = 'train' THEN 1 ELSE 0 END) AS train,
                   SUM(CASE WHEN st.dataset_split = 'validation' THEN 1 ELSE 0 END) AS validation
            FROM project_operations op
            LEFT JOIN video_annotations va ON va.operation_id = op.id
            LEFT JOIN stations st ON st.id = va.station_id
            WHERE op.project_id = ?
            GROUP BY op.id, op.nom
            ORDER BY op.nom COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall()
    _, _, signature = _operation_learning_data(project_id)
    model = _operation_model_status(project_id, signature)
    return {
        "project": dict(project),
        "splits": {row["split"]: {"videos": row["videos"], "annotations": row["annotations"] or 0} for row in split_rows},
        "operations": [dict(row) for row in operation_rows],
        "model_status": model["model_status"],
        "model": model,
        "message": model["message"],
    }


@app.get("/api/projects/{project_id}/operation-model")
def get_project_operation_model(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    _, _, signature = _operation_learning_data(project_id)
    return _operation_model_status(project_id, signature)


@app.post("/api/projects/{project_id}/operation-model/train")
def train_project_operation_model(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    train_samples, validation_samples, signature = _operation_learning_data(project_id)
    training_videos = {_video_identity(sample.video_path) for sample in train_samples if sample.video_path}
    validation_videos = {_video_identity(sample.video_path) for sample in validation_samples if sample.video_path}
    if training_videos & validation_videos:
        raise HTTPException(
            status_code=422,
            detail="Une même vidéo ne peut pas être répartie entre l'entraînement et la validation.",
        )
    model_path, metadata_path = _operation_model_paths(project_id)
    try:
        metadata = train_operation_model(
            project_id,
            train_samples,
            validation_samples,
            model_path,
            metadata_path,
            signature,
        )
    except OperationLearningError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        **metadata,
        "model_status": "trained",
        "is_stale": False,
        "message": (
            "Modèle local entraîné. La validation utilise des vidéos séparées ; les scores restent indicatifs."
        ),
    }


@app.post("/api/stations/{station_id}/operation-suggestions")
def suggest_station_operations(station_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            """
            SELECT id, project_id, video_path, roi, dataset_split
            FROM stations WHERE id = ?
            """,
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        if station["dataset_split"] != "excluded":
            raise HTTPException(
                status_code=409,
                detail="Pour éviter de réutiliser les vidéos d'entraînement ou de validation, "
                "les suggestions sont réservées aux vidéos exclues de ces deux jeux.",
            )
        phases = conn.execute(
            """
            SELECT id, debut_s, fin_s FROM phases
            WHERE station_id = ? AND type_auto = 'activity'
            ORDER BY debut_s, id
            """,
            (station_id,),
        ).fetchall()
        annotations = conn.execute(
            "SELECT debut_s, fin_s FROM video_annotations WHERE station_id = ?",
            (station_id,),
        ).fetchall()

    if not station["video_path"] or not Path(station["video_path"]).is_file():
        raise HTTPException(status_code=422, detail="La vidéo locale du poste est introuvable.")

    _, _, signature = _operation_learning_data(int(station["project_id"]))
    model_status = _operation_model_status(int(station["project_id"]), signature)
    if model_status["model_status"] == "stale":
        raise HTTPException(status_code=409, detail=model_status["message"])
    if model_status["model_status"] != "trained":
        raise HTTPException(status_code=409, detail=model_status["message"])
    model_path, metadata_path = _operation_model_paths(int(station["project_id"]))
    try:
        svm, metadata = load_operation_model(model_path, metadata_path)
        suggestions: list[dict[str, Any]] = []
        uncertain = 0
        already_annotated = 0
        for phase in phases:
            start = float(phase["debut_s"])
            end = float(phase["fin_s"])
            if any(start < float(row["fin_s"]) and end > float(row["debut_s"]) for row in annotations):
                already_annotated += 1
                continue
            prediction = predict_operation(
                svm,
                metadata,
                str(station["video_path"]),
                start,
                end,
                station["roi"],
            )
            if not prediction["accepted"]:
                uncertain += 1
                continue
            suggestions.append(
                {
                    "phase_id": int(phase["id"]),
                    "debut_s": start,
                    "fin_s": end,
                    **prediction,
                }
            )
    except OperationLearningError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return {
        "suggestions": suggestions,
        "considered": len(phases),
        "uncertain": uncertain,
        "already_annotated": already_annotated,
        "minimum_confidence": MIN_SUGGESTION_CONFIDENCE,
        "message": "Suggestions locales à vérifier sur la vidéo. Elles ne créent aucune annotation automatiquement.",
    }


@app.get("/api/projects/{project_id}/annotation-manifest")
def export_project_annotation_manifest(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute(
            "SELECT id, nom FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable.")
        stations = conn.execute(
            """
            SELECT id, nom, video_duration_s, dataset_split
            FROM stations WHERE project_id = ? ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        videos = []
        for station in stations:
            annotations = conn.execute(
                """
                SELECT va.id, va.debut_s, va.fin_s, va.operation_id,
                       COALESCE(op.nom, 'Autre / incertain') AS operation
                FROM video_annotations va
                LEFT JOIN project_operations op ON op.id = va.operation_id
                WHERE va.station_id = ?
                ORDER BY va.debut_s, va.id
                """,
                (station["id"],),
            ).fetchall()
            videos.append({**dict(station), "annotations": [dict(row) for row in annotations]})
    return {
        "format": "kaizen-studio-annotations-v1",
        "project": dict(project),
        "videos": videos,
        "notice": "Les annotations sont des labels humains. Les résultats d'un éventuel modèle seront des estimations à valider.",
    }


def _station_annotation_row(conn, station_id: int, annotation_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT va.id, va.station_id, va.operation_id, va.debut_s, va.fin_s, va.created_at,
               COALESCE(op.nom, 'Autre / incertain') AS operation
        FROM video_annotations va
        LEFT JOIN project_operations op ON op.id = va.operation_id
        WHERE va.id = ? AND va.station_id = ?
        """,
        (annotation_id, station_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Annotation introuvable.")
    return dict(row)


def _validate_annotation_interval(
    conn,
    station_id: int,
    start: float,
    end: float,
    exclude_id: int | None = None,
) -> None:
    if end <= start:
        raise HTTPException(status_code=422, detail="La fin doit être après le début de l'annotation.")
    station = conn.execute(
        "SELECT video_duration_s FROM stations WHERE id = ?",
        (station_id,),
    ).fetchone()
    if station is None:
        raise HTTPException(status_code=404, detail="Poste introuvable.")
    duration = station["video_duration_s"]
    if duration is not None and end > float(duration) + 0.05:
        raise HTTPException(status_code=422, detail="L'annotation dépasse la durée de la vidéo.")
    query = """
        SELECT id FROM video_annotations
        WHERE station_id = ? AND debut_s < ? AND fin_s > ?
    """
    params: list[Any] = [station_id, end, start]
    if exclude_id is not None:
        query += " AND id <> ?"
        params.append(exclude_id)
    query += " LIMIT 1"
    if conn.execute(query, params).fetchone():
        raise HTTPException(
            status_code=409,
            detail="Les annotations d'une vidéo ne peuvent pas se chevaucher dans ce premier jeu de labels.",
        )


@app.get("/api/stations/{station_id}/annotations")
def list_station_annotations(station_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        rows = conn.execute(
            """
            SELECT va.id, va.station_id, va.operation_id, va.debut_s, va.fin_s, va.created_at,
                   COALESCE(op.nom, 'Autre / incertain') AS operation
            FROM video_annotations va
            LEFT JOIN project_operations op ON op.id = va.operation_id
            WHERE va.station_id = ? ORDER BY va.debut_s, va.id
            """,
            (station_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/stations/{station_id}/annotations", status_code=status.HTTP_201_CREATED)
def create_video_annotation(station_id: int, payload: VideoAnnotationCreate) -> dict[str, Any]:
    ensure_initialized()
    start = round(payload.debut_s, 1)
    end = round(payload.fin_s, 1)
    with get_connection() as conn:
        _validate_annotation_interval(conn, station_id, start, end)
        if payload.operation_id is not None:
            operation = conn.execute(
                """
                SELECT op.id FROM project_operations op
                JOIN stations st ON st.project_id = op.project_id
                WHERE op.id = ? AND st.id = ?
                """,
                (payload.operation_id, station_id),
            ).fetchone()
            if operation is None:
                raise HTTPException(status_code=422, detail="L'opération n'appartient pas au projet de cette vidéo.")
        station = conn.execute(
            "SELECT project_id, dataset_split FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station["dataset_split"] in {"train", "validation"}:
            _remove_operation_model(int(station["project_id"]))
        cursor = conn.execute(
            """
            INSERT INTO video_annotations (station_id, operation_id, debut_s, fin_s)
            VALUES (?, ?, ?, ?)
            """,
            (station_id, payload.operation_id, start, end),
        )
        created = _station_annotation_row(conn, station_id, int(cursor.lastrowid))
    return created


@app.patch("/api/stations/{station_id}/annotations/{annotation_id}")
def update_video_annotation(
    station_id: int,
    annotation_id: int,
    payload: VideoAnnotationUpdate,
) -> dict[str, Any]:
    ensure_initialized()
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune modification fournie.")
    with get_connection() as conn:
        current = conn.execute(
            "SELECT * FROM video_annotations WHERE id = ? AND station_id = ?",
            (annotation_id, station_id),
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Annotation introuvable.")
        start = round(float(updates.get("debut_s", current["debut_s"])), 1)
        end = round(float(updates.get("fin_s", current["fin_s"])), 1)
        _validate_annotation_interval(conn, station_id, start, end, annotation_id)
        operation_id = updates.get("operation_id", current["operation_id"])
        if operation_id is not None:
            operation = conn.execute(
                """
                SELECT op.id FROM project_operations op
                JOIN stations st ON st.project_id = op.project_id
                WHERE op.id = ? AND st.id = ?
                """,
                (operation_id, station_id),
            ).fetchone()
            if operation is None:
                raise HTTPException(status_code=422, detail="L'opération n'appartient pas au projet de cette vidéo.")
        station = conn.execute(
            "SELECT project_id, dataset_split FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station["dataset_split"] in {"train", "validation"}:
            _remove_operation_model(int(station["project_id"]))
        conn.execute(
            """
            UPDATE video_annotations
            SET operation_id = ?, debut_s = ?, fin_s = ?
            WHERE id = ? AND station_id = ?
            """,
            (operation_id, start, end, annotation_id, station_id),
        )
        updated = _station_annotation_row(conn, station_id, annotation_id)
    return updated


@app.delete("/api/stations/{station_id}/annotations/{annotation_id}")
def delete_video_annotation(station_id: int, annotation_id: int) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            "SELECT project_id, dataset_split FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        annotation = conn.execute(
            "SELECT id FROM video_annotations WHERE id = ? AND station_id = ?",
            (annotation_id, station_id),
        ).fetchone()
        if annotation is None:
            raise HTTPException(status_code=404, detail="Annotation introuvable.")
        if station["dataset_split"] in {"train", "validation"}:
            _remove_operation_model(int(station["project_id"]))
        cursor = conn.execute(
            "DELETE FROM video_annotations WHERE id = ? AND station_id = ?",
            (annotation_id, station_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Annotation introuvable.")
    return {"status": "Annotation supprimée."}


@app.put("/api/stations/{station_id}/dataset-split")
def update_station_dataset_split(station_id: int, payload: DatasetSplitUpdate) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            "SELECT project_id, video_path FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        if payload.split in {"train", "validation"} and station["video_path"]:
            identity = _video_identity(str(station["video_path"]))
            other_stations = conn.execute(
                """
                SELECT id, video_path, dataset_split FROM stations
                WHERE project_id = ? AND id <> ? AND dataset_split IN ('train', 'validation')
                """,
                (station["project_id"], station_id),
            ).fetchall()
            if any(
                row["dataset_split"] != payload.split
                and row["video_path"]
                and _video_identity(str(row["video_path"])) == identity
                for row in other_stations
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cette même vidéo est déjà affectée à l'autre split. "
                    "La séparation entraînement/validation doit se faire par vidéo entière.",
                )
        _remove_operation_model(int(station["project_id"]))
        cursor = conn.execute(
            "UPDATE stations SET dataset_split = ? WHERE id = ?",
            (payload.split, station_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
    return {"split": payload.split}


@app.post("/api/projects/{project_id}/stations", status_code=status.HTTP_201_CREATED)
def create_station(project_id: int, payload: StationCreate) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        cursor = conn.execute(
            """
            INSERT INTO stations (project_id, nom, video_path, roi, fenetre_debut, fenetre_fin)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                payload.nom.strip(),
                _legacy_video_path(payload.video_path),
                _validated_roi(payload.roi),
                payload.fenetre_debut,
                payload.fenetre_fin,
            ),
        )
        station = conn.execute(
            "SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin, video_duration_s, video_fps FROM stations WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(station)


@app.post("/api/projects/{project_id}/stations/import", status_code=status.HTTP_201_CREATED)
async def create_station_with_video(
    project_id: int,
    nom: str = Form(..., min_length=1, max_length=200),
    video: UploadFile = File(...),
) -> dict[str, Any]:
    ensure_initialized()
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi"}:
        raise HTTPException(status_code=400, detail="Formats autorisés : MP4, MOV et AVI.")

    with get_connection() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        setting = conn.execute(
            "SELECT valeur FROM settings WHERE cle = 'video_max_mb'"
        ).fetchone()

    try:
        max_bytes = int(setting["valeur"]) * 1024 * 1024
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Le réglage video_max_mb est invalide.") from error

    async def upload_chunks() -> AsyncIterator[bytes]:
        while chunk := await video.read(1024 * 1024):
            yield chunk

    try:
        return await _store_station_video(
            project_id,
            nom,
            suffix,
            upload_chunks(),
            max_bytes,
        )
    finally:
        await video.close()


@app.post("/api/projects/{project_id}/stations/import-stream", status_code=status.HTTP_201_CREATED)
async def create_station_with_streamed_video(
    project_id: int,
    request: Request,
    nom: str = Query(..., min_length=1, max_length=200),
    filename: str = Query(..., min_length=1, max_length=255),
) -> dict[str, Any]:
    ensure_initialized()
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi"}:
        raise HTTPException(status_code=400, detail="Formats autorisés : MP4, MOV et AVI.")

    with get_connection() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        setting = conn.execute(
            "SELECT valeur FROM settings WHERE cle = 'video_max_mb'"
        ).fetchone()

    try:
        max_bytes = int(setting["valeur"]) * 1024 * 1024
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Le réglage video_max_mb est invalide.") from error

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Taille de requête invalide.") from error
        if declared_size > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Vidéo trop volumineuse. Taille maximale configurée : {max_bytes // (1024 * 1024)} Mo.",
            )

    return await _store_station_video(
        project_id,
        nom.strip(),
        suffix,
        request.stream(),
        max_bytes,
    )


async def _store_station_video(
    project_id: int,
    nom: str,
    suffix: str,
    chunks: AsyncIterator[bytes],
    max_bytes: int,
) -> dict[str, Any]:
    VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
    temporary_path = VIDEO_ROOT / f"upload_{os.urandom(12).hex()}.tmp{suffix}"
    size_bytes = 0
    final_path: Path | None = None
    upload_saved = False
    try:
        with temporary_path.open("wb") as destination:
            async for chunk in chunks:
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Vidéo trop volumineuse. Taille maximale configurée : {max_bytes // (1024 * 1024)} Mo.",
                    )
                await asyncio.to_thread(destination.write, chunk)
        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="Le fichier vidéo est vide.")

        capture = open_video_capture(temporary_path)
        if not capture.isOpened():
            capture.release()
            raise HTTPException(status_code=422, detail="OpenCV ne peut pas lire cette vidéo.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        capture.release()
        if fps <= 0 or frame_count <= 0:
            raise HTTPException(status_code=422, detail="Impossible d'extraire la durée ou la fréquence vidéo.")
        duration_s = frame_count / fps

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO stations (project_id, nom, fenetre_debut)
                VALUES (?, ?, 0)
                """,
                (project_id, nom.strip()),
            )
            station_id = cursor.lastrowid
            station_dir = VIDEO_ROOT / f"project_{project_id}" / f"station_{station_id}"
            station_dir.mkdir(parents=True, exist_ok=True)
            final_path = station_dir / f"video{suffix}"
            temporary_path.replace(final_path)
            conn.execute(
                """
                UPDATE stations
                SET video_path = ?, video_duration_s = ?, video_fps = ?
                WHERE id = ?
                """,
                (str(final_path), duration_s, fps, station_id),
            )
            station = conn.execute(
                """
                SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin,
                       video_duration_s, video_fps, motion_signal_json, motion_threshold_pct,
                       posture_signal_json, dataset_split
                FROM stations WHERE id = ?
                """,
                (station_id,),
            ).fetchone()
        upload_saved = True
        return dict(station)
    except HTTPException:
        raise
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Échec de l'enregistrement local de la vidéo : {error}") from error
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
        if not upload_saved and final_path is not None and final_path.exists():
            final_path.unlink()


@app.get("/api/stations/{station_id}")
def get_station(station_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            """
            SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin,
                   video_duration_s, video_fps, dataset_split, motion_signal_json, motion_threshold_pct,
                   posture_signal_json, analysis_configuration_json
            FROM stations WHERE id = ?
            """,
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        phases = conn.execute(
            "SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description, categorie, commentaire, chrono_reel_s, mouvement_moyen_pct "
            "FROM phases WHERE station_id = ? ORDER BY ordre ASC",
            (station_id,),
        ).fetchall()
        assessments = conn.execute(
            """
            SELECT id, station_id, time_s, rula_score, reba_score, evaluator,
                   factors_notes, created_at
            FROM ergonomic_assessments WHERE station_id = ?
            ORDER BY time_s, id
            """,
            (station_id,),
        ).fetchall()
        annotations = conn.execute(
            """
            SELECT va.id, va.station_id, va.operation_id, va.debut_s, va.fin_s, va.created_at,
                   COALESCE(op.nom, 'Autre / incertain') AS operation
            FROM video_annotations va
            LEFT JOIN project_operations op ON op.id = va.operation_id
            WHERE va.station_id = ? ORDER BY va.debut_s, va.id
            """,
            (station_id,),
        ).fetchall()
    result = dict(station)
    try:
        result["analysis_configuration"] = json.loads(
            result.pop("analysis_configuration_json") or "{}"
        )
    except json.JSONDecodeError as error:
        logger.exception("Configuration locale illisible pour le poste %s", station_id)
        raise HTTPException(
            status_code=500,
            detail="La configuration locale de ce poste est illisible.",
        ) from error
    result["phases"] = [dict(row) for row in phases]
    result["annotations"] = [dict(row) for row in annotations]
    result["ergonomic_assessments"] = []
    for row in assessments:
        assessment = dict(row)
        if assessment["rula_score"] is not None:
            assessment["rula_level"] = _assessment_risk("RULA", int(assessment["rula_score"]))
        if assessment["reba_score"] is not None:
            assessment["reba_level"] = _assessment_risk("REBA", int(assessment["reba_score"]))
        result["ergonomic_assessments"].append(assessment)
    return result


@app.put("/api/stations/{station_id}/analysis-configuration")
def update_station_analysis_configuration(
    station_id: int, payload: AnalysisConfigurationUpdate
) -> dict[str, Any]:
    ensure_initialized()
    allowed_fields = {
        "review": {
            "threshold_pct", "min_phase_seconds", "window_start", "window_end",
        },
        "operations": {
            "operation_name", "dataset_split", "annotation_operation",
            "annotation_start", "annotation_end",
        },
        "cycles": {
            "cycle_start", "cycle_end", "minimum_stop", "minimum_cycle",
        },
        "ergonomics": {
            "view_camera", "charge_kg", "type_effort", "prise", "torsion_tronc",
            "inclinaison_laterale_tronc", "torsion_cou",
            "inclinaison_laterale_cou", "epaule_surelevee", "abduction_bras",
            "bras_soutenu", "avant_bras_croise_ligne_mediane",
            "deviation_poignet", "rotation_poignet", "appui_jambes",
            "frequence_geste_par_min", "posture_statique_sup_1min", "time_s",
            "rula_score", "reba_score", "evaluator", "factors_notes",
        },
    }
    if not payload.values or payload.values.keys() - allowed_fields[payload.section]:
        raise HTTPException(status_code=422, detail="La configuration contient des champs non autorisés.")
    for key, value in payload.values.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise HTTPException(status_code=422, detail="Valeur de configuration invalide.")
        if isinstance(value, str) and len(value) > 4000:
            raise HTTPException(status_code=422, detail="Une valeur de configuration est trop longue.")
        if isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(status_code=422, detail="Valeur numérique de configuration invalide.")
    numeric_limits = {
        "threshold_pct": (0, 100),
        "min_phase_seconds": (0.2, 4),
        "window_start": (0, None),
        "window_end": (0, None),
        "minimum_stop": (0.5, 600),
        "minimum_cycle": (1, 3600),
        "charge_kg": (0, None),
        "frequence_geste_par_min": (0, None),
        "time_s": (0, None),
        "rula_score": (1, 7),
        "reba_score": (1, 15),
    }
    for key, limits in numeric_limits.items():
        if key not in payload.values or payload.values[key] in (None, ""):
            continue
        try:
            number = float(payload.values[key])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"La valeur « {key} » doit être numérique.") from error
        if not math.isfinite(number) or number < limits[0] or (
            limits[1] is not None and number > limits[1]
        ):
            raise HTTPException(status_code=422, detail=f"La valeur « {key} » est hors limites.")
    if payload.values.get("dataset_split") not in (None, "train", "validation", "excluded"):
        raise HTTPException(status_code=422, detail="Affectation de vidéo invalide.")
    if payload.values.get("view_camera") not in (
        None, "inconnue", "face", "profil_gauche", "profil_droit", "oblique",
    ):
        raise HTTPException(status_code=422, detail="Vue caméra invalide.")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT analysis_configuration_json FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        try:
            configuration = json.loads(row["analysis_configuration_json"] or "{}")
        except json.JSONDecodeError as error:
            logger.exception("Configuration locale illisible pour le poste %s", station_id)
            raise HTTPException(
                status_code=500,
                detail="La configuration locale de ce poste est illisible.",
            ) from error
        if not isinstance(configuration, dict):
            raise HTTPException(
                status_code=500,
                detail="La configuration locale de ce poste a un format invalide.",
            )
        section_values = configuration.setdefault(payload.section, {})
        if not isinstance(section_values, dict):
            raise HTTPException(
                status_code=500,
                detail="La configuration locale de ce poste a un format invalide.",
            )
        section_values.update(payload.values)
        conn.execute(
            "UPDATE stations SET analysis_configuration_json = ? WHERE id = ?",
            (json.dumps(configuration, ensure_ascii=False, allow_nan=False), station_id),
        )
    return {"section": payload.section, "values": section_values}


def _assessment_risk(method: str, score: int) -> str:
    if method == "RULA":
        if score <= 2:
            return "Acceptable"
        if score <= 4:
            return "À investiguer"
        if score <= 6:
            return "Action à court terme"
        return "Action immédiate"
    if score == 1:
        return "Négligeable"
    if score <= 3:
        return "Faible"
    if score <= 7:
        return "Moyen"
    if score <= 10:
        return "Élevé"
    return "Très élevé"


@app.post("/api/ergonomics/score")
def calculate_ergonomic_precotation(payload: ErgonomicScoringRequest) -> dict[str, Any]:
    """Calcule localement une pré-cotation RULA/REBA sans modifier les données enregistrées."""
    factors = dict(payload.evaluator_factors)
    temporal_summary = None
    derived_factors: list[str] = []
    try:
        if payload.series:
            temporal_summary = summarize_series(payload.series, payload.view_camera, factors)
            if factors.get("frequence_geste_par_min") is None:
                factors["frequence_geste_par_min"] = temporal_summary.get("frequence_estimee_gestes_min")
                derived_factors.append("fréquence des gestes estimée par la série temporelle")
            if factors.get("posture_statique_sup_1min") is None:
                factors["posture_statique_sup_1min"] = temporal_summary.get("posture_statique_sup_60s")
                derived_factors.append("statisme estimé par la série temporelle")
        result = score_posture(payload.instant_s, payload.angles, payload.view_camera, factors)
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"Entrées de pré-cotation invalides : {error}") from error
    if temporal_summary is not None:
        result["serie_temporelle"] = temporal_summary
        if derived_factors:
            result["donnees_manquantes"].extend(derived_factors)
            result["hypotheses"].extend(
                f"{factor} ; estimation indicative à vérifier par l’évaluateur."
                for factor in derived_factors
            )
            result["fiabilite"] = "faible" if len(result["donnees_manquantes"]) > 2 else "moyenne"
    return result


@app.post("/api/stations/{station_id}/ergonomic-assessments", status_code=status.HTTP_201_CREATED)
def create_ergonomic_assessment(
    station_id: int,
    payload: ErgonomicAssessmentCreate,
) -> dict[str, Any]:
    ensure_initialized()
    if payload.rula_score is None and payload.reba_score is None:
        raise HTTPException(status_code=422, detail="Saisissez au moins un score RULA ou REBA.")
    if not payload.official_method_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirmez avoir déterminé le score selon la méthode officielle.",
        )
    if not payload.evaluator.strip() or not payload.factors_notes.strip():
        raise HTTPException(
            status_code=422,
            detail="Renseignez le nom de l'évaluateur et les facteurs/observations pris en compte.",
        )
    with get_connection() as conn:
        station = conn.execute(
            "SELECT id, video_duration_s, posture_signal_json FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        if station["video_duration_s"] is not None and payload.time_s > float(station["video_duration_s"]):
            raise HTTPException(status_code=422, detail="L'instant évalué dépasse la durée de la vidéo.")
        snapshot = None
        if station["posture_signal_json"]:
            try:
                samples = json.loads(station["posture_signal_json"])
            except json.JSONDecodeError as error:
                raise HTTPException(status_code=500, detail="Le signal de posture enregistré est illisible.") from error
            if samples:
                nearest_sample = min(samples, key=lambda sample: abs(float(sample["time_s"]) - payload.time_s))
                if abs(float(nearest_sample["time_s"]) - payload.time_s) <= 1:
                    snapshot = nearest_sample
        cursor = conn.execute(
            """
            INSERT INTO ergonomic_assessments (
                station_id, time_s, rula_score, reba_score, evaluator, factors_notes,
                posture_snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                payload.time_s,
                payload.rula_score,
                payload.reba_score,
                payload.evaluator.strip(),
                payload.factors_notes.strip(),
                json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
            ),
        )
        created = conn.execute(
            """
            SELECT id, station_id, time_s, rula_score, reba_score, evaluator,
                   factors_notes, posture_snapshot_json, created_at
            FROM ergonomic_assessments WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    result = dict(created)
    if result["rula_score"] is not None:
        result["rula_level"] = _assessment_risk("RULA", int(result["rula_score"]))
    if result["reba_score"] is not None:
        result["reba_level"] = _assessment_risk("REBA", int(result["reba_score"]))
    return result


@app.get("/api/stations/{station_id}/ergonomic-assessments")
def list_ergonomic_assessments(station_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        assessments = conn.execute(
            """
            SELECT id, station_id, time_s, rula_score, reba_score, evaluator,
                   factors_notes, posture_snapshot_json, created_at
            FROM ergonomic_assessments WHERE station_id = ?
            ORDER BY time_s, id
            """,
            (station_id,),
        ).fetchall()
    result = []
    for row in assessments:
        assessment = dict(row)
        if assessment["rula_score"] is not None:
            assessment["rula_level"] = _assessment_risk("RULA", int(assessment["rula_score"]))
        if assessment["reba_score"] is not None:
            assessment["reba_level"] = _assessment_risk("REBA", int(assessment["reba_score"]))
        result.append(assessment)
    return result


@app.delete("/api/stations/{station_id}")
def delete_station(station_id: int) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            "SELECT id, project_id, video_path FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
    if station is None:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    with analysis_jobs_lock:
        if any(
            int(job["station_id"]) == station_id and job["status"] in {"queued", "running"}
            for job in analysis_jobs.values()
        ):
            raise HTTPException(status_code=409, detail="Impossible de supprimer le poste pendant une analyse.")
    managed_path = _managed_file_path(station["video_path"], VIDEO_ROOT)
    try:
        _remove_operation_model(int(station["project_id"]))
        _remove_managed_file(station["video_path"], VIDEO_ROOT)
        _remove_managed_file(
            str(EXPORT_ROOT / f"kaizen_studio_projet_{station['project_id']}.xlsx"),
            EXPORT_ROOT,
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Échec de suppression des fichiers locaux : {error}") from error
    with get_connection() as conn:
        conn.execute("DELETE FROM stations WHERE id = ?", (station_id,))
    result = {"status": "deleted", "station_id": str(station_id)}
    if station["video_path"] and managed_path is None:
        result["warning"] = "Le fichier vidéo référencé hors du dossier géré n'a pas été supprimé."
    return result


@app.get("/api/stations/{station_id}/frame")
def station_video_frame(station_id: int, time_s: float = Query(default=0, ge=0)) -> Response:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            "SELECT video_path, video_duration_s FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
    if station is None:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    video_path = station["video_path"]
    if not video_path or not Path(video_path).is_file():
        raise HTTPException(status_code=404, detail="Vidéo locale introuvable")

    capture = open_video_capture(video_path)
    if not capture.isOpened():
        capture.release()
        raise HTTPException(status_code=422, detail="Impossible d'ouvrir la vidéo pour extraire l'image.")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    duration = float(station["video_duration_s"] or 0)
    if fps <= 0:
        capture.release()
        raise HTTPException(status_code=422, detail="Fréquence d'images invalide dans la vidéo.")
    target_time = min(float(time_s), duration) if duration > 0 else float(time_s)
    capture.set(cv2.CAP_PROP_POS_MSEC, target_time * 1000)
    ok, frame = capture.read()
    if ok:
        frame = orient_video_frame(capture, frame)
    capture.release()
    if not ok:
        raise HTTPException(status_code=422, detail="Impossible d'extraire l'image à cet instant vidéo.")
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="Impossible d'encoder l'image extraite.")
    return Response(content=encoded.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def _run_analysis(job_id: str, station: dict[str, Any], params: AnalysisParams) -> None:
    with analysis_jobs_lock:
        analysis_jobs[job_id]["status"] = "running"

    def update_progress(value: float) -> None:
        with analysis_jobs_lock:
            analysis_jobs[job_id]["progress"] = max(
                analysis_jobs[job_id]["progress"],
                min(99, int(value * 100)),
            )

    def update_signal(samples: list[dict[str, float]], threshold_pct: float) -> None:
        with analysis_jobs_lock:
            analysis_jobs[job_id]["motion_samples"] = samples
            analysis_jobs[job_id]["threshold_pct"] = threshold_pct

    try:
        phases = MotionAnalysisBackend().analyze(
            station["video_path"],
            params,
            progress_callback=update_progress,
            signal_callback=update_signal,
        )
        with analysis_jobs_lock:
            motion_samples = analysis_jobs[job_id]["motion_samples"]
            threshold_pct = analysis_jobs[job_id]["threshold_pct"]
        with get_connection() as conn:
            conn.execute(
                "UPDATE stations SET motion_signal_json = ?, motion_threshold_pct = ? WHERE id = ?",
                (
                    json.dumps(motion_samples, ensure_ascii=False),
                    threshold_pct,
                    station["id"],
                ),
            )
            conn.execute("DELETE FROM phases WHERE station_id = ?", (station["id"],))
            for order, phase in enumerate(phases, start=1):
                description = (
                    "Activité détectée — à décrire"
                    if phase.type == "activity"
                    else "Arrêt détecté — à décrire"
                )
                conn.execute(
                    """
                    INSERT INTO phases (
                        station_id, ordre, debut_s, fin_s, type_auto, description,
                        categorie, mouvement_moyen_pct
                    ) VALUES (?, ?, ?, ?, ?, ?, 'Non classé', ?)
                    """,
                    (
                        station["id"],
                        order,
                        round(phase.start, 1),
                        round(phase.end, 1),
                        phase.type,
                        description,
                        round(phase.motion_mean_pct, 3),
                    ),
                )
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="completed", progress=100, phase_count=len(phases))
    except Exception as error:
        logger.exception("Échec de l'analyse de mouvement du poste %s.", station["id"])
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))


def _run_posture_analysis(job_id: str, station: dict[str, Any], payload: PostureAnalysisRequest) -> None:
    with analysis_jobs_lock:
        analysis_jobs[job_id]["status"] = "running"

    def update_progress(value: float) -> None:
        with analysis_jobs_lock:
            analysis_jobs[job_id]["progress"] = max(
                analysis_jobs[job_id]["progress"],
                min(99, int(value * 100)),
            )

    try:
        samples = analyze_posture_video(
            station["video_path"],
            payload.fenetre_debut,
            payload.fenetre_fin,
            payload.fps,
            progress_callback=update_progress,
        )
        if not samples:
            raise RuntimeError(
                "Aucune posture détectée. Vérifiez le cadrage, l'éclairage et la visibilité de la personne."
            )
        with get_connection() as conn:
            conn.execute(
                "UPDATE stations SET posture_signal_json = ? WHERE id = ?",
                (json.dumps(samples, ensure_ascii=False), station["id"]),
            )
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(
                status="completed",
                progress=100,
                posture_samples=samples,
                sample_count=len(samples),
            )
    except Exception as error:
        logger.exception("Échec du suivi de posture pour le poste %s.", station["id"])
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))


@app.post("/api/stations/{station_id}/posture-analysis", status_code=status.HTTP_202_ACCEPTED)
def start_posture_analysis(
    station_id: int,
    payload: PostureAnalysisRequest,
) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station_row = conn.execute(
            """
            SELECT id, project_id, nom, video_path, video_duration_s
            FROM stations WHERE id = ?
            """,
            (station_id,),
        ).fetchone()
    if station_row is None:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    station = dict(station_row)
    if not station["video_path"] or not Path(station["video_path"]).is_file():
        raise HTTPException(status_code=400, detail="Aucune vidéo locale valide n'est associée à ce poste.")
    capture = open_video_capture(station["video_path"])
    if not capture.isOpened():
        capture.release()
        raise HTTPException(status_code=422, detail="Impossible de lire les métadonnées de la vidéo.")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    capture.release()
    if fps <= 0 or frame_count <= 0:
        raise HTTPException(status_code=422, detail="La vidéo ne fournit pas une durée ou une fréquence valide.")
    video_duration = frame_count / fps
    station["video_duration_s"] = video_duration
    if payload.fenetre_fin > video_duration:
        one_frame_tolerance = 1 / fps
        if payload.fenetre_fin - video_duration > one_frame_tolerance + 1e-6:
            raise HTTPException(status_code=422, detail="La fenêtre de fin dépasse la durée de la vidéo.")
        payload = payload.model_copy(update={"fenetre_fin": video_duration})
    with get_connection() as conn:
        conn.execute(
            "UPDATE stations SET video_duration_s = ?, video_fps = ? WHERE id = ?",
            (video_duration, fps, station_id),
        )
    if payload.fenetre_fin <= payload.fenetre_debut:
        raise HTTPException(status_code=422, detail="La fenêtre de fin doit être supérieure au début.")

    with analysis_jobs_lock:
        if any(
            job["station_id"] == station_id and job["status"] in {"queued", "running"}
            for job in analysis_jobs.values()
        ):
            raise HTTPException(status_code=409, detail="Une analyse est déjà en cours pour ce poste.")
        _prune_finished_jobs_locked()
        job_id = uuid.uuid4().hex
        analysis_jobs[job_id] = {
            "id": job_id,
            "station_id": station_id,
            "kind": "posture",
            "status": "queued",
            "progress": 0,
            "sample_count": None,
            "posture_samples": [],
            "error": None,
        }
    try:
        analysis_executor.submit(_run_posture_analysis, job_id, station, payload)
    except RuntimeError as error:
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))
        raise HTTPException(status_code=503, detail="Le service d'analyse n'est pas disponible.") from error
    return {"job_id": job_id, "status": "queued", "poll_url": f"/api/jobs/{job_id}"}


@app.post("/api/stations/{station_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
def start_station_analysis(
    station_id: int,
    payload: AnalysisRequest,
    force: bool = Query(default=False),
) -> dict[str, Any]:
    ensure_initialized()
    if not force:
        with get_connection() as conn:
            if _station_has_reviewed_phases(conn, station_id):
                raise HTTPException(status_code=409, detail=_REVIEWED_PHASES_MESSAGE)
    with get_connection() as conn:
        station_row = conn.execute(
            """
            SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin,
                   video_duration_s
            FROM stations WHERE id = ?
            """,
            (station_id,),
        ).fetchone()
    if station_row is None:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    station = dict(station_row)
    if not station["video_path"] or not Path(station["video_path"]).is_file():
        raise HTTPException(status_code=400, detail="Aucune vidéo locale valide n'est associée à ce poste.")
    capture = open_video_capture(station["video_path"])
    if not capture.isOpened():
        capture.release()
        raise HTTPException(status_code=422, detail="Impossible de lire les métadonnées de la vidéo.")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    capture.release()
    if fps <= 0 or frame_count <= 0:
        raise HTTPException(status_code=422, detail="La vidéo ne fournit pas une durée ou une fréquence valide.")
    video_duration = frame_count / fps
    station["video_duration_s"] = video_duration

    start = payload.fenetre_debut
    if start is None:
        start = float(station["fenetre_debut"] or 0.0)
    end = payload.fenetre_fin
    if end is None:
        end = station["fenetre_fin"] or station["video_duration_s"]
    if end is None or float(end) <= float(start):
        raise HTTPException(status_code=422, detail="La fenêtre de fin doit être supérieure au début.")
    if float(end) > video_duration:
        if float(end) - video_duration > 1 / fps + 1e-6:
            raise HTTPException(status_code=422, detail="La fenêtre de fin dépasse la durée de la vidéo.")
        end = video_duration
    if float(start) >= video_duration:
        raise HTTPException(status_code=422, detail="Le début de la fenêtre doit être avant la fin de la vidéo.")

    roi_value = payload.roi if payload.roi is not None else station["roi"]
    try:
        roi = parse_roi(roi_value)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    params = AnalysisParams(
        fps=payload.fps,
        start=float(start),
        end=float(end),
        roi=roi,
        min_phase_seconds=payload.duree_min_s,
        auto_threshold_pct=payload.seuil_pct if payload.seuil_pct and payload.seuil_pct > 0 else None,
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE stations
            SET roi = ?, fenetre_debut = ?, fenetre_fin = ?, video_duration_s = ?, video_fps = ?
            WHERE id = ?
            """,
            (
                serialize_roi(roi),
                float(start),
                float(end),
                video_duration,
                fps,
                station_id,
            ),
        )

    with analysis_jobs_lock:
        if any(
            job["station_id"] == station_id and job["status"] in {"queued", "running"}
            for job in analysis_jobs.values()
        ):
            raise HTTPException(status_code=409, detail="Une analyse est déjà en cours pour ce poste.")
        _prune_finished_jobs_locked()
        job_id = uuid.uuid4().hex
        analysis_jobs[job_id] = {
            "id": job_id,
            "station_id": station_id,
            "status": "queued",
            "progress": 0,
            "phase_count": None,
            "motion_samples": [],
            "threshold_pct": None,
            "error": None,
        }
    try:
        analysis_executor.submit(_run_analysis, job_id, station, params)
    except RuntimeError as error:
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))
        raise HTTPException(status_code=503, detail="Le service d'analyse n'est pas disponible.") from error
    return {"job_id": job_id, "status": "queued", "poll_url": f"/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def get_analysis_job(job_id: str) -> dict[str, Any]:
    with analysis_jobs_lock:
        job = analysis_jobs.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Tâche d'analyse introuvable (le serveur a peut-être redémarré).",
            )
        snapshot = dict(job)
        if job.get("status") not in {"queued", "running"}:
            for heavy_key in ("motion_samples", "posture_samples"):
                if heavy_key in job:
                    job[heavy_key] = []
        return snapshot


@app.post("/api/stations/{station_id}/resegment")
def resegment_station(
    station_id: int,
    payload: ResegmentRequest,
    force: bool = Query(default=False),
) -> list[dict[str, Any]]:
    ensure_initialized()
    if not force:
        with get_connection() as conn:
            if _station_has_reviewed_phases(conn, station_id):
                raise HTTPException(status_code=409, detail=_REVIEWED_PHASES_MESSAGE)
    with get_connection() as conn:
        station = conn.execute(
            """
            SELECT motion_signal_json, motion_threshold_pct, fenetre_fin, fenetre_debut
            FROM stations WHERE id = ?
            """,
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        if not station["motion_signal_json"]:
            raise HTTPException(status_code=409, detail="Lance d'abord une analyse vidéo pour créer le signal de mouvement.")
        try:
            samples = json.loads(station["motion_signal_json"])
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=500, detail="Le signal de mouvement enregistré est illisible.") from error

        threshold_pct = payload.seuil_pct
        if threshold_pct is None or threshold_pct == 0:
            threshold_pct = float(station["motion_threshold_pct"] or 0.2)
        phases = segment_motion_signal(
            samples,
            threshold_pct,
            payload.duree_min_s,
            station["fenetre_fin"],
            start_time=station["fenetre_debut"],
        )
        conn.execute("DELETE FROM phases WHERE station_id = ?", (station_id,))
        for order, phase in enumerate(phases, start=1):
            description = (
                "Activité détectée — à décrire"
                if phase.type == "activity"
                else "Arrêt détecté — à décrire"
            )
            conn.execute(
                """
                INSERT INTO phases (
                    station_id, ordre, debut_s, fin_s, type_auto, description,
                    categorie, mouvement_moyen_pct
                ) VALUES (?, ?, ?, ?, ?, ?, 'Non classé', ?)
                """,
                (
                    station_id,
                    order,
                    round(phase.start, 1),
                    round(phase.end, 1),
                    phase.type,
                    description,
                    round(phase.motion_mean_pct, 3),
                ),
            )
        rows = conn.execute(
            """
            SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description,
                   categorie, commentaire, chrono_reel_s, mouvement_moyen_pct
            FROM phases WHERE station_id = ? ORDER BY ordre ASC
            """,
            (station_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.put("/api/stations/{station_id}/analysis-settings")
def update_analysis_settings(station_id: int, payload: AnalysisSettingsUpdate) -> dict[str, Any]:
    ensure_initialized()
    try:
        parse_roi(payload.roi)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if (
        payload.fenetre_debut is not None
        and payload.fenetre_fin is not None
        and payload.fenetre_fin <= payload.fenetre_debut
    ):
        raise HTTPException(status_code=422, detail="La fenêtre de fin doit être supérieure au début.")
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        conn.execute(
            """
            UPDATE stations
            SET roi = ?, fenetre_debut = ?, fenetre_fin = ?
            WHERE id = ?
            """,
            (
                serialize_roi(parse_roi(payload.roi)),
                payload.fenetre_debut,
                payload.fenetre_fin,
                station_id,
            ),
        )
        updated = conn.execute(
            "SELECT id, project_id, nom, video_path, roi, fenetre_debut, fenetre_fin FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
    return dict(updated)


@app.get("/api/stations/{station_id}/phases")
def list_phases(station_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        phases = conn.execute(
            "SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description, categorie, commentaire, chrono_reel_s, mouvement_moyen_pct "
            "FROM phases WHERE station_id = ? ORDER BY ordre ASC",
            (station_id,),
        ).fetchall()
    return [dict(phase) for phase in phases]


@app.get("/api/stations/{station_id}/cycles")
def list_station_cycles(station_id: int) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        rows = conn.execute(
            "SELECT id, station_id, debut_s, fin_s, source, created_at "
            "FROM cycles WHERE station_id = ? ORDER BY debut_s, id",
            (station_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/stations/{station_id}/cycle-candidates")
def get_station_cycle_candidates(
    station_id: int,
    min_stop_s: float = Query(default=2.0, gt=0, le=600),
    min_cycle_s: float = Query(default=5.0, gt=0, le=3600),
) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        rows = conn.execute(
            "SELECT debut_s, fin_s, type_auto FROM phases WHERE station_id = ? ORDER BY debut_s",
            (station_id,),
        ).fetchall()
    candidates = suggest_cycles(
        [dict(row) for row in rows],
        min_stop_seconds=min_stop_s,
        min_cycle_seconds=min_cycle_s,
    )
    return {
        "candidates": candidates,
        "method": "segments d'activité séparés par des arrêts prolongés",
        "warning": (
            "Ces intervalles sont des propositions basées uniquement sur le mouvement et les arrêts. "
            "Vérifiez-les sur la vidéo avant de les ajouter."
        ),
    }


@app.post("/api/stations/{station_id}/cycles", status_code=status.HTTP_201_CREATED)
def create_station_cycle(station_id: int, payload: CycleCreate) -> dict[str, Any]:
    ensure_initialized()
    start = float(payload.debut_s)
    end = float(payload.fin_s)
    if end <= start:
        raise HTTPException(status_code=422, detail="La fin du cycle doit être après son début.")
    with get_connection() as conn:
        station = conn.execute(
            "SELECT id, video_duration_s FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable.")
        if station["video_duration_s"] is not None and end > float(station["video_duration_s"]) + 0.05:
            raise HTTPException(status_code=422, detail="Le cycle dépasse la durée de la vidéo.")
        overlap = conn.execute(
            """
            SELECT 1 FROM cycles
            WHERE station_id = ? AND debut_s < ? AND fin_s > ?
            LIMIT 1
            """,
            (station_id, end, start),
        ).fetchone()
        if overlap:
            raise HTTPException(status_code=409, detail="Ce cycle chevauche un cycle déjà enregistré.")
        cursor = conn.execute(
            "INSERT INTO cycles (station_id, debut_s, fin_s, source) VALUES (?, ?, ?, ?)",
            (station_id, start, end, payload.source),
        )
        created = conn.execute(
            "SELECT id, station_id, debut_s, fin_s, source, created_at FROM cycles WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(created)


@app.delete("/api/stations/{station_id}/cycles/{cycle_id}")
def delete_station_cycle(station_id: int, cycle_id: int) -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM cycles WHERE id = ? AND station_id = ?",
            (cycle_id, station_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cycle introuvable.")
    return {"status": "Cycle supprimé."}


@app.post("/api/stations/{station_id}/phases", status_code=status.HTTP_201_CREATED)
def create_phase(station_id: int, payload: PhaseCreate) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id, project_id FROM stations WHERE id = ?", (station_id,)).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        cursor = conn.execute(
            """
            INSERT INTO phases (
                station_id, ordre, debut_s, fin_s, type_auto, description, categorie,
                commentaire, chrono_reel_s, mouvement_moyen_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                payload.ordre,
                payload.debut_s,
                payload.fin_s,
                payload.type_auto,
                payload.description,
                payload.categorie,
                payload.commentaire,
                payload.chrono_reel_s,
                payload.mouvement_moyen_pct,
            ),
        )
        new_description = (payload.description or "").strip()
        if new_description and not new_description.startswith(_AUTO_PREFIXES):
            conn.execute(
                "INSERT OR IGNORE INTO project_operations (project_id, nom) VALUES (?, ?)",
                (station["project_id"], new_description),
            )
        created = conn.execute(
            "SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description, categorie, commentaire, chrono_reel_s, mouvement_moyen_pct "
            "FROM phases WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(created)


@app.patch("/api/stations/{station_id}/phases/{phase_id}")
def update_phase(station_id: int, phase_id: int, payload: PhaseUpdate) -> dict[str, Any]:
    ensure_initialized()
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Aucune modification fournie.")
    allowed = {
        "debut_s",
        "fin_s",
        "type_auto",
        "description",
        "categorie",
        "commentaire",
        "chrono_reel_s",
    }
    if set(updates) - allowed:
        raise HTTPException(status_code=422, detail="Champ de phase non modifiable.")
    with get_connection() as conn:
        current = conn.execute(
            """
            SELECT ph.*, st.project_id
            FROM phases ph JOIN stations st ON st.id = ph.station_id
            WHERE ph.id = ? AND ph.station_id = ?
            """,
            (phase_id, station_id),
        ).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Phase introuvable")
        start = float(updates.get("debut_s", current["debut_s"]))
        end = float(updates.get("fin_s", current["fin_s"]))
        if end <= start:
            raise HTTPException(status_code=422, detail="La fin de phase doit être après son début.")
        previous = conn.execute(
            "SELECT fin_s FROM phases WHERE station_id = ? AND ordre = ?",
            (station_id, current["ordre"] - 1),
        ).fetchone()
        following = conn.execute(
            "SELECT debut_s FROM phases WHERE station_id = ? AND ordre = ?",
            (station_id, current["ordre"] + 1),
        ).fetchone()
        if previous and start < float(previous["fin_s"]):
            raise HTTPException(status_code=422, detail="Le début chevauche la phase précédente.")
        if following and end > float(following["debut_s"]):
            raise HTTPException(status_code=422, detail="La fin chevauche la phase suivante.")

        assignments = ", ".join(f"{field} = ?" for field in updates)
        conn.execute(
            f"UPDATE phases SET {assignments} WHERE id = ? AND station_id = ?",
            (*updates.values(), phase_id, station_id),
        )
        if "description" in updates:
            description = str(updates["description"] or "").strip()
            if description and not description.startswith(
                ("Activité détectée", "Arrêt détecté", "Phase fusionnée")
            ):
                conn.execute(
                    "INSERT OR IGNORE INTO project_operations (project_id, nom) VALUES (?, ?)",
                    (current["project_id"], description),
                )
        updated = conn.execute("SELECT * FROM phases WHERE id = ?", (phase_id,)).fetchone()
    return dict(updated)


@app.post("/api/stations/{station_id}/phases/{phase_id}/split", status_code=status.HTTP_201_CREATED)
def split_phase(station_id: int, phase_id: int, payload: PhaseSplit) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        phase = conn.execute(
            "SELECT * FROM phases WHERE id = ? AND station_id = ?",
            (phase_id, station_id),
        ).fetchone()
        if phase is None:
            raise HTTPException(status_code=404, detail="Phase introuvable")
        split_at = round(float(payload.temps_s), 1)
        if not float(phase["debut_s"]) + 0.1 <= split_at <= float(phase["fin_s"]) - 0.1:
            raise HTTPException(status_code=422, detail="La coupe doit se trouver à l'intérieur de la phase.")
        conn.execute(
            "UPDATE phases SET fin_s = ?, chrono_reel_s = NULL WHERE id = ?",
            (split_at, phase_id),
        )
        conn.execute(
            "UPDATE phases SET ordre = ordre + 1 WHERE station_id = ? AND ordre > ?",
            (station_id, phase["ordre"]),
        )
        conn.execute(
            """
            INSERT INTO phases (
                station_id, ordre, debut_s, fin_s, type_auto, description, categorie,
                commentaire, mouvement_moyen_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_id,
                phase["ordre"] + 1,
                split_at,
                phase["fin_s"],
                phase["type_auto"],
                phase["description"],
                phase["categorie"],
                phase["commentaire"],
                phase["mouvement_moyen_pct"],
            ),
        )
        phases = conn.execute(
            "SELECT * FROM phases WHERE station_id = ? ORDER BY ordre",
            (station_id,),
        ).fetchall()
    return [dict(row) for row in phases]


@app.post("/api/stations/{station_id}/phases/merge")
def merge_phases(station_id: int, payload: PhaseMerge) -> list[dict[str, Any]]:
    ensure_initialized()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM phases
            WHERE station_id = ? AND id IN (?, ?)
            ORDER BY ordre
            """,
            (station_id, payload.phase_ids[0], payload.phase_ids[1]),
        ).fetchall()
        if len(rows) != 2:
            raise HTTPException(status_code=404, detail="Les deux phases doivent appartenir à ce poste.")
        first, second = rows
        if int(second["ordre"]) != int(first["ordre"]) + 1:
            raise HTTPException(status_code=422, detail="Seules deux phases voisines peuvent être fusionnées.")
        conn.execute(
            """
            UPDATE phases
            SET fin_s = ?, mouvement_moyen_pct = ?, description = ?, categorie = 'Non classé',
                commentaire = NULL, chrono_reel_s = NULL
            WHERE id = ?
            """,
            (
                second["fin_s"],
                (
                    float(first["mouvement_moyen_pct"] or 0.0) * (float(first["fin_s"]) - float(first["debut_s"]))
                    + float(second["mouvement_moyen_pct"] or 0.0) * (float(second["fin_s"]) - float(second["debut_s"]))
                )
                / max(float(second["fin_s"]) - float(first["debut_s"]), 1e-9),
                "Phase fusionnée — à décrire",
                first["id"],
            ),
        )
        conn.execute("DELETE FROM phases WHERE id = ?", (second["id"],))
        conn.execute(
            "UPDATE phases SET ordre = ordre - 1 WHERE station_id = ? AND ordre > ?",
            (station_id, second["ordre"]),
        )
        phases = conn.execute(
            "SELECT * FROM phases WHERE station_id = ? ORDER BY ordre",
            (station_id,),
        ).fetchall()
    return [dict(row) for row in phases]


@app.get("/api/projects/{project_id}/summary")
def project_summary(project_id: int) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        project = conn.execute("SELECT id, nom, takt_s FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        stations = conn.execute(
            """
            SELECT
                s.id,
                s.nom,
                (
                    SELECT ea.rula_score
                    FROM ergonomic_assessments ea
                    WHERE ea.station_id = s.id AND ea.rula_score IS NOT NULL
                    ORDER BY ea.created_at DESC, ea.id DESC
                    LIMIT 1
                ) AS latest_rula_score,
                (
                    SELECT ea.reba_score
                    FROM ergonomic_assessments ea
                    WHERE ea.station_id = s.id AND ea.reba_score IS NOT NULL
                    ORDER BY ea.created_at DESC, ea.id DESC
                    LIMIT 1
                ) AS latest_reba_score
            FROM stations s
            WHERE s.project_id = ?
            ORDER BY s.id ASC
            """,
            (project_id,),
        ).fetchall()
        summary_by_station: list[dict[str, Any]] = []
        comparisons: list[dict[str, Any]] = []
        for station in stations:
            phases = conn.execute(
                """
                SELECT id, ordre, debut_s, fin_s, type_auto, description, categorie, chrono_reel_s
                FROM phases WHERE station_id = ? ORDER BY ordre ASC
                """,
                (station["id"],),
            ).fetchall()
            cycles = conn.execute(
                "SELECT id, debut_s, fin_s, source FROM cycles WHERE station_id = ? ORDER BY debut_s, id",
                (station["id"],),
            ).fetchall()
            data = {"VA": 0.0, "NVA nécessaire": 0.0, "Gaspillage": 0.0, "Non classé": 0.0}
            total_cycle = 0.0
            station_comparisons: list[dict[str, Any]] = []
            for row in phases:
                category = row["categorie"] or "Non classé"
                duration = float(row["fin_s"]) - float(row["debut_s"])
                if category in data:
                    data[category] += duration
                else:
                    data["Non classé"] += duration
                total_cycle += duration
                real_s = float(row["chrono_reel_s"]) if row["chrono_reel_s"] is not None else None
                error_pct = (
                    abs(duration - real_s) / real_s * 100.0
                    if real_s is not None and real_s > 0
                    else None
                )
                comparison = {
                    "phase_id": row["id"],
                    "ordre": row["ordre"],
                    "type_auto": row["type_auto"],
                    "description": row["description"] or "Étape non décrite",
                    "duree_estimee_s": round(duration, 2),
                    "chrono_reel_s": real_s,
                    "ecart_absolu_s": round(abs(duration - real_s), 2) if real_s is not None else None,
                    "erreur_absolue_pct": round(error_pct, 2) if error_pct is not None else None,
                }
                station_comparisons.append(comparison)
                if error_pct is not None:
                    comparisons.append(comparison)
            summary_by_station.append(
                {
                    "station_id": station["id"],
                    "station_nom": station["nom"],
                    "latest_rula_score": (
                        int(station["latest_rula_score"])
                        if station["latest_rula_score"] is not None
                        else None
                    ),
                    "latest_rula_level": (
                        _assessment_risk("RULA", int(station["latest_rula_score"]))
                        if station["latest_rula_score"] is not None
                        else None
                    ),
                    "latest_reba_score": (
                        int(station["latest_reba_score"])
                        if station["latest_reba_score"] is not None
                        else None
                    ),
                    "latest_reba_level": (
                        _assessment_risk("REBA", int(station["latest_reba_score"]))
                        if station["latest_reba_score"] is not None
                        else None
                    ),
                    "VA": round(data["VA"], 2),
                    "NVA nécessaire": round(data["NVA nécessaire"], 2),
                    "Gaspillage": round(data["Gaspillage"], 2),
                    "Non classé": round(data["Non classé"], 2),
                    "temps_observe_total": round(total_cycle, 2),
                    "temps_cycle": round(_reference_cycle_time(total_cycle, cycles)[0], 2),
                    "base_temps_cycle": _reference_cycle_time(total_cycle, cycles)[1],
                    "nombre_cycles": len(cycles),
                    "takt": float(project["takt_s"]),
                    "pct_va": round((data["VA"] / total_cycle) * 100.0 if total_cycle else 0.0, 2),
                    "ecart_takt": (
                        round(_reference_cycle_time(total_cycle, cycles)[0] - float(project["takt_s"]), 2)
                        if total_cycle
                        else 0.0
                    ),
                    "comparaison_chrono": station_comparisons,
                    "cycles": [
                        {
                            "id": int(cycle["id"]),
                            "debut_s": float(cycle["debut_s"]),
                            "fin_s": float(cycle["fin_s"]),
                            "duree_s": round(float(cycle["fin_s"]) - float(cycle["debut_s"]), 2),
                            "source": cycle["source"],
                        }
                        for cycle in cycles
                    ],
                    "statistiques_cycles": cycle_duration_statistics([dict(cycle) for cycle in cycles]),
                }
            )
    measured_errors = [
        comparison["erreur_absolue_pct"]
        for comparison in comparisons
        if comparison["erreur_absolue_pct"] is not None
    ]
    average_error = round(sum(measured_errors) / len(measured_errors), 2) if measured_errors else None
    return {
        "project": dict(project),
        "stations": summary_by_station,
        "comparaison_chrono": {
            "erreur_absolue_moyenne_pct": average_error,
            "phases_chronometrees": len(measured_errors),
            "phases": comparisons,
        },
    }


@app.get("/api/projects/{project_id}/export.xlsx")
def export_project(project_id: int) -> Response:
    ensure_initialized()
    with get_connection() as conn:
        project_row = conn.execute(
            "SELECT id, nom, takt_s FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project_row is None:
            raise HTTPException(status_code=404, detail="Projet introuvable")

        station_rows = conn.execute(
            "SELECT id, nom FROM stations WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        ).fetchall()
        stations: list[dict[str, Any]] = []
        for station_row in station_rows:
            phase_rows = conn.execute(
                """
                SELECT ordre, debut_s, fin_s, type_auto, description, categorie,
                       commentaire, chrono_reel_s, mouvement_moyen_pct
                FROM phases
                WHERE station_id = ?
                ORDER BY ordre ASC
                """,
                (station_row["id"],),
            ).fetchall()
            cycle_rows = conn.execute(
                "SELECT debut_s, fin_s, source FROM cycles WHERE station_id = ? ORDER BY debut_s, id",
                (station_row["id"],),
            ).fetchall()
            stations.append(
                {
                    "id": station_row["id"],
                    "nom": station_row["nom"],
                    "phases": [dict(row) for row in phase_rows],
                    "cycles": [dict(row) for row in cycle_rows],
                }
            )

    project = dict(project_row)
    target_path = EXPORT_ROOT / f"kaizen_studio_projet_{project_id}.xlsx"
    safe_project_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(project["nom"])).strip(" .")
    if not safe_project_name:
        safe_project_name = f"projet_{project_id}"
    download_filename = f"kaizen_studio_{safe_project_name}.xlsx"
    try:
        output_path, warning = export_project_workbook(project, stations, target_path)
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Échec de l'export Excel : {error}") from error

    headers = {}
    if warning:
        headers["X-Export-Warning"] = warning
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_filename,
        headers=headers,
    )


@app.get("/api/stations/{station_id}/video")
def station_video(station_id: int) -> FileResponse:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute(
            "SELECT id, nom, video_path FROM stations WHERE id = ?",
            (station_id,),
        ).fetchone()
        if station is None:
            raise HTTPException(status_code=404, detail="Poste introuvable")
        video_path = station["video_path"]
    managed_video = managed_file_path(video_path, VIDEO_ROOT)
    if managed_video is None or not managed_video.is_file():
        raise HTTPException(status_code=404, detail="Vidéo introuvable pour ce poste")
    video_path = str(managed_video)
    media_types = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo"}
    media_type = media_types.get(Path(video_path).suffix.lower(), "application/octet-stream")
    return FileResponse(video_path, media_type=media_type)


@app.get("/api/settings")
def get_settings() -> dict[str, str]:
    ensure_initialized()
    with get_connection() as conn:
        rows = conn.execute("SELECT cle, valeur FROM settings ORDER BY cle").fetchall()
    return {row["cle"]: row["valeur"] for row in rows}


@app.post("/api/settings")
def save_setting(payload: dict[str, str]) -> dict[str, str]:
    ensure_initialized()
    unknown_settings = set(payload) - _ALLOWED_SETTINGS
    if unknown_settings:
        raise HTTPException(
            status_code=422,
            detail=f"Réglage(s) non modifiable(s) : {', '.join(sorted(unknown_settings))}.",
        )
    if "purge_days" in payload:
        try:
            retention_days = int(payload["purge_days"])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="purge_days doit être un entier compris entre 1 et 3650.") from error
        if not 1 <= retention_days <= 3650:
            raise HTTPException(status_code=422, detail="purge_days doit être compris entre 1 et 3650 jours.")
    if "video_max_mb" in payload:
        try:
            max_video_mb = int(payload["video_max_mb"])
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail="video_max_mb doit être un entier positif.") from error
        if not 1 <= max_video_mb <= 20480:
            raise HTTPException(
                status_code=422,
                detail="video_max_mb doit être compris entre 1 et 20480 Mo.",
            )
    with get_connection() as conn:
        for key, value in payload.items():
            conn.execute("INSERT OR REPLACE INTO settings (cle, valeur) VALUES (?, ?)", (key, value))
    return payload


@app.post("/api/maintenance/purge")
def run_retention_purge() -> dict[str, int | str]:
    try:
        result = purge_expired_projects()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {"status": "completed", **result}


@app.get("/api/exports")
def list_exports() -> list[str]:
    ensure_initialized()
    return sorted(str(path.relative_to(EXPORT_ROOT)) for path in EXPORT_ROOT.glob("*") if path.is_file())


if __name__ == "__main__":
    import uvicorn

    server_host, certfile, keyfile = server_bind_configuration()
    uvicorn.run(
        "app.main:app",
        host=server_host,
        port=8000,
        reload=False,
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
