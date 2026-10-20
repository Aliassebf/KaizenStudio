"""Accès sûr aux fichiers gérés par Kaizen Studio (anti-lecture arbitraire de fichiers)."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def managed_file_path(value: str | None, root: Path) -> Path | None:
    """Chemin résolu s'il se trouve STRICTEMENT sous ``root``, sinon None."""
    if not value:
        return None
    resolved_root = root.resolve()
    try:
        resolved_path = Path(value).resolve()
    except (OSError, RuntimeError):
        return None
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        return None
    return resolved_path


def require_managed_video(value: str | None, root: Path) -> Path:
    """À utiliser AVANT toute lecture/diffusion d'une vidéo de poste.

    Bloque le scénario : POST /api/projects/{id}/stations avec
    ``video_path = "C:/Users/.../kaizen_studio.db"`` puis GET /api/stations/{id}/video
    → téléchargement de n'importe quel fichier lisible par le serveur
    (base des mots de passe, vidéos d'autres utilisateurs, documents…).
    """
    path = managed_file_path(value, root)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Vidéo locale introuvable pour ce poste.")
    return path
