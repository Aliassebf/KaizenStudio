"""Moteur Azure Vision désactivé par défaut.

Il reste présent pour les futures intégrations IA contrôlées, mais il ne doit être activé
qu'avec une configuration explicite et une approbation de la gouvernance IA de l'entreprise.
"""

from __future__ import annotations

from pathlib import Path

from .base import AnalysisBackend, AnalysisParams, Phase, DisabledBackend


class AzureVisionBackend(DisabledBackend):
    """Moteur Azure Vision non activé par défaut."""

    name = "azure_vision"
    warning_message = (
        "Le moteur Azure Vision est désactivé par défaut. Il exige une approbation explicite "
        "de la gouvernance IA de l'entreprise et une configuration dédiée."
    )

    def analyze(self, video_path: str | Path, params: AnalysisParams) -> list[Phase]:
        raise RuntimeError(self.warning_message)
