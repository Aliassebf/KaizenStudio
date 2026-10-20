# Kaizen Studio — Revue de code full stack et plan d'amélioration

*Revue du 20/10/2026 — dossier `Dev_Log/KaizenStudio-Projet-Complet`*

## 1. Synthèse

**Verdict : base saine, au-dessus de la moyenne d'un prototype interne**, avec 3 défauts à corriger
avant toute diffusion en mode réseau (pilote GENESIS) et 2 biais de mesure qui touchent directement
les chiffres présentés à la direction.

| Domaine | Appréciation |
|---|---|
| Sécurité | Bonne base (sessions hachées, anti-force brute, origine vérifiée, SameSite strict, admin initial en local uniquement). **1 faille critique potentielle** (chemin vidéo arbitraire). |
| Fiabilité des mesures | **2 biais** : angles de posture déformés par le format d'image ; « temps de cycle » = durée totale de la vidéo. Dérive de temps sur vidéos smartphone (VFR). |
| Robustesse serveur | Connexions SQLite non fermées, ré-initialisation de la base à chaque requête, fuite mémoire des tâches, import vidéo bloquant. |
| Intégrité des données | Ré-analyse qui efface sans prévenir le travail de l'analyste ; purge qui peut supprimer un projet actif ; opérations renommées qui « ressuscitent ». |
| Architecture | `main.py` 2 782 lignes et `app.js` 2 261 lignes : fonctionnels mais difficiles à faire évoluer. |
| Documentation / honnêteté | Excellente : ARCHITECTURE.md clair, limites assumées (estimations, pré-cotation, pas de reconnaissance de geste). |

