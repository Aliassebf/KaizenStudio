from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    nom: str = Field(..., min_length=1, max_length=200)
    takt_s: float = Field(..., gt=0)


class ProjectUpdate(BaseModel):
    takt_s: float = Field(..., gt=0)


class ProjectOperationCreate(BaseModel):
    nom: str = Field(..., min_length=1, max_length=200)


class ProjectOperationUpdate(ProjectOperationCreate):
    pass


class VideoAnnotationCreate(BaseModel):
    operation_id: Optional[int] = Field(default=None, gt=0)
    debut_s: float = Field(..., ge=0)
    fin_s: float = Field(..., gt=0)


class VideoAnnotationUpdate(BaseModel):
    operation_id: Optional[int] = Field(default=None, gt=0)
    debut_s: Optional[float] = Field(default=None, ge=0)
    fin_s: Optional[float] = Field(default=None, gt=0)


class DatasetSplitUpdate(BaseModel):
    split: Literal["train", "validation", "excluded"]


class LocalAccountCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=12, max_length=256)


class AdminAccountCreate(LocalAccountCreate):
    is_admin: bool = False


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=12, max_length=256)


class PasswordReset(BaseModel):
    new_password: str = Field(..., min_length=12, max_length=256)


class ProjectOut(BaseModel):
    id: int
    nom: str
    takt_s: float
    cree_le: str


class StationCreate(BaseModel):
    nom: str = Field(..., min_length=1, max_length=200)
    video_path: Optional[str] = None
    roi: Optional[str] = None
    fenetre_debut: Optional[float] = 0.0
    fenetre_fin: Optional[float] = None


class StationOut(BaseModel):
    id: int
    project_id: int
    nom: str
    video_path: Optional[str]
    roi: Optional[str]
    fenetre_debut: Optional[float]
    fenetre_fin: Optional[float]


class PhaseCreate(BaseModel):
    ordre: int = Field(..., ge=1)
    debut_s: float = Field(..., ge=0)
    fin_s: float = Field(..., gt=0)
    type_auto: str = Field(..., pattern=r"^(activity|stop)$")
    description: Optional[str] = None
    categorie: Optional[str] = None
    commentaire: Optional[str] = None
    chrono_reel_s: Optional[float] = None
    mouvement_moyen_pct: Optional[float] = None


class PhaseOut(BaseModel):
    id: int
    station_id: int
    ordre: int
    debut_s: float
    fin_s: float
    type_auto: str
    description: Optional[str]
    categorie: Optional[str]
    commentaire: Optional[str]
    chrono_reel_s: Optional[float]
    mouvement_moyen_pct: Optional[float]


class AnalysisSettingsUpdate(BaseModel):
    roi: Optional[str] = None
    fenetre_debut: Optional[float] = Field(default=0.0, ge=0)
    fenetre_fin: Optional[float] = Field(default=None, gt=0)
    backend: Optional[str] = "motion"


class AnalysisConfigurationUpdate(BaseModel):
    section: Literal["review", "operations", "cycles", "ergonomics"]
    values: dict[str, Any]


class AnalysisRequest(BaseModel):
    fenetre_debut: Optional[float] = Field(default=None, ge=0)
    fenetre_fin: Optional[float] = Field(default=None, gt=0)
    roi: Optional[str] = None
    fps: float = Field(default=5.0, gt=0, le=30)
    seuil_pct: Optional[float] = Field(default=None, ge=0, le=100)
    duree_min_s: float = Field(default=1.0, ge=0, le=60)


class PostureAnalysisRequest(BaseModel):
    fenetre_debut: float = Field(default=0.0, ge=0)
    fenetre_fin: float = Field(..., gt=0)
    fps: float = Field(default=2.0, gt=0, le=5)


class CycleCreate(BaseModel):
    debut_s: float = Field(..., ge=0)
    fin_s: float = Field(..., gt=0)
    source: Literal["manual", "auto"] = "manual"


class ErgonomicAssessmentCreate(BaseModel):
    time_s: float = Field(..., ge=0)
    rula_score: Optional[int] = Field(default=None, ge=1, le=7)
    reba_score: Optional[int] = Field(default=None, ge=1, le=15)
    evaluator: str = Field(..., min_length=1, max_length=200)
    factors_notes: str = Field(..., min_length=1, max_length=4000)
    official_method_confirmed: bool


class ErgonomicScoringRequest(BaseModel):
    instant_s: float = Field(..., ge=0)
    view_camera: Literal["face", "profil_gauche", "profil_droit", "oblique", "inconnue"]
    angles: dict[str, Optional[float]] = Field(default_factory=dict)
    evaluator_factors: dict[str, object] = Field(default_factory=dict)
    series: list[dict[str, object]] = Field(default_factory=list)


class ResegmentRequest(BaseModel):
    seuil_pct: Optional[float] = Field(default=None, ge=0, le=100)
    duree_min_s: float = Field(default=1.0, ge=0, le=60)


class PhaseUpdate(BaseModel):
    debut_s: Optional[float] = Field(default=None, ge=0)
    fin_s: Optional[float] = Field(default=None, gt=0)
    type_auto: Optional[str] = Field(default=None, pattern=r"^(activity|stop)$")
    description: Optional[str] = None
    categorie: Optional[str] = None
    commentaire: Optional[str] = None
    chrono_reel_s: Optional[float] = Field(default=None, ge=0)


class PhaseSplit(BaseModel):
    temps_s: float = Field(..., ge=0)


class PhaseMerge(BaseModel):
    phase_ids: list[int] = Field(..., min_length=2, max_length=2)
