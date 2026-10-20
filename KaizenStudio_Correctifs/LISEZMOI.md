# Kaizen Studio – Kit de correctifs v1.0

## Installation (PowerShell, à la racine du projet)

```powershell
cd "C:\Users\FOFANABA\OneDrive - Otis Global Tenant\Old_PC\Dev_Log\KaizenStudio-Projet-Complet"
# 1. Décompresser le kit ici -> dossier KaizenStudio_Correctifs\
# 2. Simulation (n'écrit rien)
py -3.11 KaizenStudio_Correctifs\appliquer_correctifs.py --verifier
# 3. Application (sauvegarde automatique dans _sauvegarde_correctifs_<date>\)
py -3.11 KaizenStudio_Correctifs\appliquer_correctifs.py
# 4. Contrôles
py -3.11 -m pytest -q
node --check app\static\app.js
py -3.11 -m app.launcher
# 5. Nouvel exécutable
.\build_windows_exe.bat
```
Si une étape échoue, rien n'est écrit et le script indique quel extrait n'a pas été trouvé.
Retour arrière : recopier le contenu du dossier `_sauvegarde_correctifs_<date>\`.

## Ce qui est corrigé

| Code | Correction |
|---|---|
| fichiers | `db.py` (connexions fermées, WAL, migrations versionnées), `video.py`, `motion.py` (horodatage réel, phases doublées), `posture.py` (angles corrigés du format d'image), `core/files.py`, tests |
| M05 M07 | Un chemin vidéo saisi par l'API ne permet plus de télécharger un fichier hors du dossier vidéo géré |
| M21 | `/api/settings` n'accepte que `purge_days` et `video_max_mb` |
| M11 M12 J02-J07 | Relancer l'analyse ou bouger un curseur n'efface plus les phases décrites/classées/chronométrées sans confirmation |
| M15 M16 | Référentiel d'opérations alimenté à la création de phase (test qui échouait) |
| M03 M04 T01 | La purge se base sur la dernière activité du projet, plus sur sa date de création |
| M20 | Écart au takt calculé sur la médiane des cycles validés (`temps_observe_total` conservé) |
| M17 M18 M19 | Coupe/fusion : chrono réel, catégorie et mouvement moyen cohérents |
| M06 M08 M09 M10 | Import vidéo non bloquant, erreurs d'analyse journalisées, mémoire des tâches bornée |
| M22 | Protection contre l'intégration de l'application dans un cadre (clickjacking) |
| J01 | Session expirée → retour à la connexion ; messages d'erreur 422 lisibles |
| J08 J09 | La sauvegarde automatique de l'onglet Ergonomie fonctionnait seulement après un clic sur « Renommer » |
| X01-X06 | Export Excel : un texte commençant par « = » n'est plus écrit comme une formule |

## Après installation
- Relancer « Suivi de posture » sur les postes déjà analysés : les angles enregistrés avant ce
  correctif sont déformés. Revoir les cotations RULA/REBA confirmées qui s'appuyaient dessus.
- Faire réanalyser/approuver le nouvel exécutable par l'IT avant diffusion.
