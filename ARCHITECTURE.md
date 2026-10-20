# Architecture de Kaizen Studio

Ce document est le point d'entree technique du projet. Il s'adresse aux developpeurs, aux methodes
et aux agents IA qui doivent comprendre le code avant de le modifier. Pour l'installation utilisateur,
consulter aussi [README.md](README.md).

## 1. Ce que fait l'application

Kaizen Studio est une application web locale d'etude de temps et de mouvements. Un utilisateur importe
une video, l'analyse, verifie et decrit les phases, annote des operations, delimite des cycles et peut
realiser une pre-cotation ergonomique.

Le mode d'analyse temporelle `motion` mesure la presence de mouvement dans l'image. Il ne reconnait
ni le geste, ni l'operation, ni la personne. Les durees automatiques sont des **estimations a valider
par chronometrage**. La pre-cotation ergonomique est un outil d'aide et doit etre verifiee par une
personne competente.

Le produit utilise de la vision par ordinateur locale (OpenCV et MediaPipe), mais ne fait pas appel a
un assistant conversationnel ni a un service d'IA distant dans le parcours par defaut. Les adaptateurs
`azure_vision` et `ollama` sont des moteurs inactifs, pas des integrations prêtes a l'emploi.

## 2. Vue d'ensemble

```text
Utilisateur
    |
    v
Navigateur local (HTML, CSS, JavaScript, sans CDN)
    |  HTTP/JSON, video et images locales
    v
FastAPI / Uvicorn - app/main.py
    |                         |
    | SQL                     | tache de fond (ThreadPoolExecutor, 1 worker)
    v                         v
SQLite                    OpenCV / MediaPipe / moteur motion
    |                         |
    +---- resultats persistants + progression en memoire
    |
    +---- videos, exports Excel et modeles locaux dans DATA_DIR
```

Le navigateur et le serveur sont servis par la meme application. En configuration par defaut, le
serveur ecoute sur `127.0.0.1:8000`. Les ressources de l'interface sont dans `app/static`; aucune
bibliotheque front-end n'est chargee depuis un CDN.

## 3. Ou se trouve quoi ?

| Chemin | Responsabilite |
| --- | --- |
| `app/main.py` | Application FastAPI, routes HTTP, orchestration des analyses, acces aux donnees, authentification des routes et exports. C'est le point d'entree serveur ; garder les calculs specialises dans leurs modules. |
| `app/models.py` | Schemas Pydantic pour valider les corps de requete et les limites des API. |
| `app/db.py` | Connexion SQLite, creation des tables et migrations de compatibilite au demarrage. |
| `app/config.py` | Repertoires de donnees, chemins locaux et validation de l'adresse d'ecoute/TLS. |
| `app/auth.py` | Hachage des mots de passe, sessions, expiration et limitation des tentatives de connexion. |
| `app/launcher.py` | Demarrage serveur Python, choix d'adresse, fenetre de controle et ouverture du navigateur. |
| `app/analysis/base.py` | Contrat commun `AnalysisBackend`, `AnalysisParams`, `Phase` et moteurs desactives. |
| `app/analysis/motion.py` | Detection de mouvement, signal temporel, seuillage, hysteresis et segmentation des phases. |
| `app/analysis/video.py` | Ouverture OpenCV commune et correction de l'orientation lue dans les metadonnees video. |
| `app/analysis/posture.py` | Echantillonnage local MediaPipe, points d'articulation et angles 2D estimes. |
| `app/analysis/operation_learning.py` | Apprentissage experimental local sur annotations humaines (HOG/flux optique, SVM) et propositions a verifier. |
| `app/analysis/azure_vision.py`, `app/analysis/ollama.py` | Emplacements de futurs moteurs externes ; ils sont desactives et refusent l'analyse. |
| `app/ergonomics/scoring.py` | Calcul deterministe des pre-cotations RULA/REBA, incertitudes et resume temporel. |
| `app/services/cycle_analysis.py` | Proposition de cycles depuis les phases et statistiques descriptives des cycles valides. |
| `app/services/excel_export.py` | Generation du classeur Excel, feuilles, formules, styles, validations et graphiques. |
| `app/static/*.html` | Pages tableau de bord, revue, synthese, connexion, configuration initiale et comptes. |
| `app/static/app.js` | Logique principale de la revue : video, phases, ROI, operations, cycles et ergonomie. |
| `app/static/dashboard.js`, `summary.js` | Interactions du tableau de bord et de la synthese. |
| `app/static/auth-ui.js`, `auth-pages.js`, `users.js` | Interface des sessions, pages de connexion et administration des comptes. |
| `app/static/styles.css` | Styles partages de l'interface. |
| `tests/` | Tests pytest des API, calculs, analyses, authentification et interface. |
| `tools/` | Outils de construction et de preparation du projet ; ce ne sont pas des modules du serveur. |
| `dist/` | Executables construits. Plusieurs fichiers peuvent etre des versions historiques : verifier le nom et la date avant distribution. |
| `wheelhouse/` | Paquets Python (`.whl`) utilises pour une installation hors ligne. |
| `presentation/` | Supports de presentation, separes de l'application executable. |
| `kaizen_video_study.py`, `kaizen_video_study_v2.py` | Anciens prototypes CLI autonomes ; le serveur web courant est le package `app/`. |

