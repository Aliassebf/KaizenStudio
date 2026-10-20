# Kaizen Studio

Application locale d'étude de temps et de mouvements à partir de vidéos de postes de travail.
Les temps produits par l'analyse vidéo sont des **ESTIMATIONS à valider par chronométrage réel**.
Le moteur `motion` mesure uniquement la présence de mouvement ; il ne reconnaît ni les gestes,
ni les opérations, ni les personnes.

Pour comprendre l'organisation interne, les flux de données et les modules avant de contribuer,
consultez [ARCHITECTURE.md](ARCHITECTURE.md).

## Prérequis Windows

- Windows et Python 3.11 installé pour le compte utilisateur, sans privilèges administrateur.
- Accès à l'index de paquets Python approuvé par l'entreprise lors de l'installation, ou un
  dossier `wheelhouse` préparé hors ligne.
- Sur le PC cible, Python 3.11 reste nécessaire ; les roues fournissent les paquets Python, pas
  l'interpréteur lui-même.
- Les fichiers vidéo doivent être accessibles localement sur le poste.

## Créer l'exécutable Windows

Sur le PC de construction, avec Python 3.11 64 bits et les dépendances de l'application
disponibles, double-cliquez sur `build_windows_exe.bat`. Le script crée `dist\KaizenStudio.exe`,
un exécutable autonome avec l'icône KS, Python embarqué et les dépendances nécessaires, dont
OpenCV et MediaPipe. Aucun Python séparé n'est requis sur le PC cible. La construction nécessite
PyInstaller ; si celui-ci manque, installez les dépendances de construction avec
`python -m pip install -r requirements-build.txt`. La taille de l'exécutable peut atteindre plusieurs
centaines de mégaoctets. Faites analyser et approuver le binaire par l'informatique avant son
transfert ou son exécution.

Au démarrage, une fenêtre propose les deux modes : ce PC uniquement ou HTTP sur le réseau privé.
Le choix réseau détecte une IPv4 privée et affiche une confirmation graphique des risques avant
démarrage. L'exécutable ouvre ensuite le navigateur et garde une fenêtre de contrôle pour afficher
l'adresse et arrêter le serveur. Il ne crée pas de règle de pare-feu ; l'IT doit limiter TCP 8000 aux
postes autorisés et vérifier l'absence d'exposition à Internet. HTTP ne chiffre ni les mots de passe
ni les vidéos. Les données restent stockées dans `%LOCALAPPDATA%\Kaizen Studio`, comme pour le
lancement Python.

## Installation et démarrage en une commande

Dans l'Explorateur Windows, double-cliquer sur `run_kaizen_studio.bat`, ou depuis PowerShell :

```powershell
.\run_kaizen_studio.bat
```

Le script :

1. vérifie Python 3.11 ;
2. installe/vérifie les dépendances pour l'utilisateur courant (`pip --user`, sans droits admin),
   depuis `wheelhouse` sans réseau lorsqu'il contient les roues, ou depuis l'index configuré par pip
   si aucun wheelhouse n'est présent ;
3. lance le serveur lié exclusivement à `127.0.0.1` et ouvre le navigateur par défaut.

Pour préparer l'installation hors ligne, sur un PC Windows connecté disposant de Python 3.11,
double-cliquer sur `prepare_offline_dependencies.bat`. Ce script télécharge les roues compatibles
dans `wheelhouse` sans installer les paquets. Copiez ensuite le dossier complet du projet, y compris
`wheelhouse`, sur le PC cible via un moyen autorisé par l'entreprise. Au lancement, les dépendances
sont installées depuis ces fichiers avec `--no-index`, sans accès à un index réseau. Les deux PC
doivent utiliser une architecture et une version Python compatibles (Windows, Python 3.11,
généralement 64 bits). Validez les paquets téléchargés avec l'informatique avant leur transfert.
L'application elle-même ne contacte pas Internet, n'envoie aucune télémétrie et charge ses ressources
depuis le serveur local.

