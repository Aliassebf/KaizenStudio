"""Applique les correctifs de la revue Kaizen Studio sur le projet existant.

Usage (depuis la RACINE du projet, là où se trouve le dossier « app ») :

    py -3.11 KaizenStudio_Correctifs\\appliquer_correctifs.py            # applique
    py -3.11 KaizenStudio_Correctifs\\appliquer_correctifs.py --verifier # simulation, n'écrit rien

Le script :
1. sauvegarde chaque fichier touché dans _sauvegarde_correctifs_AAAAMMJJ_HHMMSS\\ ;
2. copie les modules réécrits (db, vidéo, mouvement, posture, fichiers gérés, tests) ;
3. modifie app/main.py, app/static/app.js, app/services/excel_export.py et
   tests/test_video_import.py par recherche/remplacement d'extraits exacts ;
4. s'arrête SANS RIEN ÉCRIRE si un extrait attendu est introuvable ou ambigu.
Il est rejouable : un correctif déjà présent est signalé « déjà appliqué ».
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
NEW_FILES = (
    "app/db.py",
    "app/core/__init__.py",
    "app/core/files.py",
    "app/analysis/video.py",
    "app/analysis/motion.py",
    "app/analysis/posture.py",
    "tests/test_review_improvements.py",
)


@dataclass
class Edit:
    code: str
    label: str
    old: str
    new: str
    marker: str  # texte présent seulement après application (idempotence)
    count: int = 1


@dataclass
class FilePatch:
    path: str
    edits: list[Edit] = field(default_factory=list)


def _pattern(old: str) -> re.Pattern[str]:
    """Regex tolérante : indentation, espaces de fin et lignes vides intercalées."""
    lines = [line.strip() for line in old.strip("\n").split("\n") if line.strip()]
    parts = [r"[ \t]*" + re.escape(line) + r"[ \t]*" for line in lines]
    body = r"(?:\n[ \t]*)*\n".join(parts)
    if len(lines) > 1:
        body = r"(?:(?<=\n)|^)" + body  # un extrait multiligne commence en début de ligne
    return re.compile(body)


def apply_edit(text: str, edit: Edit) -> tuple[str, str]:
    if edit.marker in text:
        return text, "déjà appliqué"
    matches = list(_pattern(edit.old).finditer(text))
    if len(matches) != edit.count:
        raise LookupError(f"{edit.code} {edit.label} : {len(matches)} occurrence(s) trouvée(s), {edit.count} attendue(s).")
    for match in reversed(matches):
        replacement = edit.new.strip("\n")
        original_indent = re.match(r"[ \t]*", match.group(0)).group(0)
        if replacement[:1] not in (" ", "\t"):
            replacement = original_indent + replacement
        text = text[: match.start()] + replacement + text[match.end():]
    return text, "appliqué"


# --------------------------------------------------------------------------- #
# app/main.py
# --------------------------------------------------------------------------- #
MAIN_HELPERS = '''
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
'''

MAIN = FilePatch(
    "app/main.py",
    [
        Edit(
            "M01", "imports",
            "from .db import get_connection, init_db",
            "from .db import get_connection, init_db, touch_project\nfrom .core.files import managed_file_path",
            "from .core.files import managed_file_path",
        ),
        Edit(
            "M02", "fonctions utilitaires",
            '@app.get("/")\ndef index(request: Request):',
            MAIN_HELPERS + '\n\n@app.get("/")\ndef index(request: Request):',
            "def _prune_finished_jobs_locked",
        ),
        Edit(
            "M03", "activité projet (middleware)",
            '''
            if row is None or int(row["owner_user_id"]) != int(user["id"]):
                return JSONResponse({"detail": "Tâche d'analyse introuvable."}, status_code=404)
    return await call_next(request)
''',
            '''
            if row is None or int(row["owner_user_id"]) != int(user["id"]):
                return JSONResponse({"detail": "Tâche d'analyse introuvable."}, status_code=404)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (project_match or station_match):
        _touch_project_activity(project_match, station_match)
    return await call_next(request)
''',
            "_touch_project_activity(project_match, station_match)\n",
        ),
        Edit(
            "M04", "purge sur la dernière activité",
            '''"SELECT id FROM projects WHERE datetime(cree_le) < datetime('now', ?)",''',
            '''"SELECT id FROM projects WHERE datetime(COALESCE(derniere_activite_le, cree_le)) < datetime('now', ?)",''',
            "COALESCE(derniere_activite_le, cree_le)",
        ),
        Edit(
            "M05", "création de poste : chemin vidéo et ROI validés",
            '''
                payload.nom,
                payload.video_path,
                payload.roi,
''',
            '''
                payload.nom.strip(),
                _legacy_video_path(payload.video_path),
                _validated_roi(payload.roi),
''',
            "_legacy_video_path(payload.video_path)",
        ),
        Edit(
            "M06", "import vidéo non bloquant",
            "destination.write(chunk)",
            "await asyncio.to_thread(destination.write, chunk)",
            "await asyncio.to_thread(destination.write, chunk)",
        ),
        Edit(
            "M07", "diffusion vidéo limitée au dossier géré",
            '''
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Vidéo introuvable pour ce poste")
''',
            '''
    managed_video = managed_file_path(video_path, VIDEO_ROOT)
    if managed_video is None or not managed_video.is_file():
        raise HTTPException(status_code=404, detail="Vidéo introuvable pour ce poste")
    video_path = str(managed_video)
''',
            "managed_video = managed_file_path(video_path, VIDEO_ROOT)",
        ),
        Edit(
            "M08", "journalisation des échecs d'analyse",
            '''
    except Exception as error:
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))
def _run_posture_analysis(
''',
            '''
    except Exception as error:
        logger.exception("Échec de l'analyse de mouvement du poste %s.", station["id"])
        with analysis_jobs_lock:
            analysis_jobs[job_id].update(status="failed", error=str(error))


def _run_posture_analysis(
''',
            "Échec de l'analyse de mouvement du poste",
        ),
        Edit(
            "M09", "mémoire des tâches bornée",
            '''
        job_id = uuid.uuid4().hex
        analysis_jobs[job_id] = {
''',
            '''
        _prune_finished_jobs_locked()
        job_id = uuid.uuid4().hex
        analysis_jobs[job_id] = {
''',
            "_prune_finished_jobs_locked()\n        job_id",
            count=2,
        ),
        Edit(
            "M10", "libération des résultats lus",
            '''
                detail="Tâche d'analyse introuvable (le serveur a peut-être redémarré).",
            )
        return dict(job)
''',
            '''
                detail="Tâche d'analyse introuvable (le serveur a peut-être redémarré).",
            )
        snapshot = dict(job)
        if job.get("status") not in {"queued", "running"}:
            for heavy_key in ("motion_samples", "posture_samples"):
                if heavy_key in job:
                    job[heavy_key] = []
        return snapshot
''',
            "for heavy_key in (\"motion_samples\", \"posture_samples\")",
        ),
        Edit(
            "M11", "analyse : protection des phases revues",
            '''
def start_station_analysis(station_id: int, payload: AnalysisRequest) -> dict[str, Any]:
    ensure_initialized()
''',
            '''
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
''',
            "def start_station_analysis(\n    station_id: int,",
        ),
        Edit(
            "M12", "resegmentation : protection des phases revues",
            '''
def resegment_station(station_id: int, payload: ResegmentRequest) -> list[dict[str, Any]]:
    ensure_initialized()
''',
            '''
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
''',
            "def resegment_station(\n    station_id: int,",
        ),
        Edit(
            "M13", "resegmentation depuis le début de fenêtre (requête)",
            "SELECT motion_signal_json, motion_threshold_pct, fenetre_fin",
            "SELECT motion_signal_json, motion_threshold_pct, fenetre_fin, fenetre_debut",
            "motion_threshold_pct, fenetre_fin, fenetre_debut",
        ),
        Edit(
            "M14", "resegmentation depuis le début de fenêtre (appel)",
            '''
            payload.duree_min_s,
            station["fenetre_fin"],
        )
''',
            '''
            payload.duree_min_s,
            station["fenetre_fin"],
            start_time=station["fenetre_debut"],
        )
''',
            'start_time=station["fenetre_debut"]',
        ),
        Edit(
            "M15", "création de phase : référentiel d'opérations (requête)",
            '''
def create_phase(station_id: int, payload: PhaseCreate) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id FROM stations WHERE id = ?", (station_id,)).fetchone()
''',
            '''
def create_phase(station_id: int, payload: PhaseCreate) -> dict[str, Any]:
    ensure_initialized()
    with get_connection() as conn:
        station = conn.execute("SELECT id, project_id FROM stations WHERE id = ?", (station_id,)).fetchone()
''',
            'station = conn.execute("SELECT id, project_id FROM stations WHERE id = ?", (station_id,)).fetchone()',
        ),
        Edit(
            "M16", "création de phase : référentiel d'opérations (alimentation)",
            '''
        created = conn.execute(
            "SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description, categorie, commentaire, chrono_reel_s, mouvement_moyen_pct "
            "FROM phases WHERE id = ?",
''',
            '''
        new_description = (payload.description or "").strip()
        if new_description and not new_description.startswith(_AUTO_PREFIXES):
            conn.execute(
                "INSERT OR IGNORE INTO project_operations (project_id, nom) VALUES (?, ?)",
                (station["project_id"], new_description),
            )
        created = conn.execute(
            "SELECT id, station_id, ordre, debut_s, fin_s, type_auto, description, categorie, commentaire, chrono_reel_s, mouvement_moyen_pct "
            "FROM phases WHERE id = ?",
''',
            "new_description = (payload.description or \"\").strip()",
        ),
        Edit(
            "M17", "coupe : le chrono réel n'est plus attribué à une seule moitié",
            '"UPDATE phases SET fin_s = ? WHERE id = ?",',
            '"UPDATE phases SET fin_s = ?, chrono_reel_s = NULL WHERE id = ?",',
            "SET fin_s = ?, chrono_reel_s = NULL WHERE id = ?",
        ),
        Edit(
            "M18", "fusion : catégorie cohérente",
            "SET fin_s = ?, mouvement_moyen_pct = ?, description = ?, categorie = NULL,",
            "SET fin_s = ?, mouvement_moyen_pct = ?, description = ?, categorie = 'Non classé',",
            "description = ?, categorie = 'Non classé',",
        ),
        Edit(
            "M19", "fusion : mouvement moyen pondéré par la durée",
            '''
                (
                    float(first["mouvement_moyen_pct"] or 0.0)
                    + float(second["mouvement_moyen_pct"] or 0.0)
                )
                / 2.0,
''',
            '''
                (
                    float(first["mouvement_moyen_pct"] or 0.0) * (float(first["fin_s"]) - float(first["debut_s"]))
                    + float(second["mouvement_moyen_pct"] or 0.0) * (float(second["fin_s"]) - float(second["debut_s"]))
                )
                / max(float(second["fin_s"]) - float(first["debut_s"]), 1e-9),
''',
            '/ max(float(second["fin_s"]) - float(first["debut_s"]), 1e-9),',
        ),
        Edit(
            "M20", "synthèse : temps de cycle de référence",
            '''
                    "temps_cycle": round(total_cycle, 2),
                    "takt": float(project["takt_s"]),
                    "pct_va": round((data["VA"] / total_cycle) * 100.0 if total_cycle else 0.0, 2),
                    "ecart_takt": round(total_cycle - float(project["takt_s"]), 2) if total_cycle else 0.0,
''',
            '''
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
''',
            '"temps_observe_total": round(total_cycle, 2),',
        ),
        Edit(
            "M21", "réglages : liste blanche",
            '''
def save_setting(payload: dict[str, str]) -> dict[str, str]:
    ensure_initialized()
''',
            '''
def save_setting(payload: dict[str, str]) -> dict[str, str]:
    ensure_initialized()
    unknown_settings = set(payload) - _ALLOWED_SETTINGS
    if unknown_settings:
        raise HTTPException(
            status_code=422,
            detail=f"Réglage(s) non modifiable(s) : {', '.join(sorted(unknown_settings))}.",
        )
''',
            "unknown_settings = set(payload) - _ALLOWED_SETTINGS",
        ),
        Edit(
            "M22", "anti-intégration en cadre (clickjacking)",
            '''
    response = await call_next(request)
    if not request.url.path.startswith("/static/"):
''',
            '''
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    if not request.url.path.startswith("/static/"):
''',
            'response.headers.setdefault("X-Frame-Options", "DENY")',
        ),
    ],
)

# --------------------------------------------------------------------------- #
# app/static/app.js
# --------------------------------------------------------------------------- #
APP_JS = FilePatch(
    "app/static/app.js",
    [
        Edit(
            "J01", "apiRequest robuste (session expirée, erreurs 422, réseau)",
            '''
async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Erreur serveur (${response.status}).`;
    try {
      message = (await response.json()).detail || message;
    } catch (error) {
      console.error('Réponse API non JSON', error);
    }
    throw new Error(message);
  }
  return response.json();
}
''',
            '''
async function apiRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { credentials: 'same-origin', ...options });
  } catch (error) {
    throw new Error('Serveur Kaizen Studio injoignable. Vérifiez qu’il est toujours lancé.');
  }
  if (response.status === 401) {
    window.location.assign('/login');
    const expired = new Error('Session expirée : reconnectez-vous.');
    expired.status = 401;
    throw expired;
  }
  if (!response.ok) {
    let message = `Erreur serveur (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).join(' · ');
    } catch (error) {
      console.error('Réponse API non JSON', error);
    }
    const failure = new Error(message);
    failure.status = response.status;
    throw failure;
  }
  if (response.status === 204) return null;
  return response.json();
}
''',
            "failure.status = response.status;",
        ),
        Edit(
            "J02", "aide : détection des phases déjà revues",
            "const categoryOptions = ['Non classé', 'VA', 'NVA nécessaire', 'Gaspillage'];",
            '''
const categoryOptions = ['Non classé', 'VA', 'NVA nécessaire', 'Gaspillage'];
function phasesHaveReview() {
  return state.phases.some((phase) => phase.chrono_reel_s != null
    || String(phase.commentaire || '').trim() !== ''
    || (phase.categorie && phase.categorie !== 'Non classé')
    || (String(phase.description || '').trim() !== ''
      && !/^(Activité détectée|Arrêt détecté|Phase fusionnée)/.test(String(phase.description))));
}
function reviewedPhasesQuery() {
  if (!phasesHaveReview()) return '';
  const confirmed = window.confirm(
    'Des phases ont déjà été décrites, classées, commentées ou chronométrées.\\n'
    + 'Relancer le calcul les remplacera. Continuer ?',
  );
  return confirmed ? '?force=true' : null;
}
''',
            "function reviewedPhasesQuery()",
        ),
        Edit(
            "J03", "analyse : confirmation avant de remplacer les phases",
            '''
  state.busy = true;
  analyzeButton.disabled = true;
  analysisProgress.value = 0;
''',
            '''
  const forceQuery = reviewedPhasesQuery();
  if (forceQuery === null) {
    showAnalysisStatus('Analyse annulée : les phases existantes sont conservées.');
    return;
  }
  state.busy = true;
  analyzeButton.disabled = true;
  analysisProgress.value = 0;
''',
            "const forceQuery = reviewedPhasesQuery();\n  if (forceQuery === null) {\n    showAnalysisStatus('Analyse annulée",
        ),
        Edit(
            "J04", "analyse : paramètre de confirmation",
            "const job = await apiRequest(`/api/stations/${stationId}/analysis`, {",
            "const job = await apiRequest(`/api/stations/${stationId}/analysis${forceQuery}`, {",
            "/analysis${forceQuery}`",
        ),
        Edit(
            "J05", "resegmentation : confirmation",
            '''
async function resegmentPhases() {
  if (state.busy) return;
''',
            '''
async function resegmentPhases() {
  if (state.busy) return;
  const forceQuery = reviewedPhasesQuery();
  if (forceQuery === null) return;
''',
            "async function resegmentPhases() {\n  if (state.busy) return;\n  const forceQuery",
        ),
        Edit(
            "J06", "resegmentation : paramètre de confirmation",
            "state.phases = await apiRequest(`/api/stations/${stationId}/resegment`, {",
            "state.phases = await apiRequest(`/api/stations/${stationId}/resegment${forceQuery}`, {",
            "/resegment${forceQuery}`",
        ),
        Edit(
            "J07", "curseurs : ne plus effacer automatiquement les phases revues",
            '''
function scheduleAnalysisAfterSettingChange() {
  if (!state.station?.video_path) return;
  window.clearTimeout(analysisDebounce);
''',
            '''
function scheduleAnalysisAfterSettingChange() {
  if (!state.station?.video_path) return;
  if (phasesHaveReview()) {
    showAnalysisStatus('Réglages enregistrés. Les phases déjà revues sont conservées : cliquez sur « Analyser le mouvement » pour recalculer.');
    return;
  }
  window.clearTimeout(analysisDebounce);
''',
            "if (phasesHaveReview()) {\n    showAnalysisStatus('Réglages enregistrés.",
        ),
        Edit(
            "J08", "sauvegarde ergonomie : écouteurs mal placés (dans « Renommer »)",
            '''
      assessmentForm.addEventListener('input', () => scheduleConfigurationSave('ergonomics'));
      assessmentForm.addEventListener('change', () => scheduleConfigurationSave('ergonomics'));
      const cancel = document.createElement('button');
''',
            '''
      const cancel = document.createElement('button');
''',
            "assessmentForm.addEventListener('change', () => scheduleConfigurationSave('ergonomics'));\nprefill",
        ),
        Edit(
            "J09", "sauvegarde ergonomie : écouteurs enregistrés une seule fois",
            "assessmentForm.addEventListener('submit', saveErgonomicAssessment);",
            '''
assessmentForm.addEventListener('submit', saveErgonomicAssessment);
assessmentForm.addEventListener('input', () => scheduleConfigurationSave('ergonomics'));
assessmentForm.addEventListener('change', () => scheduleConfigurationSave('ergonomics'));
''',
            "assessmentForm.addEventListener('change', () => scheduleConfigurationSave('ergonomics'));\nprefill",
        ),
    ],
)

# --------------------------------------------------------------------------- #
# app/services/excel_export.py
# --------------------------------------------------------------------------- #
EXCEL = FilePatch(
    "app/services/excel_export.py",
    [
        Edit(
            "X01", "fonction d'échappement des formules",
            'FONT_NAME = "Arial"',
            '''
FONT_NAME = "Arial"


def _safe_text(value: Any) -> Any:
    """Empêche qu'un texte saisi commençant par « = » soit écrit comme une formule Excel."""
    if isinstance(value, str) and value.lstrip().startswith("="):
        return "'" + value
    return value
