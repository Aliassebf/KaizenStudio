"""Accès sûr aux fichiers gérés par Kaizen Studio."""
from __future__ import annotations

from pathlib import Path


def managed_file_path(value: str | None, root: Path) -> Path | None:
    """Chemin résolu s'il se trouve STRICTEMENT sous ``root``, sinon None."""
    if not value:
        return None
    resolved_root = Path(root).resolve()
    try:
        resolved_path = Path(value).resolve()
    except (OSError, RuntimeError):
        return None
    if resolved_path == resolved_root or resolved_root not in resolved_path.parents:
        return None
    return resolved_path
