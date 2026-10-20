# Correctifs à appliquer dans `app/main.py`

Chaque bloc indique **où**, **avant** et **après**. Les numéros (P1…P12) renvoient au rapport.
Appliquer dans l'ordre, puis lancer `python -m pytest -q`.

---

## P0 — Imports (en tête de fichier)

**Ajouter** après `from .db import get_connection, init_db` :

```python
from .db import touch_project
from .core.files import managed_file_path, require_managed_video
from .jobs import jobs
```

**Remplacer** la fonction `_managed_file_path` (≈ L193) par un alias, pour ne rien casser :

```python
_managed_file_path = managed_file_path
```

> `ensure_initialized()` peut rester partout : avec le nouveau `db.py`, `init_db()` ne fait plus
> rien après le premier appel. Ce n'est plus un coût par requête.

---

## P1 — CRITIQUE : lecture arbitraire de fichiers via `video_path`

### P1.a `create_station` (POST `/api/projects/{project_id}/stations`, ≈ L1327)

**Avant**
```python
        cursor = conn.execute(
            """
            INSERT INTO stations (project_id, nom, video_path, roi, fenetre_debut, fenetre_fin)
```
**Après** (insérer juste avant le `cursor = ...`)
```python
        if payload.video_path:
            raise HTTPException(
                status_code=422,
                detail="Le chemin vidéo ne peut pas être fourni : importez la vidéo via /stations/import.",
            )
        if payload.roi:
            try:
                parse_roi(payload.roi)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
```

### P1.b `station_video` (GET `/api/stations/{id}/video`, ≈ L2715)

**Avant**
```python
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Vidéo introuvable pour ce poste")
    media_types = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo"}
    media_type = media_types.get(Path(video_path).suffix.lower(), "application/octet-stream")
    return FileResponse(video_path, media_type=media_type)
```
**Après**
```python
    safe_path = require_managed_video(video_path, VIDEO_ROOT)
    media_types = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo"}
    media_type = media_types.get(safe_path.suffix.lower(), "application/octet-stream")
    return FileResponse(safe_path, media_type=media_type)
```

### P1.c Même garde partout où une vidéo est OUVERTE

Dans `station_video_frame`, `start_posture_analysis`, `start_station_analysis`,
`suggest_station_operations` : remplacer