''',
            "def _safe_text(value: Any) -> Any:",
        ),
        Edit(
            "X02", "étapes : nom de poste",
            '''
                    station["nom"],
                    phase["ordre"],
''',
            '''
                    _safe_text(station["nom"]),
                    phase["ordre"],
''',
            '_safe_text(station["nom"]),\n                    phase["ordre"],',
        ),
        Edit(
            "X03", "étapes : description",
            'phase.get("description") or "",',
            '_safe_text(phase.get("description") or ""),',
            '_safe_text(phase.get("description") or ""),',
        ),
        Edit(
            "X04", "étapes : commentaire",
            'phase.get("commentaire") or "",',
            '_safe_text(phase.get("commentaire") or ""),',
            '_safe_text(phase.get("commentaire") or ""),',
        ),
        Edit(
            "X05", "synthèse : nom de poste",
            'summary_sheet.cell(row=summary_row, column=1, value=station["nom"])',
            'summary_sheet.cell(row=summary_row, column=1, value=_safe_text(station["nom"]))',
            'value=_safe_text(station["nom"]))',
        ),
        Edit(
            "X06", "cycles : nom de poste",
            '''
                    station["nom"],
                    cycle_index,
''',
            '''
                    _safe_text(station["nom"]),
                    cycle_index,
