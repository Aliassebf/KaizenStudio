from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class AnalysisParams:
    """Paramètres partagés par tous les moteurs d'analyse."""

    fps: float = 5.0
    start: float = 0.0
    end: Optional[float] = None
    roi: Optional[
        tuple[float, float, float, float]
        | tuple[tuple[float, float, float, float], ...]
    ] = None
    pixel_threshold: int = 25
    blur: int = 5
    smooth_seconds: float = 0.6
    min_phase_seconds: float = 1.0
    auto_threshold_pct: Optional[float] = None


@dataclass
class Phase:
    """Phase d'activité ou d'arrêt détectée dans le signal de mouvement."""

    start: float
    end: float
    type: str
    motion_mean_pct: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class AnalysisBackend(ABC):
    """Interface commune pour les moteurs d'analyse vidéo."""

    name = "base"
    enabled = True

    @abstractmethod
    def analyze(
        self,
        video_path: str | Path,
        params: AnalysisParams,
        progress_callback: Optional[Callable[[float], None]] = None,
        signal_callback: Optional[Callable[[list[dict[str, float]], float], None]] = None,
    ) -> list[Phase]:
        """Retourne des phases ordonnées et non chevauchantes."""


class DisabledBackend(AnalysisBackend):
    """Classe de base pour les moteurs désactivés par défaut."""

    enabled = False
    warning_message = "Ce moteur est désactivé par défaut et nécessite une approbation explicite de la gouvernance IA de l'entreprise."

    def analyze(
        self,
        video_path: str | Path,
        params: AnalysisParams,
        progress_callback: Optional[Callable[[float], None]] = None,
        signal_callback: Optional[Callable[[list[dict[str, float]], float], None]] = None,
    ) -> list[Phase]:
        raise RuntimeError(self.warning_message)
