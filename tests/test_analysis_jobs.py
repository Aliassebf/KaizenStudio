from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

from tests.test_video_import import make_project, synthetic_avi_bytes


def test_motion_analysis_job_persists_phases(client, tmp_path):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste analysé"},
        files={
            "video": (
                "mouvement.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station = response.json()

    submitted = client.post(
        f"/api/stations/{station['id']}/analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 2, "duree_min_s": 0.1},
    )
    assert submitted.status_code == 202, submitted.text
    job_url = submitted.json()["poll_url"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(job_url).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert job["motion_samples"]
    assert all("time_s" in sample and "motion_pct" in sample for sample in job["motion_samples"])
    assert job["threshold_pct"] >= 0.2

    phases = client.get(f"/api/stations/{station['id']}/phases").json()
    assert job["phase_count"] == len(phases)
    assert phases
    assert all(phase["categorie"] == "Non classé" for phase in phases)
    assert all(phase["fin_s"] > phase["debut_s"] for phase in phases)
    persisted_station = client.get(f"/api/stations/{station['id']}").json()
    assert persisted_station["motion_signal_json"]
    assert persisted_station["motion_threshold_pct"] == job["threshold_pct"]

    recalculated = client.post(
        f"/api/stations/{station['id']}/resegment",
        json={"seuil_pct": 100, "duree_min_s": 0.1},
    )
    assert recalculated.status_code == 200, recalculated.text
    assert len(recalculated.json()) == 1
    assert recalculated.json()[0]["type_auto"] == "stop"
    assert client.get(f"/api/stations/{station['id']}").json()["motion_signal_json"] == persisted_station["motion_signal_json"]


def test_motion_analysis_rejects_window_beyond_video_duration(client, tmp_path):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste fenêtre mouvement"},
        files={
            "video": (
                "motion-window.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station = response.json()

    too_late = client.post(
        f"/api/stations/{station['id']}/analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 2.2},
    )

    assert too_late.status_code == 422
    assert too_late.json()["detail"] == "La fenêtre de fin dépasse la durée de la vidéo."


def test_analysis_requires_an_imported_video(client):
    project = client.post("/api/projects", json={"nom": "Sans vidéo", "takt_s": 30}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste vide"},
    ).json()
    response = client.post(f"/api/stations/{station['id']}/analysis", json={})
    assert response.status_code == 400


def test_posture_analysis_job_persists_local_samples(client, tmp_path, monkeypatch):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste posture"},
        files={
            "video": (
                "posture.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station = response.json()
    sample = {
        "time_s": 0.0,
        "points": {"left_shoulder": {"x": 0.4, "y": 0.2, "visibility": 0.9}},
        "angles": {"trunk_inclination": 10.0},
    }

    def fake_posture_analysis(_video_path, _start, _end, _fps, progress_callback):
        progress_callback(1.0)
        return [sample]

    monkeypatch.setattr("app.main.analyze_posture_video", fake_posture_analysis)
    submitted = client.post(
        f"/api/stations/{station['id']}/posture-analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 2},
    )
    assert submitted.status_code == 202, submitted.text

    job_url = submitted.json()["poll_url"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(job_url).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    assert job["kind"] == "posture"
    assert job["posture_samples"] == [sample]
    assert client.get(f"/api/stations/{station['id']}").json()["posture_signal_json"]


def test_posture_analysis_requires_an_imported_video(client):
    project = client.post("/api/projects", json={"nom": "Sans vidéo", "takt_s": 30}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste vide"},
    ).json()
    response = client.post(
        f"/api/stations/{station['id']}/posture-analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 1},
    )
    assert response.status_code == 400


def test_posture_analysis_clamps_one_frame_rounding_and_rejects_larger_overflow(
    client,
    tmp_path,
    monkeypatch,
):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste fenêtre vidéo"},
        files={
            "video": (
                "window.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station = response.json()
    analyzed_ranges = []

    def fake_posture_analysis(_video_path, start, end, _fps, progress_callback):
        analyzed_ranges.append((start, end))
        progress_callback(1.0)
        return [{"time_s": start, "points": {}, "angles": {}}]

    monkeypatch.setattr("app.main.analyze_posture_video", fake_posture_analysis)
    rounded_end = client.post(
        f"/api/stations/{station['id']}/posture-analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 2.05},
    )
    assert rounded_end.status_code == 202, rounded_end.text

    job_url = rounded_end.json()["poll_url"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(job_url).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    assert analyzed_ranges == [(0, 2.0)]

    too_late = client.post(
        f"/api/stations/{station['id']}/posture-analysis",
        json={"fenetre_debut": 0, "fenetre_fin": 2.2},
    )
    assert too_late.status_code == 422
    assert too_late.json()["detail"] == "La fenêtre de fin dépasse la durée de la vidéo."