Arrêter le serveur avec `Ctrl+C` dans la fenêtre du script. Par défaut, l'URL locale est
[http://127.0.0.1:8000/](http://127.0.0.1:8000/) et le serveur n'est accessible que sur ce PC.
Pour le lancer en HTTP sur le réseau local avec une adresse IPv4 détectée automatiquement,
double-cliquez sur `run_kaizen_studio_lan.bat` et confirmez explicitement l'avertissement. Ce mode
ne chiffre pas les communications : mots de passe, vidéos et autres données peuvent être interceptés
par une personne ayant accès au trafic réseau. Ne l'utilisez que sur un réseau privé isolé approuvé
par l'entreprise. Le script lie le serveur à une IPv4 privée précise (jamais à `0.0.0.0`), mais cela
ne garantit pas à lui seul que le service soit inaccessible depuis Internet : le routage, le pare-feu
Windows et les équipements réseau doivent être vérifiés et filtrés par l'IT. Le script ne crée aucune
règle de pare-feu. Les autres PC autorisés ouvrent `http://<IPv4-du-serveur>:8000/`. Pour le mode
recommandé, configurez plutôt HTTPS avec certificat d'entreprise comme décrit ci-dessous.

## Comptes locaux et accès équipe

Au premier démarrage, créez l'administrateur local sur la page de configuration. Les mots de passe
doivent comporter au moins 12 caractères et sont stockés hachés avec PBKDF2-SHA256. L'administrateur
crée les comptes dans « Gérer les comptes » et peut choisir le rôle « Utilisateur » ou
« Administrateur » (le rôle utilisateur est sélectionné par défaut). Plusieurs administrateurs peuvent
ainsi gérer les comptes ; chacun peut désactiver un compte et réinitialiser son mot de passe, mais le
dernier administrateur actif ne peut pas être désactivé. Chaque utilisateur ne voit que ses propres
projets ; les API, vidéos, évaluations et exports
vérifient également cette propriété. Après la création du premier administrateur depuis le PC serveur,
les inscriptions publiques sont désactivées. Les anciens projets sans propriétaire sont attribués à
l'administrateur initial. Le compte peut changer son propre mot de passe ; les sessions sont
révoquées à la modification du mot de passe et à la désactivation du compte. Les tentatives de
connexion sont limitées, les sessions expirent après 12 heures et utilisent un cookie `HttpOnly`,
`SameSite=Strict` (et `Secure` en HTTPS). Conservez des sauvegardes protégées de la base et des vidéos ;
il n'existe pas de récupération automatique d'un mot de passe administrateur perdu.

Pour l'accès depuis d'autres PC, configurez de préférence une adresse IPv4 privée fixe sur le PC
serveur. Le lanceur `run_kaizen_studio_lan.bat` détecte l'adresse IPv4 active et configure
`KAIZEN_STUDIO_HOST` pour ce démarrage ; pour une configuration manuelle, définissez cette variable
avec l'adresse (par exemple `192.168.1.20`). N'utilisez pas `0.0.0.0`. En HTTP, le lanceur exige une
confirmation explicite et le serveur refuse les adresses non privées. Cela ne suffit toutefois pas à
garantir l'absence d'accès depuis Internet : l'IT doit vérifier le routage et limiter le port TCP 8000
au sous-réseau autorisé. Le mode HTTP n'assure aucune confidentialité des échanges. Pour protéger
les mots de passe et les vidéos, préférez HTTPS avec un certificat émis/approuvé par l'entreprise.
Le premier compte administrateur ne peut être créé qu'en ouvrant Kaizen Studio localement sur le PC
serveur.
Définissez alors `KAIZEN_STUDIO_SSL_CERTFILE` et `KAIZEN_STUDIO_SSL_KEYFILE` vers les fichiers du
certificat et de sa clé privée. En HTTPS, le cookie de session est automatiquement marqué `Secure`.
N'exposez jamais ce service à Internet ; faites valider l'architecture, les accès et la conservation
des vidéos par les équipes informatique, sécurité et RGPD.

## Lancement manuel

```powershell
python -m pip install --user -r requirements.txt
python -m app.launcher
```

Pour configurer le serveur sur son adresse LAN avec TLS, dans PowerShell (chemins et IP à remplacer
par ceux approuvés par l'entreprise) :

```powershell
$env:KAIZEN_STUDIO_HOST = "192.168.1.20"
$env:KAIZEN_STUDIO_SSL_CERTFILE = "C:\certificats\kaizen-studio.crt"
$env:KAIZEN_STUDIO_SSL_KEYFILE = "C:\certificats\kaizen-studio.key"
python -m app.launcher
```

Ou, sans ouverture automatique du navigateur :

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Données et confidentialité

Par défaut, la base SQLite, les vidéos, exports et fichiers temporaires sont conservés sous
`%LOCALAPPDATA%\Kaizen Studio`. Le chemin peut être remplacé avec la variable d'environnement
`KAIZEN_STUDIO_DATA_DIR`, avant le lancement.

Les moteurs Azure Vision et Ollama ne sont pas activés dans l'application. Toute future activation
de traitement IA doit faire l'objet d'une approbation explicite de la gouvernance IA de l'entreprise.
Avant tout enregistrement, informer les opérateurs et valider les exigences RGPD et sociales
applicables. L'application ne réalise aucune extraction de visages.

## Fonctionnalités livrées

- Moteur OpenCV `motion` local, sans IA.
- API FastAPI et persistance SQLite locale.
- Comptes locaux avec rôles administrateur/utilisateur, mots de passe hachés, sessions HTTP-only,
  renouvellement/réinitialisation de mot de passe et cloisonnement des projets par propriétaire.
- Tableau de bord de pilotage avec indicateurs projets/postes/cotations, recherche, filtres, tri,
  état d'analyse des postes et derniers scores RULA/REBA saisis.
- Tableau de bord permettant la création de projets et l'import vidéo MP4, MOV ou AVI par poste.
  La taille maximale par défaut est de 2048 Mo et se configure par un administrateur (1 à 20480 Mo) ;
  pour une vidéo de 6 Go, régler la limite à environ 7000 Mo. L'import conserve temporairement
  une copie du fichier : prévoir environ la taille de la vidéo libre sur le volume temporaire Windows
  et sur le volume de stockage de l'application. Durée et FPS sont lus à l'import.
- Projets présentés en cartes responsive avec indicateur d'avancement des analyses, synthèse et
  suppression regroupées, et formulaire d'ajout de poste repliable pour réduire l'encombrement.
- Suppression confirmée d'un poste, de sa vidéo gérée localement et de toutes ses phases.
- Suppression confirmée d'un projet entier, avec ses postes, vidéos gérées et données associées.
- Conservation configurable en jours (90 par défaut) : les projets expirés sont purgés au démarrage
  et toutes les 24 heures, avec une action de purge immédiate depuis le tableau de bord.
- Écran de revue avec capture locale de l'image vidéo à la pause, ajout/suppression de plusieurs
  ROI dessinées à la souris et enregistrées par poste (l'orientation de l'image suit celle affichée
  par le lecteur ; les repères de posture et les zones ROI restent alignés sur la vidéo ; mouvement calculé sur l'union des zones),
  lancement d'analyse en tâche de fond, progression, réglage du seuil et de la durée minimale qui
  recalculent les phases depuis le signal enregistré sans relire la vidéo, courbe lissée persistée,
  modification de phases, coupe, fusion et saisie de chronos réels. Le champ « Opération observée »
  propose les noms déjà saisis dans le projet et indique les opérations associées à plusieurs phases.
  Ces noms sont renseignés par l'utilisateur : le moteur motion ne les identifie pas.
- Référentiel d'opérations partagé par projet, classe « Autre / incertain », annotations humaines début/fin à
  0,1 s sur la vidéo, modification/suppression et affichage des intervalles sur une frise dédiée.
  Les annotations sont indépendantes des phases Yamazumi. Les intervalles d'une même vidéo ne
  peuvent pas se chevaucher ; les annotations peuvent se toucher exactement. L'écran de revue est
  réparti en quatre onglets : Revue (frise et étapes), Opérations & annotations, Cycles et
  Ergonomie. Le lecteur vidéo, les réglages d'analyse et la ROI restent dans une colonne partagée,
  accessible depuis tous les onglets ; sur grand écran elle reste visible pendant le défilement.
  Sur écran étroit, cette colonne devient compacte et fixe en haut pour garder les onglets utilisables.
  Dans l'onglet Revue, les commandes et filtres des étapes restent en place tandis que la liste des
  étapes défile dans sa propre zone. Le zoom navigateur est autorisé.
  La navigation est accessible au clavier et l'onglet actif est mémorisé dans le navigateur par poste.
  Les réglages et brouillons des quatre onglets sont enregistrés automatiquement dans la base locale
  par poste et restaurés à la réouverture ; la confirmation officielle RULA/REBA n'est jamais mémorisée.
- Apprentissage local expérimental des opérations avec OpenCV SVM et des caractéristiques HOG/flux
  optique calculées sur les vidéos annotées ; aucune vidéo ni donnée n'est envoyée sur Internet et
  aucun modèle pré-entraîné n'est téléchargé. L'entraînement exige au moins deux opérations avec
  deux annotations chacune dans le jeu `train`, ainsi qu'au moins une annotation correspondante dans
  `validation`. Les résultats de validation sont mesurés sur des vidéos distinctes. Les opérations
  avec trop peu d'exemples sont explicitement ignorées. Le modèle et ses métadonnées sont stockés
  localement par projet et supprimés avec celui-ci ; modifier les annotations, les opérations ou les
  splits invalide le modèle.
- Les propositions classent les phases d'activité d'une vidéo `excluded` seulement. Un score
  indicatif inférieur au seuil de rejet n'est pas proposé. Une proposition n'est enregistrée qu'après
  acceptation explicite de l'utilisateur ; les phases déjà annotées sont ignorées. Les scores ne sont
  pas des probabilités calibrées et les noms/limites restent des estimations à vérifier sur la vidéo.
  Ce classifieur visuel supervisé léger est un premier point de départ, pas un modèle pré-entraîné
  d'action humaine ; sa qualité doit être évaluée sur les vidéos représentatives de l'usine.
- Affectation de chaque vidéo entière au jeu d'entraînement, de validation ou à l'exclusion. La
  séparation se fait au niveau vidéo pour éviter de répartir des images d'un même clip entre les
  jeux ; Kaizen Studio refuse qu'un même chemin vidéo soit affecté aux deux splits. Le récapitulatif
  du projet affiche les volumes par split et par opération ; un manifeste JSON local peut être exporté
  pour préparer une évaluation ultérieure.
- Frise chronologique défilable avec numéros de phase identiques à la liste (par exemple
  « 1. Activité »), sélection synchronisée avec la carte correspondante dans « Étapes », mise en
  évidence sur le graphique du mouvement et lecture limitée à l'intervalle choisi. Le type d'une
  phase peut être corrigé entre « Activité » et « Arrêt » dans sa carte ; la correction est
  enregistrée et reflétée sur la frise. Le bouton « Lire toute la vidéo » retire la limite de lecture.
- Comparaison de plusieurs cycles par poste : limites saisies manuellement avec l'instant vidéo courant
  ou propositions à vérifier séparées par des arrêts prolongés. Les synthèses affichent la durée de
  chaque cycle, la moyenne, la médiane, le minimum, le maximum, l'écart-type et le coefficient de
  variation ; ces valeurs restent des estimations vidéo à confirmer par chronométrage.
- Suivi de posture MediaPipe exécuté localement à environ 2 images/s, squelette 2D superposé à la
  vidéo et angles estimés des coudes, épaules, genoux et de l'inclinaison du tronc. Le module
  déterministe `app/ergonomics/scoring.py` applique les grilles RULA/REBA pour proposer une
  pré-cotation min/probable/max par côté, avec détail des tables, hypothèses et fiabilité. Vue caméra
  et facteurs évaluateur sont saisis manuellement ; en présence d'une série, les postures aberrantes
  ou occultées sont écartées de la synthèse de série temporelle et la répétitivité/le statisme sont
  estimés. Après l'analyse, l'onglet liste toutes les images de posture avec leurs angles visibles et
  manquants. L'évaluateur choisit une image complète ou partielle ; les angles absents alimentent les
  fourchettes d'incertitude et les hypothèses, sans être inventés. « Utiliser l'instant vidéo courant »
  sélectionne l'image analysée la plus proche. La pré-cotation RULA/REBA porte sur cette posture
  choisie et remplit des champs modifiables sans enregistrer ni cocher la validation obligatoire.
  Le format
  existant des cotations persistées est inchangé ; l'instant, l'évaluateur et les observations/facteurs
  restent conservés. Ces scores ne sont pas officiels, ne sont pas un diagnostic, et doivent être
  vérifiés selon les méthodes officielles par une personne compétente.
- Tableau de bord et synthèse Yamazumi.
- La synthèse guide les projets sans poste vers l'ajout de vidéo et propose un accès direct à la
  revue des postes sans phases ou depuis le tableau récapitulatif.
- Export Excel avec les onglets `Synthèse`, `Étapes` et `Notes`, formules, validation de catégorie,
  graphique Yamazumi natif et lignes de réserve.
- Avertissement dans l'interface et les exports : les mesures automatiques sont des estimations.

## Limites du MVP actuel

- La courbe affichée est le signal échantillonné à 5 images/s et lissé sur environ 0,6 s ; elle
  mesure la présence de mouvement et n'identifie pas les actions.
- La revue ne remplace pas une validation terrain ni un chronométrage réel.
- Le suivi MediaPipe est une estimation 2D sensible au cadrage, aux occultations et à la vue caméra.
  Le calcul déterministe RULA/REBA est une pré-cotation indicative à faire vérifier et corriger par
  l'évaluateur ; la vidéo monoculaire ne fournit pas à elle seule la charge, la prise, les torsions ou
  les appuis, et ne permet aucun diagnostic médical.
- Pas de modèle pré-entraîné de reconnaissance d'actions, ni de reconnaissance de multi-opérateurs
  ou d'hébergement cloud.
- Un fichier référencé hors du dossier vidéo géré par Kaizen Studio est volontairement conservé
  même si son poste est supprimé ; l'API le signale.
- Un projet ayant une analyse en cours est ignoré par la purge automatique jusqu'à un prochain
  passage ; la suppression manuelle d'un poste ou projet est refusée pendant l'analyse.

## Tests

```powershell
python -m pytest -q
```

Le test de recalcul des formules par LibreOffice s'exécute automatiquement si `soffice` est
disponible dans le `PATH`. Sinon, il est ignoré ; les tests de structure des formules, du classeur,
du graphique natif, de l'API et du mécanisme de repli restent exécutés.

## API utile

- `GET /api/health` : état et indicateurs de fonctionnement local.
- `GET /api/auth/status`, `POST /api/auth/setup`, `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me` : configuration initiale et session locale.
- `GET/POST /api/admin/users`, `PATCH /api/admin/users/{user_id}/active` et
  `PUT /api/admin/users/{user_id}/password` : gestion réservée à l'administrateur.
- `PUT /api/auth/password` : changement de son propre mot de passe.
- `GET/POST /api/projects` : lister ou créer un projet (`nom`, `takt_s`).
- `PATCH /api/projects/{project_id}` : modifier le takt du projet (secondes, strictement positif).
- `DELETE /api/projects/{project_id}` : supprimer un projet, ses postes, ses phases et ses vidéos gérées.
- `GET/POST /api/projects/{project_id}/stations` : lister ou ajouter un poste.
- `GET/POST /api/projects/{project_id}/operations` : lister ou ajouter les opérations du référentiel projet.
- `PATCH/DELETE /api/projects/{project_id}/operations/{operation_id}` : renommer ou supprimer une opération non utilisée.
- `GET /api/projects/{project_id}/annotation-dataset` : résumé des vidéos et annotations par split et opération.
- `GET /api/projects/{project_id}/operation-model` : état du modèle local et de sa fraîcheur par rapport aux données.
- `POST /api/projects/{project_id}/operation-model/train` : entraîner puis évaluer le classifieur sur les vidéos des splits `train` et `validation`.
- `GET /api/projects/{project_id}/annotation-manifest` : exporter le manifeste d'annotations humain au format JSON.
- `POST /api/projects/{project_id}/stations/import` : créer un poste et importer sa vidéo locale.
- `DELETE /api/stations/{station_id}` : supprimer un poste, sa vidéo locale gérée et ses données.
- `GET/POST /api/stations/{station_id}/annotations` : lister ou créer une annotation temporelle humaine.
- `PATCH/DELETE /api/stations/{station_id}/annotations/{annotation_id}` : modifier ou supprimer une annotation.
- `PUT /api/stations/{station_id}/dataset-split` : affecter la vidéo entière à `train`, `validation` ou `excluded`.
- `POST /api/stations/{station_id}/operation-suggestions` : proposer, sans les enregistrer, des opérations pour les phases d'activité d'une vidéo `excluded`.
- `GET/POST /api/stations/{station_id}/phases` : lister ou ajouter une phase.
- `POST /api/stations/{station_id}/analysis` : lancer une analyse locale ; réponse avec `job_id`.
- `POST /api/stations/{station_id}/posture-analysis` : lancer le suivi MediaPipe local des postures ; réponse avec `job_id`.
- `POST /api/ergonomics/score` : calcul déterministe local d'une pré-cotation RULA/REBA et, si
  fournie, du résumé de série temporelle ; n'enregistre aucune cotation.
- `GET /api/jobs/{job_id}` : consulter l'état et la progression de l'analyse.
- `POST /api/stations/{station_id}/resegment` : recalculer les phases à partir du signal local.
- `GET /api/stations/{station_id}/frame?time_s=...` : extraire une image vidéo localement pour la ROI.
- `PUT /api/stations/{station_id}/analysis-settings` : enregistrer la ROI et la fenêtre d'analyse.
- `GET /api/settings` et `POST /api/settings` : consulter les réglages ou modifier `purge_days` (1–3650) et `video_max_mb`.
- `POST /api/maintenance/purge` : purger les projets dépassant le délai configuré.
- `PATCH /api/stations/{station_id}/phases/{phase_id}` : éditer les temps, le type Activité/Arrêt,
  la catégorie, la description ou le chrono.
- `POST /api/stations/{station_id}/phases/{phase_id}/split` : couper une phase au temps donné.
- `POST /api/stations/{station_id}/phases/merge` : fusionner deux phases voisines.
- `GET/POST /api/stations/{station_id}/cycles` : consulter ou enregistrer des intervalles de cycle.
- `PUT /api/stations/{station_id}/analysis-configuration` : enregistrer localement les réglages et
  brouillons des onglets de revue, opérations, cycles et ergonomie.
- `GET /api/stations/{station_id}/cycle-candidates` : proposer des intervalles séparés par des arrêts
  prolongés (`min_stop_s`, `min_cycle_s`) ; les résultats doivent être vérifiés sur la vidéo.
- `DELETE /api/stations/{station_id}/cycles/{cycle_id}` : supprimer un intervalle de cycle.
- `GET /api/projects/{project_id}/summary` : synthèse par catégorie et comparaison au takt.
- `GET /api/dashboard` : indicateurs consolidés, état des postes et dernières cotations enregistrées.
- `GET/POST /api/stations/{station_id}/ergonomic-assessments` : consulter/enregistrer les scores RULA/REBA validés manuellement, avec l'instant et les observations.
- `GET /api/projects/{project_id}/export.xlsx` : télécharger le classeur sous le nom
  `kaizen_studio_NomDuProjet.xlsx` (les caractères interdits par Windows sont remplacés).
  Les cycles enregistrés sont également listés dans l'onglet `Notes`.

## Prototype CLI historique

`kaizen_video_study.py` et `kaizen_video_study_v2.py` sont des prototypes distincts de l'application
web. Certaines options historiques, notamment le backend Azure, peuvent transmettre des images à un
service distant. **Ne pas utiliser ce backend avec des vidéos d'opérateurs sans approbation
explicite de la gouvernance et validation des règles de confidentialité.** Le mode local de
l'application web n'appelle pas ces scripts.