## 4. Demarrage et configuration locale

### Mode Python

Depuis la racine du projet, sous Windows :

```powershell
.\run_kaizen_studio.bat
```

Pour un lancement manuel apres installation des dependances :

```powershell
python -m pip install --user -r requirements.txt
python -m app.launcher
```

`app.launcher` lit la configuration de `app.config`, demarre Uvicorn sur le port 8000 et ouvre
l'interface une fois `/api/health` disponible. `KAIZEN_STUDIO_HOST` vaut par defaut `127.0.0.1`.
L'ecoute reseau est encadree : une adresse IPv4 privee explicite est necessaire et HTTP LAN exige
une autorisation explicite ; TLS se configure avec `KAIZEN_STUDIO_SSL_CERTFILE` et
`KAIZEN_STUDIO_SSL_KEYFILE`. Ne jamais remplacer cette protection par `0.0.0.0`.

Le lanceur graphique de l'executable autonome est `kaizen_studio_exe.py`; il propose le mode local ou
un mode reseau prive et pilote le serveur Uvicorn.

### Repertoires de donnees

Les donnees operationnelles ne sont pas stockees dans le dossier du code. Le chemin par defaut est :

```text
%LOCALAPPDATA%\Kaizen Studio\
    data\kaizen_studio.db
    videos\
    exports\
    models\
    tmp\
```

`KAIZEN_STUDIO_DATA_DIR` permet de definir un autre emplacement avant de demarrer. Ce repertoire peut
contenir des videos d'operateurs et des donnees personnelles : le proteger et appliquer les regles
internes de conservation/suppression. Une copie du code source ne contient donc pas necessairement les
projets de l'utilisateur ni les videos.

## 5. Donnees et persistance

SQLite est le stockage de reference. `init_db()` dans `app/db.py` cree les tables et ajoute les
colonnes manquantes avec des migrations additives, afin de conserver les bases deja installees.

Relations principales :

```text
users 1---* user_sessions
users 1---* projects 1---* stations
stations 1---* phases
stations 1---* cycles
stations 1---* video_annotations
projects 1---* project_operations ---* video_annotations
stations 1---* ergonomic_assessments
settings : parametres globaux cle/valeur
```

Les stations portent egalement les metadonnees video, la ROI, la fenetre temporelle, les signaux
enregistres, la repartition train/validation/exclusion et `analysis_configuration_json`. Cette
configuration conserve les parametres et brouillons des quatre sections de revue **par poste**.
Les resultats valides (phases, annotations, cycles, cotations) ont leurs propres tables. La case de
confirmation officielle ergonomique n'est pas restauree automatiquement.

Les identifiants de session ne sont pas stockes en clair : seul leur hash est persiste. Les projets
sont rattaches a leur proprietaire ; les routes privees appliquent les controles d'acces.

## 6. Parcours d'une analyse video

1. L'interface importe la video par `/api/projects/{id}/stations/import` ou `import-stream`.
2. Le serveur place la video dans le repertoire local gere, extrait sa duree/FPS et cree une station.
3. La page `/review/{station_id}` charge la station, ses donnees et ses phases depuis l'API.
4. L'aperçu ROI est extrait par `/api/stations/{id}/frame`. La ROI utilise des coordonnees relatives
   a l'image affichee et peut contenir plusieurs rectangles.
5. L'analyse est demarree par `POST /api/stations/{id}/analysis`. `main.py` place le travail dans
   un `ThreadPoolExecutor` d'un worker. Le navigateur interroge `GET /api/jobs/{job_id}` pour suivre
   la progression.
6. `MotionAnalysisBackend` analyse le signal ; le serveur persiste le signal, son seuil et les phases
   dans SQLite. Les reglages de seuil et de duree minimale peuvent ensuite resegmenter le signal sans
   relire la video via `POST /api/stations/{id}/resegment`.
