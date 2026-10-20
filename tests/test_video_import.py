from __future__ import annotations

from io import BytesIO
from pathlib import Path

import cv2
import numpy as np

import app.db as database
import app.main as main_module


def synthetic_avi_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "synthetic_import_test.avi"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (64, 48),
    )
    if not writer.isOpened():
        raise RuntimeError("Impossible de créer la vidéo de test.")
    for index in range(20):
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        cv2.rectangle(image, (index, 10), (index + 12, 35), (255, 255, 255), -1)
        writer.write(image)
    writer.release()
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def make_project(client) -> int:
    response = client.post("/api/projects", json={"nom": "Import vidéo", "takt_s": 60})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_import_video_creates_station_and_extracts_metadata(client, tmp_path):
    project_id = make_project(client)
    video_bytes = synthetic_avi_bytes(tmp_path)

    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste montage"},
        files={"video": ("poste.avi", BytesIO(video_bytes), "video/x-msvideo")},
    )

    assert response.status_code == 201, response.text
    station = response.json()
    assert station["nom"] == "Poste montage"
    assert station["video_fps"] == 10.0
    assert station["video_duration_s"] == 2.0
    saved_path = Path(station["video_path"])
    assert saved_path.exists()
    assert saved_path.parent.name == f"station_{station['id']}"

    video_response = client.get(f"/api/stations/{station['id']}/video")
    assert video_response.status_code == 200
    assert video_response.headers["content-type"].startswith("video/x-msvideo")
    assert video_response.content == video_bytes


def test_streamed_video_import_saves_video_without_multipart(client, tmp_path):
    project_id = make_project(client)
    video_bytes = synthetic_avi_bytes(tmp_path)

    response = client.post(
        f"/api/projects/{project_id}/stations/import-stream",
        params={"nom": "Poste flux", "filename": "poste.avi"},
        content=video_bytes,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 201, response.text
    station = response.json()
    assert station["video_fps"] == 10.0
    assert station["video_duration_s"] == 2.0
    assert Path(station["video_path"]).read_bytes() == video_bytes


def test_streamed_video_import_rejects_oversized_content_length(client):
    project_id = make_project(client)
    assert client.post("/api/settings", json={"video_max_mb": "1"}).status_code == 200
    response = client.post(
        f"/api/projects/{project_id}/stations/import-stream",
        params={"nom": "Poste trop grand", "filename": "poste.avi"},
        content=b"x",
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(2 * 1024 * 1024),
        },
    )
    assert response.status_code == 413