```python
    if not video_path or not Path(video_path).is_file():
```
par
```python
    video_path = str(require_managed_video(video_path, VIDEO_ROOT))
```
(adapter le nom de variable : `station["video_path"]` dans les deux fonctions d'analyse).

### P1.d Ne plus exposer le chemin absolu au navigateur

Dans `get_station`, `get_project`, `list_stations`, `_store_station_video` : après `result = dict(...)`,
ajouter `result["has_video"] = bool(result.pop("video_path", None))`.
`app.js` lit `state.station.video_path` / `payload.video_path` à 5 endroits (≈ L1558, L1613, L1802,
L2109) : les remplacer par `has_video`. Vérifier aussi `dashboard.js`. Supprimer `video_path` de
`StationCreate` et `StationOut` dans `models.py` (confirmé : champ libre `Optional[str]`).

---

## P2 — `POST /api/settings` : liste blanche des clés

**Avant**
```python
@app.post("/api/settings")
def save_setting(payload: dict[str, str]) -> dict[str, str]:
    ensure_initialized()
```
**Après**
```python
ALLOWED_SETTINGS = {"purge_days", "video_max_mb"}


@app.post("/api/settings")
def save_setting(payload: dict[str, str]) -> dict[str, str]:
    ensure_initialized()
    unknown = set(payload) - ALLOWED_SETTINGS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Réglage(s) non modifiable(s) : {', '.join(sorted(unknown))}.")
```
> `allow_outbound_network` ne doit pas être modifiable depuis l'interface : sinon un compte admin
> réseau peut désactiver la garantie « aucun appel externe ».

---

## P3 — Registre de tâches (`app/jobs.py`) : fuite mémoire + logs

1. Supprimer `analysis_jobs`, `analysis_jobs_lock` (L79-80).
2. Remplacements mécaniques :

| Ancien code | Nouveau code |
|---|---|
| bloc `with analysis_jobs_lock: if any(... job["station_id"] == station_id ...): raise 409 ... analysis_jobs[job_id] = {...}` | `try: job_id = jobs.create(station_id, "motion", phase_count=None, motion_samples=[], threshold_pct=None)`<br>`except RuntimeError as error: raise HTTPException(409, str(error)) from error` |
| idem posture | `jobs.create(station_id, "posture", sample_count=None, posture_samples=[])` |
| `analysis_jobs[job_id]["status"] = "running"` | `jobs.update(job_id, status="running")` |
| `update_progress` (corps) | `jobs.set_progress(job_id, value)` |
| `update_signal` (corps) | `jobs.update(job_id, motion_samples=samples, threshold_pct=threshold_pct)` |
| lecture `motion_samples`/`threshold_pct` après analyse | `job = jobs.get(job_id); motion_samples, threshold_pct = job["motion_samples"], job["threshold_pct"]` |
| `analysis_jobs[job_id].update(status=...)` | `jobs.update(job_id, status=...)` |
| tests « analyse en cours » (purge, delete_project, delete_station) | `jobs.has_active(station_id)` / `jobs.has_active(station_ids)` / `jobs.active_station_ids()` |

3. `get_analysis_job` :
```python
@app.get("/api/jobs/{job_id}")
def get_analysis_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id, release_heavy=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Tâche d'analyse introuvable (le serveur a peut-être redémarré).")
    return job
```
4. Middleware (contrôle de propriété des jobs, ≈ L173) :
```python
    job_match = re.match(r"^/api/jobs/([a-f0-9]+)$", path)
    if job_match:
        job_station = jobs.station_of(job_match.group(1))
        if job_station is not None:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT p.owner_user_id FROM stations s JOIN projects p ON p.id = s.project_id WHERE s.id = ?",
                    (job_station,),
                ).fetchone()
            if row is None or int(row["owner_user_id"]) != int(user["id"]):
                return JSONResponse({"detail": "Tâche d'analyse introuvable."}, status_code=404)
```
5. `_run_analysis` : dans `except Exception as error:` ajouter
   `logger.exception("Échec de l'analyse de mouvement du poste %s.", station["id"])`
   (aujourd'hui l'erreur disparaît des journaux, seule l'IHM la voit).

---

## P4 — Ne plus écraser silencieusement le travail de l'analyste

`_run_analysis` et `resegment_station` font `DELETE FROM phases` : descriptions, catégories,
commentaires et chronos réels sont perdus sans avertissement.

**Ajouter** cette fonction (près de `_assessment_risk`) :
```python
_AUTO_PREFIXES = ("Activité détectée", "Arrêt détecté", "Phase fusionnée")


def _station_has_reviewed_phases(conn, station_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM phases
        WHERE station_id = ?
          AND (chrono_reel_s IS NOT NULL
               OR COALESCE(TRIM(commentaire), '') <> ''
               OR COALESCE(categorie, 'Non classé') <> 'Non classé'
               OR (description IS NOT NULL
                   AND description NOT LIKE 'Activité détectée%'
                   AND description NOT LIKE 'Arrêt détecté%'
                   AND description NOT LIKE 'Phase fusionnée%'))
        LIMIT 1
        """,
        (station_id,),
    ).fetchone()
    return row is not None
```
**Dans** `start_station_analysis` et `resegment_station`, ajouter le paramètre
`force: bool = Query(default=False)` et, avant tout `UPDATE`/`DELETE` :
```python
    with get_connection() as conn:
        if not force and _station_has_reviewed_phases(conn, station_id):
            raise HTTPException(
                status_code=409,
                detail="Des phases ont déjà été décrites, classées ou chronométrées. "
                "Relancer l'analyse les remplacera : confirmez pour continuer.",
            )
```
Côté navigateur : voir `PATCH_app_js.md` (confirmation puis renvoi avec `?force=true`).

---

## P5 — Course critique dans `start_station_analysis`

La ROI et la fenêtre sont écrites en base **avant** le contrôle « analyse déjà en cours ».
Déplacer le bloc `jobs.create(...)` (P3) **avant** le `UPDATE stations SET roi = ...` ;
en cas d'erreur sur l'`UPDATE`, appeler `jobs.update(job_id, status="failed", error=...)`.

---

## P6 — Import vidéo : ne plus bloquer le serveur

`_store_station_video` est `async` mais écrit sur disque et ouvre OpenCV de façon **synchrone** :
pendant l'import d'une vidéo de 2 Go, toutes les autres requêtes (tous les utilisateurs en mode
réseau) sont gelées.

**Avant**
```python
                destination.write(chunk)
```
**Après**
```python
                await asyncio.to_thread(destination.write, chunk)
```
**Avant**
```python
        capture = open_video_capture(temporary_path)
        if not capture.isOpened():
            capture.release()
            raise HTTPException(status_code=422, detail="OpenCV ne peut pas lire cette vidéo.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        capture.release()
```
**Après**
```python
        def _probe(path: Path) -> tuple[float, float, bool]:
            capture = open_video_capture(path)
            try:
                if not capture.isOpened():
                    return 0.0, 0.0, False
                return float(capture.get(cv2.CAP_PROP_FPS) or 0), float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0), True
            finally:
                capture.release()

        fps, frame_count, readable = await asyncio.to_thread(_probe, temporary_path)
        if not readable:
            raise HTTPException(status_code=422, detail="OpenCV ne peut pas lire cette vidéo.")
```
Ajouter aussi, en tête de `_store_station_video` : `nom = nom.strip()` puis
`if not nom: raise HTTPException(422, "Le nom du poste est obligatoire.")`
(aujourd'hui un nom composé d'espaces passe `min_length=1`).

---

## P7 — Purge : ne plus supprimer un projet ACTIF

`purge_expired_projects` supprime sur `cree_le` (date de **création**) : un projet créé il y a
91 jours et modifié hier est effacé avec ses vidéos.

**Avant**
```python
            "SELECT id FROM projects WHERE datetime(cree_le) < datetime('now', ?)",
```
**Après**
```python
            "SELECT id FROM projects WHERE datetime(COALESCE(derniere_activite_le, cree_le)) < datetime('now', ?)",
```
Et dans le middleware `require_local_account`, juste avant le `return await call_next(request)` final :
```python
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (project_match or station_match):
        project_id = None
        with get_connection() as conn:
            if project_match:
                project_id = int(project_match.group(1))
            else:
                row = conn.execute("SELECT project_id FROM stations WHERE id = ?", (int(station_match.group(1)),)).fetchone()
                project_id = int(row["project_id"]) if row else None
            if project_id is not None:
                touch_project(conn, project_id)
```

---

## P8 — Synthèse : « temps de cycle » faux dès que la vidéo contient plusieurs cycles

`project_summary` additionne **toutes** les phases de la vidéo et compare ce total au takt.
Si la vidéo couvre 2 cycles, le « cycle » affiché est doublé et l'écart au takt devient
artificiel.

**Remplacer** le calcul `"temps_cycle"`, `"pct_va"`, `"ecart_takt"` par :
```python
            cycle_stats = cycle_duration_statistics([dict(cycle) for cycle in cycles])
            cycle_count = len(cycles)
            observed_total = total_cycle
            if cycle_count:
                reference_cycle = float(cycle_stats["mediane_s"])
                basis = "cycles validés"
            else:
                reference_cycle = observed_total
                basis = "durée totale observée (aucun cycle validé)"
```
puis dans le dictionnaire :
```python
                    "temps_observe_total": round(observed_total, 2),
                    "temps_cycle": round(reference_cycle, 2),
                    "base_temps_cycle": basis,
                    "nombre_cycles": cycle_count,
                    "pct_va": round(data["VA"] / observed_total * 100.0, 2) if observed_total else 0.0,
                    "ecart_takt": round(reference_cycle - float(project["takt_s"]), 2) if reference_cycle else 0.0,
                    "statistiques_cycles": cycle_stats,
```
> Clé `mediane_s` vérifiée dans `cycle_analysis.py`. Afficher `base_temps_cycle` dans `summary.js`.
> ⚠️ Même biais dans l'Excel : `excel_export.py`, feuille Synthèse, colonne « Temps de cycle »
> = `SUM(B:E)` de toutes les étapes. Ajouter une colonne « Nb cycles » et calculer
> `Temps de cycle = SUM(B:E) / MAX(1; Nb cycles)`, ou renommer en « Temps observé total ».

---

## P14 — Excel : injection de formules (`excel_export.py`)

openpyxl écrit toute chaîne commençant par `=` comme une **formule**. Une description de phase
ou un commentaire saisi « =HYPERLINK(...) » devient une formule active dans le classeur diffusé.

Dans `build_project_workbook`, ajouter :
```python
def _safe_text(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
```
et l'appliquer à `station["nom"]`, `description`, `categorie`, `commentaire` (feuille Étapes),
`station["nom"]` (Synthèse et tableau des cycles), `project['nom']` (titre A1).

---

## P15 — Cohérence des libellés RULA

`main._assessment_risk("RULA", 5|6)` renvoie « Action à court terme » alors que
`scoring.RULA_LEVELS` renvoie « À investiguer et changer bientôt » ; 7 → « Action immédiate » vs
« Changement immédiat ». Supprimer `_assessment_risk` et réutiliser
`scoring._level(score, RULA_LEVELS | REBA_LEVELS)` pour qu'une même note ait un seul libellé.

---

## P9 — Coupe / fusion de phases

* `split_phase` : le chrono réel de la phase d'origine reste sur la 1re moitié → fausse
  comparaison. Ajouter `chrono_reel_s = NULL` dans `UPDATE phases SET fin_s = ?` .
* `merge_phases` : moyenne de mouvement **pondérée par la durée** :
```python
        d1 = float(first["fin_s"]) - float(first["debut_s"])
        d2 = float(second["fin_s"]) - float(second["debut_s"])
        weighted = ((float(first["mouvement_moyen_pct"] or 0) * d1) + (float(second["mouvement_moyen_pct"] or 0) * d2)) / max(d1 + d2, 1e-9)
```
  et `categorie = 'Non classé'` au lieu de `NULL` (cohérent avec l'analyse).
* `resegment_station` : passer `start_time=station["fenetre_debut"]` à `segment_motion_signal`
  (ajouter `fenetre_debut` au `SELECT`).

---

## P10 — En-têtes de sécurité et ordre des middlewares

Starlette exécute **en premier le dernier middleware déclaré**. Les réponses 401/403/redirect
de `require_local_account` ne reçoivent donc pas `no-store`/`nosniff`. Déclarer
`protect_private_responses` **après** `require_local_account` et compléter :

```python
@app.middleware("http")
async def protect_private_responses(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
    return response
```
> Si une page utilise des styles/JS **inline**, la CSP les bloquera : vérifier la console du
> navigateur et déplacer ces fragments dans `styles.css` / les `.js`.

---

## P11 — Export Excel sans collision

Deux exports simultanés du même projet écrivent le même fichier
`kaizen_studio_projet_{id}.xlsx`. Utiliser un nom unique puis le supprimer après envoi :

```python
from starlette.background import BackgroundTask
...
    target_path = EXPORT_ROOT / f"kaizen_studio_projet_{project_id}_{uuid.uuid4().hex[:8]}.xlsx"
    ...
    return FileResponse(output_path, ..., background=BackgroundTask(_remove_managed_file, str(output_path), EXPORT_ROOT))
```

---

## P12 — Schémas Pydantic au lieu de `dict`

`set_local_account_active(payload: dict[str, bool])` et `save_setting(payload: dict[str, str])`
contournent la validation. Ajouter dans `models.py` :
```python
class AccountActiveUpdate(BaseModel):
    is_active: bool

class SettingsUpdate(BaseModel):
    purge_days: int | None = Field(default=None, ge=1, le=3650)
    video_max_mb: int | None = Field(default=None, ge=1, le=20480)
```
---

## P13 — Recalcul des postures existantes

Les `posture_signal_json` déjà enregistrés ont été calculés **avec la distorsion d'aspect**
(cf. `posture.py`). Après déploiement : relancer « Suivi de posture » sur les postes concernés
avant toute nouvelle pré-cotation. Les cotations RULA/REBA **confirmées** restent en base telles
quelles : les revoir si elles s'appuyaient sur les angles calculés.
