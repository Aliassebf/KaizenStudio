"""Moteur Ollama désactivé par défaut.

Le modèle de vision Ollama n'est pas activé par défaut, car il impose un cadre de validation
et de sécurité supplémentaire pour toute donnée personnelle ou opérateur visible dans la vidéo.
"""

from __future__ import annotations

from pathlib import Path

from .base import AnalysisParams, Phase, DisabledBackend


class OllamaVisionBackend(DisabledBackend):
    """Moteur Ollama non activé par défaut."""

    name = "ollama"
    warning_message = (
        "Le moteur Ollama est désactivé par défaut. Il nécessite une approbation de la gouvernance "
        "IA de l'entreprise et un paramétrage explicite pour la confidentialité et la sécurité."
    )

    def analyze(self, video_path: str | Path, params: AnalysisParams) -> list[Phase]:
        raise RuntimeError(self.warning_message)