''',
            '_safe_text(station["nom"]),\n                    cycle_index,',
        ),
    ],
)

# --------------------------------------------------------------------------- #
# tests/test_video_import.py (purge : la date d'activité compte désormais)
# --------------------------------------------------------------------------- #
TEST_IMPORT = FilePatch(
    "tests/test_video_import.py",
    [
        Edit(
            "T01", "purge : projet inactif depuis 2 jours",
            '''"UPDATE projects SET cree_le = datetime('now', '-2 days') WHERE id = ?",''',
            '''"UPDATE projects SET cree_le = datetime('now', '-2 days'), "
            "derniere_activite_le = datetime('now', '-2 days') WHERE id = ?",''',
            "derniere_activite_le = datetime('now', '-2 days') WHERE id = ?",
        ),
    ],
)

PATCHES = (MAIN, APP_JS, EXCEL, TEST_IMPORT)


def _read(path: Path) -> tuple[str, str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline, bom


def _write(path: Path, text: str, newline: str, bom: bool) -> None:
    data = text.replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--projet", default=".", help="Racine du projet (contient app/main.py). Défaut : dossier courant.")
    parser.add_argument("--verifier", action="store_true", help="Simulation : vérifie sans rien écrire.")
    args = parser.parse_args()
    root = Path(args.projet).resolve()
    if not (root / "app" / "main.py").is_file():
        print(f"ERREUR : {root} ne contient pas app\\main.py. Lancez le script depuis la racine du projet.")
        return 2

    results: list[tuple[str, str]] = []
    new_texts: dict[Path, tuple[str, str, bool]] = {}
    failures: list[str] = []
    for patch in PATCHES:
        target = root / patch.path
        if not target.is_file():
            failures.append(f"{patch.path} : fichier introuvable.")
            continue
        text, newline, bom = _read(target)
        original = text
        for edit in patch.edits:
            try:
                text, status = apply_edit(text, edit)
                results.append((f"{edit.code} {edit.label}", status))
            except LookupError as error:
                failures.append(str(error))
        if text != original:
            new_texts[target] = (text, newline, bom)

    for code_label, status in results:
        print(f"  [{status:^14}] {code_label}")
    if failures:
        print("\nÉCHEC : aucun fichier n'a été modifié. Détails :")
        for failure in failures:
            print(f"  - {failure}")
        print("Le fichier a probablement été modifié depuis la revue : envoyez ce message pour adaptation.")
        return 1

    if args.verifier:
        print("\nSimulation réussie : tous les correctifs sont applicables. Relancez sans --verifier.")
        return 0

    backup = root / f"_sauvegarde_correctifs_{datetime.now():%Y%m%d_%H%M%S}"
    to_backup = list(new_texts) + [root / relative for relative in NEW_FILES]
    for path in to_backup:
        if path.is_file():
            destination = backup / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for relative in NEW_FILES:
        source = KIT_DIR / "fichiers" / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"  [  copié       ] {relative}")
    for path, (text, newline, bom) in new_texts.items():
        _write(path, text, newline, bom)
        print(f"  [  modifié     ] {path.relative_to(root)}")
    print(f"\nSauvegarde : {backup}")
    print("Étapes suivantes :")
    print("  py -3.11 -m pytest -q")
    print("  node --check app\\static\\app.js   (si Node.js est installé)")
    print("  py -3.11 -m app.launcher           (test manuel)")
    print("  .\\build_windows_exe.bat            (nouvel exécutable)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
