"""Tests de non-régression des améliorations (db, vidéo, mouvement, posture, jobs, fichiers).

À placer dans tests/ ; n'utilise que des fichiers temporaires (aucune base utilisateur).
"""
from __future__ import annotations

import gc
import sqlite3
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import db as db_module
from app.analysis.base import AnalysisParams
from app.analysis.motion import MotionAnalysisBackend, build_roi_mask, parse_roi, segment_motion_signal
from app.analysis.posture import compute_angles
from app.analysis.video import frame_timestamp_s, open_video_capture
from app.core.files import managed_file_path
from app.jobs import JobRegistry


# --------------------------------------------------------------------------- #
# Base SQLite
# --------------------------------------------------------------------------- #
@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DATABASE_PATH", tmp_path / "test.db")
    db_module._initialized_paths.clear()
    db_module.init_db()
    return tmp_path / "test.db"


def test_connection_is_closed_after_with_block(temp_db):
    with db_module.get_connection() as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_init_db_is_versioned_and_idempotent(temp_db):
    db_module.init_db()
    db_module.init_db(force=True)
    with db_module.get_connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    assert version == db_module.SCHEMA_VERSION
    assert "derniere_activite_le" in columns


def test_renamed_operation_is_not_resurrected(temp_db):
    with db_module.get_connection() as conn:
        conn.execute("INSERT INTO projects (nom, takt_s) VALUES ('P', 60)")
        conn.execute("INSERT INTO stations (project_id, nom) VALUES (1, 'S')")
        conn.execute(
            "INSERT INTO phases (station_id, ordre, debut_s, fin_s, type_auto, description) "
            "VALUES (1, 1, 0, 5, 'activity', 'Visser')"
        )
        conn.execute("INSERT INTO project_operations (project_id, nom) VALUES (1, 'Visser')")
        conn.execute("UPDATE project_operations SET nom = 'Vissage capot' WHERE nom = 'Visser'")
    db_module.init_db(force=True)  # simule un redémarrage / une requête suivante
    with db_module.get_connection() as conn:
        names = {row["nom"] for row in conn.execute("SELECT nom FROM project_operations")}
    assert names == {"Vissage capot"}


# --------------------------------------------------------------------------- #
# Fichiers gérés
# --------------------------------------------------------------------------- #
def test_managed_file_path_rejects_outside_root(tmp_path):
    root = tmp_path / "videos"
    root.mkdir()
    inside = root / "project_1" / "video.mp4"
    inside.parent.mkdir()
    inside.write_bytes(b"x")
    assert managed_file_path(str(inside), root) == inside.resolve()
    assert managed_file_path(str(tmp_path / "kaizen_studio.db"), root) is None
    assert managed_file_path(str(root / ".." / "secret.txt"), root) is None
    assert managed_file_path(str(root), root) is None


# --------------------------------------------------------------------------- #
# Vidéo synthétique : 2 s fixe, 3 s de mouvement, 3 s fixe (10 i/s)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def synthetic_video(tmp_path) -> Path:
    path = tmp_path / "synthetic.avi"
    fps, width, height = 10, 160, 120
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    rng = np.random.default_rng(0)
    still = np.full((height, width, 3), 90, dtype=np.uint8)
    for index in range(80):
        t = index / fps
        if 2.0 <= t < 5.0:
            frame = still.copy()
            x = int(10 + (t - 2.0) * 40)
            cv2.rectangle(frame, (x, 30), (x + 40, 90), (255, 255, 255), -1)
        else:
            frame = still.copy()
        frame = cv2.add(frame, rng.integers(0, 2, frame.shape, dtype=np.uint8))
        writer.write(frame)
    writer.release()
    return path


def test_frame_timestamps_follow_container(synthetic_video):
    capture = open_video_capture(synthetic_video)
    stamps = []
    for index in range(20):
        assert capture.grab()
        stamps.append(frame_timestamp_s(capture, index, 10.0))
    capture.release()
    assert stamps[0] == pytest.approx(0.0, abs=1e-6)
    assert stamps[10] == pytest.approx(1.0, abs=0.06)
    assert all(b > a for a, b in zip(stamps, stamps[1:]))