### Points forts à conserver
- Mots de passe hachés, jetons de session stockés **hachés**, hash factice anti-timing, limitation des tentatives.
- Contrôle d'origine sur les requêtes mutantes + cookie `SameSite=strict` + `HttpOnly`.
- Suppression de fichiers restreinte aux dossiers gérés (`_managed_file_path`).
- Modèle d'apprentissage écrit de façon atomique avec empreinte SHA-256, séparation entraînement/validation **par vidéo**.
- Rendu DOM par `textContent` (pas d'injection HTML), aucun CDN, aucun appel externe par défaut.
- Avertissements métier systématiques (temps à chronométrer, cotation à confirmer).

---

## 2. Constats priorisés

Gravité : 🔴 critique · 🟠 majeur · 🟡 modéré · ⚪ mineur — Statut : ✅ code livré · 📝 patch documenté

| ID | Grav. | Fichier | Constat | Impact | Correctif | Statut |
|---|---|---|---|---|---|---|
| S1 | 🔴 | main.py `create_station` + `station_video` | `POST /api/projects/{id}/stations` insère `video_path` tel que fourni ; `GET /api/stations/{id}/video` sert ce chemin s'il existe (`os.path.exists`). **Confirmé** : `StationCreate.video_path` est un `Optional[str]` libre dans `models.py`. | En mode réseau, tout utilisateur authentifié peut télécharger n'importe quel fichier lisible par le serveur : base SQLite (hachés), vidéos d'autres comptes, documents du PC. | Refus de `video_path` à la création, diffusion/lecture uniquement sous `VIDEO_ROOT`. | ✅ `core/files.py` + 📝 P1 |
| S2 | 🟠 | main.py `save_setting` | Accepte n'importe quelle clé (`dict[str,str]`), dont `allow_outbound_network`. | La garantie « aucun appel externe » devient modifiable depuis l'IHM. | Liste blanche + schéma Pydantic. | 📝 P2, P12 |
| S3 | 🟡 | main.py middlewares | Ordre Starlette inversé : les 401/403/redirections n'ont pas `no-store`/`nosniff` ; pas de CSP. | Défense en profondeur incomplète (clickjacking, injection). | Réordonner + CSP `'self'` (compatible : aucun CDN). | 📝 P10 |
| S4 | ⚪ | main.py `get_station`… | Chemins absolus Windows renvoyés au navigateur (nom d'utilisateur, arborescence). | Divulgation d'information. | `has_video` booléen. | 📝 P1.d |
| M1 | 🔴 | posture.py | Angles calculés sur coordonnées MediaPipe **normalisées** (x/largeur, y/hauteur) → image « écrasée en carré ». En 1920×1080 : tronc à 20° mesuré ≈ 12° (paysage) ou ≈ 33° (portrait) ; angle réel de 45° → ≈ 29°. | Pré-cotations RULA/REBA biaisées de façon systématique. | Calcul en pixels (`compute_angles`). Recalculer les postures existantes. | ✅ + 📝 P13 |
| M2 | 🟠 | main.py `project_summary` | `temps_cycle` = somme de **toutes** les phases de la vidéo, comparée au takt. Le support GENESIS affiche « 336,6 s de cycle moyen estimé » pour un takt de 150 s avec « aucun cycle enregistré » : **si la vidéo couvre plus d'un cycle, l'écart au takt est surestimé**. | Décision direction sur un chiffre potentiellement faux. | Cycle de référence = médiane des cycles validés ; sinon libellé explicite « durée totale observée ». | 📝 P8 |
| M3 | 🟠 | motion.py, posture.py | Horodatage = `index / fps`. Les vidéos smartphone sont souvent à fréquence variable. | Dérive des bornes de phase sur les longues vidéos. | Horodatage réel `CAP_PROP_POS_MSEC` (repli `index/fps`). | ✅ |
| M4 | 🟡 | motion.py | Après absorption d'une micro-phase, deux phases voisines **de même type** subsistent (reproduit : `stop, activity, activity, stop`). | Phases « Activité » doublées, frise et Yamazumi faussés. | Recollage des voisines de même type. | ✅ testé |
| M5 | 🟡 | motion.py | 1re phase démarrant au 2e échantillon (trou en début de fenêtre) ; calcul d'hystérésis mort ; masque ROI recalculé à chaque image ; vidéo non libérée si exception. | Petites erreurs de durée, CPU, verrou fichier. | Corrigé. | ✅ |
| R1 | 🟠 | db.py | `with sqlite3.connect() as conn` **commit mais ne ferme pas** la connexion. Pas de WAL ni `busy_timeout`. | Fuite de descripteurs sous Windows ; « database is locked » quand l'analyse écrit pendant qu'un autre utilisateur travaille. | Connexion auto-fermante, WAL, `busy_timeout`. | ✅ testé |
| R2 | 🟠 | main.py / db.py | `ensure_initialized()` (CREATE TABLE, migrations, purge des sessions, reprise des opérations) appelé **à chaque requête**. | Écritures et verrous inutiles à chaque clic. | `init_db()` mémorisé par fichier + migrations versionnées (`PRAGMA user_version`). | ✅ testé |
| R3 | 🟠 | main.py | `analysis_jobs` ne se vide jamais et garde signaux + postures en RAM. | Croissance mémoire continue sur un serveur partagé. | `JobRegistry` avec TTL et libération après lecture. | ✅ testé + 📝 P3 |
| R4 | 🟠 | main.py `_store_station_video` | Fonction `async` qui écrit et ouvre OpenCV en **synchrone**. | Import d'une vidéo de 2 Go = serveur figé pour tous. | `asyncio.to_thread`. | 📝 P6 |
| R5 | 🟡 | main.py `_run_analysis` | Exception non journalisée (contrairement à la posture). | Diagnostic impossible a posteriori. | `logger.exception`. | 📝 P3 |
| R6 | 🟡 | main.py `start_station_analysis` | ROI/fenêtre écrites **avant** le contrôle « analyse déjà en cours ». | Paramètres modifiés pendant une analyse en cours. | Réserver la tâche avant l'écriture. | 📝 P5 |
| D1 | 🔴 | main.py analyse + resegment + app.js L1801 | `DELETE FROM phases` sans contrôle ; de plus `app.js` relance automatiquement la resegmentation au relâchement d'un curseur : **un simple réglage efface les phases décrites**. | Perte de travail de l'analyste. | 409 + confirmation (`?force=true`). | 📝 P4 + F2 |
| D2 | 🟠 | main.py purge | Purge sur la date de **création**. | Projet actif depuis > 90 j supprimé avec ses vidéos. | Colonne `derniere_activite_le` + mise à jour sur chaque modification. | ✅ migration + 📝 P7 |
| D3 | 🟡 | db.py | Reprise des descriptions → opérations exécutée à chaque requête. | Opération renommée qui réapparaît sous l'ancien nom. | Migration unique. | ✅ testé |
| D4 | 🟡 | main.py coupe/fusion | Chrono réel conservé sur la 1re moitié d'une coupe ; moyenne de mouvement non pondérée ; `categorie = NULL` à la fusion. | Comparaison chrono faussée. | Corrigé. | 📝 P9 |
| X1 | 🟠 | excel_export.py | Textes saisis (description, commentaire, nom de poste) écrits tels quels : une valeur commençant par `=` devient une formule active dans l'Excel diffusé. | Injection de formules. | Échappement `'`. | 📝 P14 |
| X2 | 🟡 | excel_export.py | « Temps de cycle » de la Synthèse Excel = somme de toutes les étapes (même biais que M2). | Chiffre faux dans l'export partagé. | Division par le nombre de cycles. | 📝 P8 |
| X3 | ⚪ | main.py / scoring.py | Deux jeux de libellés de risque RULA différents. | Incohérence IHM/synthèse. | Source unique. | 📝 P15 |
| D5 | ⚪ | main.py export | Fichier d'export à nom fixe. | Collision entre deux exports simultanés. | Nom unique + suppression après envoi. | 📝 P11 |
| F1 | 🟡 | app.js `apiRequest` | Pas de gestion 401 (session expirée), 422 Pydantic affichés « [object Object] », pas de délai. | Interface confuse après 8 h. | `apiRequest` robuste. | 📝 F1 |
| F2 | 🟡 | app.js polling | Une coupure réseau interrompt le suivi alors que l'analyse continue. | Faux échecs en mode réseau. | `pollJob` tolérant. | 📝 F3 |
| F3 | ⚪ | app.js surcouche | Squelette calé sur la boîte `<video>`, pas sur l'image affichée. | Décalage visuel si bandes noires. | `displayedVideoRect()`. | 📝 F4 |
| A1 | 🟡 | main.py / app.js | Fichiers monolithiques ; contrôle de propriété par **regex** dans un middleware : toute nouvelle route hors motif `/api/projects/{id}` ou `/api/stations/{id}` est **non protégée par défaut**. | Risque de régression de sécurité à chaque ajout de route. | Routers FastAPI + dépendances `Depends(owned_station)` (§3). | Feuille de route |

---

## 3. Architecture cible (refactorisation progressive, sans tout réécrire)

```
app/
  main.py                 # création de l'app, middlewares, montage des routers (< 150 lignes)
  core/
    files.py              # ✅ livré — chemins gérés
    security.py           # dépendances : current_user, require_admin, owned_project, owned_station
  jobs.py                 # ✅ livré — registre des tâches
  db.py                   # ✅ livré
  repositories/           # requêtes SQL par agrégat (stations.py, phases.py, cycles.py…)
  routers/
    auth.py  admin.py  projects.py  stations.py  analysis.py
    phases.py  operations.py  cycles.py  ergonomics.py  exports.py
  analysis/  ergonomics/  services/   # inchangés (déjà bien isolés)
```

Principe clé — remplacer la regex du middleware par une dépendance explicite :

```python
def owned_station(station_id: int, request: Request) -> sqlite3.Row:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT s.*, p.owner_user_id FROM stations s JOIN projects p ON p.id = s.project_id WHERE s.id = ?",
            (station_id,),
        ).fetchone()
    if row is None or int(row["owner_user_id"]) != int(request.state.user["id"]):
        raise HTTPException(status_code=404, detail="Poste introuvable.")
    return row

@router.get("/api/stations/{station_id}/phases")
def list_phases(station: sqlite3.Row = Depends(owned_station)): ...
```
Bénéfice : une route oubliée ne compile plus sans contrôle d'accès, et la station est chargée une seule fois.

Ordre conseillé : `exports` → `cycles` → `ergonomics` → `operations` → `phases` → `analysis` → `stations` →
`projects` → `auth/admin`. Un router par commit, suite de tests verte à chaque étape.

---

## 4. Qualité, outillage et livraison

| Sujet | Constat | Recommandation |
|---|---|---|
| Gestion de version | Code, exécutable (`KaizenStudio.exe`), 50+ wheels et présentations dans un même dossier OneDrive. | Dépôt Git sur la plateforme approuvée par l'IT ; `.gitignore` ✅ livré ; `dist/` et `wheelhouse/` publiés comme artefacts, pas versionnés. |
| Lint / typage | Aucun outil configuré. | `pyproject.toml` ✅ livré (ruff + mypy + pytest) ; `.pre-commit-config.yaml` ✅ livré. |
| Tests | Bonne couverture fonctionnelle annoncée (13 fichiers). | 14 tests de non-régression ✅ livrés (tous verts sur l'environnement de revue). Ajouter des tests API pour P1, P4, P7, P8. |
| Prototypes | `kaizen_video_study.py`, `_v2.py` (Azure OpenAI), `azure_vision.py`, `ollama.py` inactifs. | Déplacer dans `archive/` ou supprimer : moins de surface d'audit pour l'intake sécurité. |
| Dépendances | `mediapipe 0.10.21` utilise l'API historique `mp.solutions`. | Prévoir la migration vers MediaPipe Tasks (`PoseLandmarker`) lors d'une prochaine montée de version ; épingler les versions dans `requirements.txt`. |
| Exécutable | Diffusé à des collègues (demande d'accès reçue). | Versionner le nom (`KaizenStudio_0.2.0.exe`), publier une empreinte SHA-256, journal des changements. |
| Données personnelles | Vidéos d'opérateurs, base locale. | Faire valider l'usage (information des personnes filmées, durée de conservation, accès) par les interlocuteurs RGPD / RH avant le pilote. |

---

## 5. Contenu livré

| Fichier | Rôle |
|---|---|
| `app/db.py` | Remplace l'existant (API inchangée) : connexions fermées, WAL, init unique, migrations versionnées, index, `derniere_activite_le`, `touch_project()`. |
| `app/analysis/video.py` | Remplace l'existant (API inchangée) + `opened_video`, `read_video_metadata`, `frame_timestamp_s`. |
| `app/analysis/motion.py` | Remplace l'existant (API inchangée ; `segment_motion_signal` accepte `start_time` optionnel). |
| `app/analysis/posture.py` | Remplace l'existant (format de sortie inchangé) + `compute_angles`. |
| `app/jobs.py`, `app/core/files.py` | Nouveaux modules. |
| `patches/PATCH_main_py.md` | P0 à P13, blocs avant/après. |
| `patches/PATCH_app_js.md` | F1 à F5. |
| `tests/test_review_improvements.py` | 14 tests (base, fichiers, vidéo synthétique, segmentation, angles, tâches). |
| `pyproject.toml`, `.gitignore`, `.pre-commit-config.yaml` | Outillage. |

## 6. Procédure d'intégration (Windows, PowerShell)

```powershell
cd C:\Users\FOFANABA\...\KaizenStudio-Projet-Complet
git init; git add -A; git commit -m "Etat avant revue"           # point de retour
# 1) Copier les fichiers livrés (app\, tests\, pyproject.toml, .gitignore)
python -m pytest -q tests\test_review_improvements.py               # doit être vert
python -m pytest -q                                                 # suite complète
# 2) Appliquer patches\PATCH_main_py.md (P0 -> P13), relancer pytest après chaque Px
# 3) Appliquer patches\PATCH_app_js.md, puis :
node --check app\static\app.js
python -m app.launcher                                              # test manuel : import, analyse, ré-analyse (confirmation), posture, export
```

**Vérification préalable indispensable** : les connexions se ferment désormais en sortie de `with`.
Contrôler qu'aucun module ne réutilise une connexion après son bloc :
`Select-String -Path app\*.py,app\**\*.py -Pattern "get_connection\(\)" | Where-Object { $_.Line -notmatch "with get_connection\(\) as" }`
(aucun cas dans `main.py` ; `auth.py` non consulté). La purge des sessions expirées ne s'exécute plus
qu'au démarrage : vérifier que `get_session_user` contrôle bien `expires_at`.

**Tests existants susceptibles d'être ajustés** (comportements volontairement modifiés) :
`test_motion_analysis.py` (1re phase au début de fenêtre, voisines de même type recollées),
`test_posture_analysis.py` (valeurs d'angles corrigées), `test_api.py` (création de poste avec
`video_path` refusée, ré-analyse 409 sans `force`), `test_analysis_jobs.py` (registre de tâches).

## 7. Limites de cette revue

Fichiers lus intégralement : `ARCHITECTURE.md`, `db.py`, `motion.py`, `video.py`, `posture.py`,
`operation_learning.py`, `auth.py`, `config.py`, `models.py`, `scoring.py`, `cycle_analysis.py`,
`excel_export.py`, `app.js` (sauf lignes 830-1299). Lu en quasi-totalité : `main.py` (lignes 657-699 non vues). Non lus : `launcher.py`, `analysis/base.py`, pages HTML, `dashboard.js`, `summary.js`, `users.js`, tests existants. Les modules livrés
ont été testés avec des substituts de `config.py` / `base.py` reproduisant les attributs utilisés.