7. L'utilisateur verifie et modifie les phases ; les operations manuelles sont enregistrees par API.
8. La synthese est servie par `/api/projects/{id}/summary`; l'export Excel est genere par
   `/api/projects/{id}/export.xlsx`.

La progression des jobs est en memoire : elle n'est pas garantie apres un redemarrage du serveur.
Les resultats effectivement termines sont, eux, enregistres dans SQLite.

### Orientation video

Toute lecture serveur servant aux images, au mouvement, aux postures ou a l'apprentissage doit passer
par `app/analysis/video.py` :

- `open_video_capture()` force le backend FFmpeg quand disponible et demande la rotation automatique ;
- `orient_video_frame()` applique les metadonnees de rotation si le backend ne l'a pas deja fait.

Cette regle maintient l'alignement entre le lecteur du navigateur, l'image de ROI et les repères
d'articulation. Ne pas remplacer ces helpers par un `cv2.VideoCapture` isole sans verifier ce cas.

## 7. Sections de la revue

La page `app/static/review.html` contient quatre onglets et un lecteur partage. Le code UI de la
revue est dans `app/static/app.js`.

| Onglet | Donnees et traitements |
| --- | --- |
| 1. Revue | Signal de mouvement, seuil, duree minimale, fenetre, ROI, phases, description, categorie, commentaires et chronos reels. |
| 2. Operations & annotations | Referentiel de noms par projet, annotations temporelles, split train/validation/exclu et apprentissage experimental local. |
| 3. Cycles | Bornes de cycle manuelles, suggestions basees sur les arrets et statistiques. Une suggestion n'est pas une validation de cycle. |
| 4. Ergonomie | Images et angles 2D MediaPipe, facteurs observateur, pre-cotation deterministe RULA/REBA et enregistrement uniquement apres confirmation. |

Les controles de configuration et brouillons sont automatiquement sauves par section avec
`PUT /api/stations/{id}/analysis-configuration`. L'onglet actif est memorise par poste dans le
stockage local du navigateur. La ROI et la fenetre d'analyse sont en plus persistees sur la station.

## 8. Contrat d'analyse et moteurs

`app/analysis/base.py` definit :

- `AnalysisBackend.analyze(video_path, params, ...) -> list[Phase]` ;
- `AnalysisParams` pour la fenetre, le FPS d'echantillonnage, la ROI, le lissage, les seuils et les
  durees minimales ;
- `Phase` pour les bornes, le type et le mouvement moyen.

`MotionAnalysisBackend` est le moteur local active. Pour ajouter un moteur, respecter ce contrat,
gerer la progression et les erreurs, conserver la localite par defaut et tester les cas de videos
tournees. Les adaptateurs `AzureVisionBackend` et `OllamaVisionBackend` heritent du comportement
desactive ; leur activation reelle necessiterait une decision explicite de gouvernance, une
configuration documentee et des controles de confidentialite.

`app/analysis/posture.py` utilise MediaPipe pour produire des points et angles 2D approximatifs.
`app/ergonomics/scoring.py` applique localement des tables deterministes a ces angles et aux facteurs
observes. Les resultats doivent toujours etre presentes comme une pre-cotation a confirmer, jamais
comme un diagnostic ou une mesure biomecanique exacte.

## 9. API par responsabilite

Toutes les routes sont declarees dans `app/main.py`; les schemas d'entree sont dans `app/models.py`.

- **Comptes** : `/api/auth/*`, `/api/admin/users*`.
- **Projets et postes** : `/api/projects*`, `/api/dashboard`, `/api/stations*`.
- **Import, lecture et analyses** : `/api/projects/{id}/stations/import*`,
  `/api/stations/{id}/video`, `/frame`, `/analysis`, `/posture-analysis`,
  `/api/jobs/{job_id}` et `/resegment`.
- **Phases** : `/api/stations/{id}/phases`, modification, coupe et fusion.
- **Configuration de revue** : `/api/stations/{id}/analysis-settings` pour ROI/fenetre et
  `/analysis-configuration` pour les brouillons/reglages des quatre onglets.
- **Operations et apprentissage** : `/api/projects/{id}/operations*`, annotations de station,
  `annotation-dataset`, `annotation-manifest`, `operation-model` et `operation-suggestions`.
- **Cycles** : `/api/stations/{id}/cycles` et `/cycle-candidates`.
- **Ergonomie** : `/api/ergonomics/score` calcule sans enregistrer ; les routes
  `/api/stations/{id}/ergonomic-assessments` enregistrent/listent les cotations explicitement confirmees.
- **Synthese et fichiers** : `/api/projects/{id}/summary`, `/export.xlsx`, `/api/exports`.
- **Administration locale** : `/api/settings`, `/api/maintenance/purge`.