def test_motion_detects_activity_window(synthetic_video):
    params = AnalysisParams(fps=5, start=0.0, end=None, min_phase_seconds=0.5)
    phases = MotionAnalysisBackend().analyze(synthetic_video, params)
    activity = [phase for phase in phases if phase.type == "activity"]
    assert len(activity) == 1
    assert activity[0].start == pytest.approx(2.0, abs=0.5)
    assert activity[0].end == pytest.approx(5.0, abs=0.5)
    assert phases[0].start == pytest.approx(0.0)  # la 1re phase couvre le début de fenêtre


def test_motion_window_and_roi(synthetic_video):
    params = AnalysisParams(fps=5, start=1.0, end=6.0, roi="0.0,0.0,0.5,1.0", min_phase_seconds=0.5)
    phases = MotionAnalysisBackend().analyze(synthetic_video, params)
    assert phases[0].start == pytest.approx(1.0)
    assert phases[-1].end == pytest.approx(6.0, abs=0.25)


def test_short_phase_merge_never_leaves_adjacent_same_type():
    samples = []
    pattern = [0] * 10 + [5] * 10 + [0] * 1 + [5] * 10 + [0] * 10
    for index, value in enumerate(pattern):
        samples.append({"time_s": index * 0.2, "motion_pct": float(value)})
    phases = segment_motion_signal(samples, threshold_pct=1.0, min_duration=0.5)
    assert all(a.type != b.type for a, b in zip(phases, phases[1:]))
    assert [phase.type for phase in phases] == ["stop", "activity", "stop"]


def test_roi_mask_and_validation():
    mask = build_roi_mask((100, 200), parse_roi("[[0,0,0.5,0.5],[0.5,0.5,0.5,0.5]]"))
    assert mask is not None and mask.sum() == 2 * 50 * 100
    with pytest.raises(ValueError):
        parse_roi("0.8,0.8,0.5,0.5")
    with pytest.raises(ValueError):
        parse_roi("a,b,c,d")


# --------------------------------------------------------------------------- #
# Posture : angles corrigés du rapport d'aspect
# --------------------------------------------------------------------------- #
def _point(x, y):
    return {"x": x, "y": y, "visibility": 0.99}


@pytest.mark.parametrize("width,height", [(1920, 1080), (1080, 1920), (640, 480)])
def test_trunk_inclination_is_aspect_ratio_independent(width, height):
    length = 300.0
    angle = np.radians(20)
    hip = (width / 2, height * 0.7)
    shoulder = (hip[0] + np.sin(angle) * length, hip[1] - np.cos(angle) * length)
    points = {
        "left_hip": _point(hip[0] / width, hip[1] / height),
        "right_hip": _point(hip[0] / width, hip[1] / height),
        "left_shoulder": _point(shoulder[0] / width, shoulder[1] / height),
        "right_shoulder": _point(shoulder[0] / width, shoulder[1] / height),
    }
    angles = compute_angles(points, width, height)
    assert angles["trunk_inclination"] == pytest.approx(20.0, abs=0.2)


def test_elbow_right_angle_in_landscape():
    width, height = 1920, 1080
    shoulder, elbow, wrist = (900, 300), (900, 500), (1100, 500)
    points = {
        "left_shoulder": _point(shoulder[0] / width, shoulder[1] / height),
        "left_elbow": _point(elbow[0] / width, elbow[1] / height),
        "left_wrist": _point(wrist[0] / width, wrist[1] / height),
    }
    assert compute_angles(points, width, height)["left_elbow"] == pytest.approx(90.0, abs=0.2)


# --------------------------------------------------------------------------- #
# Registre de tâches
# --------------------------------------------------------------------------- #
def test_job_registry_blocks_concurrent_jobs_and_releases_payload():
    registry = JobRegistry()
    job_id = registry.create(1, "motion", motion_samples=[])
    with pytest.raises(RuntimeError):
        registry.create(1, "posture")
    registry.set_progress(job_id, 0.5)
    registry.set_progress(job_id, 0.2)  # la progression ne recule jamais
    assert registry.get(job_id)["progress"] == 50
    registry.update(job_id, status="completed", progress=100, motion_samples=[{"time_s": 0}])
    assert registry.get(job_id, release_heavy=True)["motion_samples"]
    assert registry.get(job_id)["motion_samples"] == []
    assert not registry.has_active(1)
    gc.collect()