def test_local_frame_preview_and_roi_settings(client, tmp_path):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste ROI"},
        files={
            "video": (
                "poste.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station_id = response.json()["id"]

    frame = client.get(f"/api/stations/{station_id}/frame?time_s=0.5")
    assert frame.status_code == 200, frame.text
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.content.startswith(b"\xff\xd8")

    saved = client.put(
        f"/api/stations/{station_id}/analysis-settings",
        json={"roi": "0.1,0.2,0.5,0.6", "fenetre_debut": 0.2, "fenetre_fin": 1.8},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["roi"] == "0.1,0.2,0.5,0.6"
    assert saved.json()["fenetre_debut"] == 0.2
    assert saved.json()["fenetre_fin"] == 1.8

    multiple = client.put(
        f"/api/stations/{station_id}/analysis-settings",
        json={
            "roi": "[[0.1,0.2,0.3,0.4],[0.6,0.1,0.2,0.5]]",
            "fenetre_debut": 0.2,
            "fenetre_fin": 1.8,
        },
    )
    assert multiple.status_code == 200, multiple.text
    assert multiple.json()["roi"] == "[[0.1,0.2,0.3,0.4],[0.6,0.1,0.2,0.5]]"


def test_delete_station_removes_imported_video_and_phases(client, tmp_path):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste à supprimer"},
        files={
            "video": (
                "poste.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    station = response.json()
    video_path = Path(station["video_path"])
    phase = client.post(
        f"/api/stations/{station['id']}/phases",
        json={"ordre": 1, "debut_s": 0, "fin_s": 1, "type_auto": "activity"},
    )
    assert phase.status_code == 201, phase.text
    project_export = main_module.EXPORT_ROOT / f"kaizen_studio_projet_{project_id}.xlsx"
    project_export.parent.mkdir(parents=True, exist_ok=True)
    project_export.write_bytes(b"export de test")

    deleted = client.delete(f"/api/stations/{station['id']}")
    assert deleted.status_code == 200, deleted.text
    assert not video_path.exists()
    assert not project_export.exists()
    assert client.get(f"/api/stations/{station['id']}").status_code == 404


def test_delete_project_removes_all_managed_videos_and_data(client, tmp_path):
    project_id = make_project(client)
    video_paths = []
    station_ids = []
    for name in ("Poste 1", "Poste 2"):
        response = client.post(
            f"/api/projects/{project_id}/stations/import",
            data={"nom": name},
            files={
                "video": (
                    f"{name}.avi",
                    BytesIO(synthetic_avi_bytes(tmp_path)),
                    "video/x-msvideo",
                )
            },
        )
        assert response.status_code == 201, response.text
        station = response.json()
        station_ids.append(station["id"])
        video_paths.append(Path(station["video_path"]))
        phase = client.post(
            f"/api/stations/{station['id']}/phases",
            json={"ordre": 1, "debut_s": 0, "fin_s": 1, "type_auto": "activity"},
        )
        assert phase.status_code == 201, phase.text

    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200, deleted.text
    assert all(not video_path.exists() for video_path in video_paths)
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert all(client.get(f"/api/stations/{station_id}").status_code == 404 for station_id in station_ids)


def test_retention_purge_removes_expired_project_and_local_video(client, tmp_path):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste expiré"},
        files={
            "video": (
                "poste.avi",
                BytesIO(synthetic_avi_bytes(tmp_path)),
                "video/x-msvideo",
            )
        },
    )
    assert response.status_code == 201, response.text
    video_path = Path(response.json()["video_path"])

    with database.get_connection() as conn:
        conn.execute(
            "UPDATE projects SET cree_le = datetime('now', '-2 days'), "
            "derniere_activite_le = datetime('now', '-2 days') WHERE id = ?",
            (project_id,),
        )
    saved = client.post("/api/settings", json={"purge_days": "1"})
    assert saved.status_code == 200, saved.text

    purged = client.post("/api/maintenance/purge")
    assert purged.status_code == 200, purged.text
    assert purged.json()["projects_deleted"] == 1
    assert purged.json()["videos_deleted"] == 1
    assert purged.json()["external_files_preserved"] == 0
    assert not video_path.exists()
    assert client.get(f"/api/projects/{project_id}").status_code == 404


def test_video_import_rejects_unsupported_extension(client):
    project_id = make_project(client)
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste"},
        files={"video": ("poste.mkv", BytesIO(b"video"), "video/x-matroska")},
    )
    assert response.status_code == 400


def test_video_import_enforces_configured_size_limit(client):
    project_id = make_project(client)
    assert client.post("/api/settings", json={"video_max_mb": "1"}).status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["video_max_mb"] == "1"
    response = client.post(
        f"/api/projects/{project_id}/stations/import",
        data={"nom": "Poste"},
        files={"video": ("poste.avi", BytesIO(b"x" * (1024 * 1024 + 1)), "video/x-msvideo")},
    )
    assert response.status_code == 413
    assert "Taille maximale" in response.json()["detail"]


def test_video_max_setting_rejects_unsafe_or_invalid_values(client):
    invalid_values = ("0", "20481", "not-a-number")
    for value in invalid_values:
        response = client.post("/api/settings", json={"video_max_mb": value})
        assert response.status_code == 422


def test_video_max_setting_accepts_six_gib(client):
    response = client.post("/api/settings", json={"video_max_mb": "6144"})
    assert response.status_code == 200, response.text
    assert client.get("/api/settings").json()["video_max_mb"] == "6144"