La liste exacte et les schemas evoluent avec le code ; les decorateurs de routes dans `app/main.py`
et les tests API restent la reference en cas d'ecart avec ce resume.

## 10. Excel et cycles

`app/services/excel_export.py` construit le classeur avec `openpyxl`. Il comporte les feuilles
`Synthese`, `Etapes` et `Notes`, des formules Excel, un graphique Yamazumi, des listes de validation
et des lignes de marge pour les etapes ajoutees. Garder les calculs formules dans Excel quand le
classeur doit rester modifiable par l'utilisateur.

`app/services/cycle_analysis.py` propose des intervalles depuis les phases et calcule des statistiques
descriptives. Un cycle propose automatiquement doit toujours etre verifie et enregistre explicitement.

## 11. Tests et commandes utiles

Depuis la racine du projet, avec Python 3.11 et les dependances installees :

```powershell
python -m pytest -q
python -m compileall -q app tests
node --check app\static\app.js
```

Fichiers de tests importants :

- `tests/test_motion_analysis.py` : mouvement, ROI et fusion des phases ;
- `tests/test_video_orientation.py` : rotation par metadonnees et comportement de l'ouverture video ;
- `tests/test_posture_analysis.py` : analyse des postures ;
- `tests/test_ergonomic_scoring.py` et `tests/test_ergonomic_scoring_api.py` : grilles RULA/REBA et API ;
- `tests/test_video_import.py` : import video et apercu ROI ;
- `tests/test_analysis_jobs.py` : progression et persistance des travaux ;
- `tests/test_operation_learning.py` : apprentissage local ;
- `tests/test_cycle_analysis.py` : propositions/statistiques de cycles ;
- `tests/test_excel_export.py` et `tests/test_excel_api.py` : classeur et export ;
- `tests/test_auth.py` : comptes, sessions et autorisations ;
- `tests/test_review_ui.py` : structure et comportements attendus de la revue.

Les tests API utilisent une base SQLite temporaire (`tests/conftest.py`) ; ils ne doivent pas modifier
la base utilisateur dans `%LOCALAPPDATA%`.

## 12. Guide de contribution pour un agent IA

Avant de modifier le projet :

1. Lire ce document et les sections pertinentes de `README.md`.
2. Suivre un parcours precis entre controle HTML, handler JavaScript, route FastAPI, schema Pydantic,
   acces SQLite, module de calcul et tests. `app/main.py` est le point de liaison, mais eviter d'y
   accumuler des algorithmes.
3. Chercher les helpers existants avant d'en ajouter. Pour toute lecture video serveur, reutiliser
   `open_video_capture()` et `orient_video_frame()`.
4. Si le schema SQLite change, ajouter une migration additive dans `init_db()` et un test qui couvre
   l'API/le chargement. Ne pas supposer qu'une base utilisateur peut etre supprimee ou recreee.
5. Pour un changement d'interface, mettre a jour les tests de `test_review_ui.py` et incrémenter le
   parametre de version de la ressource dans le HTML si necessaire au cache.
6. Pour un nouvel algo, tester les cas controles et limites, documenter ce que le resultat signifie et
   ce qu'il ne signifie pas.
7. Mettre a jour ce document et `README.md` si les modules, routes, stockage ou commandes changent.
8. Executer les tests pertinents, puis la suite complete si le changement touche plusieurs couches.

Contraintes a ne pas casser :

- pas de telemetrie ni d'appel externe dans le mode par defaut ; pas de CDN ;
- serveur local par defaut ; les modes reseau ont des garde-fous et ne sont pas a assouplir ;
- aucune identification de personne et aucune affirmation que `motion` comprend le travail ;
- temps automatiques = estimations a valider au chronometre ;
- une pre-cotation ergonomique n'est pas un diagnostic et la confirmation humaine reste obligatoire ;
- garder les erreurs visibles, les donnees privees associees a leur proprietaire et les videos dans le
  stockage local configure ;
- ne pas confondre les prototypes CLI a la racine avec l'application web du package `app/`.

## 13. Fichiers a ne pas confondre

- `README.md` : guide d'installation, d'utilisation et de configuration.
- `ARCHITECTURE.md` : organisation interne, responsabilites des modules et parcours techniques.
- `dist/*.exe` : binaires produits, qui ne remplacent pas les sources.
- `build/` : fichiers intermediaires de construction ; regenerables et normalement absents d'une
  copie de distribution du code.
- `%LOCALAPPDATA%\Kaizen Studio` : donnees actives des utilisateurs ; a sauvegarder/proteger
  separement du code, uniquement selon les regles de l'entreprise.
