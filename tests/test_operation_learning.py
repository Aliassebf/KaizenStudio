from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import app.main as main_module
from app.analysis.operation_learning import OperationSample, load_operation_model, predict_operation, train_operation_model


def _write_operation_video(path: Path, operations: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (128, 128),
    )
    assert writer.isOpened(), "OpenCV ne peut pas créer la vidéo de test."
    for operation in operations:
        for _ in range(10):
            frame = np.zeros((128, 128, 3), dtype=np.uint8)
            if operation == 1:
                cv2.circle(frame, (64, 64), 28, (255, 255, 255), -1)
            else:
                cv2.rectangle(frame, (36, 36), (92, 92), (255, 255, 255), -1)
            writer.write(frame)
    writer.release()


def test_local_classifier_trains_on_train_videos_and_evaluates_held_out_video(tmp_path):
    training_video = tmp_path / "training.avi"
    validation_video = tmp_path / "validation.avi"
    _write_operation_video(training_video, [1, 2, 1, 2])
    _write_operation_video(validation_video, [1, 2])

    train_samples = [
        OperationSample(1, str(training_video), None, 0, 1, 11, "Prendre une pièce"),
        OperationSample(1, str(training_video), None, 1, 2, 12, "Visser"),
        OperationSample(1, str(training_video), None, 2, 3, 11, "Prendre une pièce"),
        OperationSample(1, str(training_video), None, 3, 4, 12, "Visser"),
    ]
    validation_samples = [
        OperationSample(2, str(validation_video), None, 0, 1, 11, "Prendre une pièce"),
        OperationSample(2, str(validation_video), None, 1, 2, 12, "Visser"),
    ]
    model_path = tmp_path / "models" / "project_1_operations.yml"
    metadata_path = tmp_path / "models" / "project_1_operations.json"
    result = train_operation_model(
        1,
        train_samples,
        validation_samples,
        model_path,
        metadata_path,
        "test-signature",
    )

    assert result["validation"]["examples"] == 2
    assert result["validation"]["accuracy_pct"] == 100.0
    assert model_path.is_file()
    assert metadata_path.is_file()

    model, metadata = load_operation_model(model_path, metadata_path)
    first = predict_operation(model, metadata, str(validation_video), 0, 1, None)
    second = predict_operation(model, metadata, str(validation_video), 1, 2, None)
    assert first["operation_id"] == 11
    assert second["operation_id"] == 12
    assert first["accepted"] is True
    assert second["accepted"] is True
    assert 0 <= first["confidence"] <= 1


def test_same_video_cannot_be_assigned_to_training_and_validation(client, tmp_path):
    project = client.post("/api/projects", json={"nom": "Séparation vidéo", "takt_s": 60}).json()
    video_path = str(tmp_path / "shared.avi")
    stations = [
        client.post(
            f"/api/projects/{project['id']}/stations",
            json={"nom": name, "video_path": video_path},
        ).json()
        for name in ("Copie train", "Copie validation")
    ]
    training = client.put(
        f"/api/stations/{stations[0]['id']}/dataset-split",
        json={"split": "train"},
    )
    assert training.status_code == 200, training.text

    validation = client.put(
        f"/api/stations/{stations[1]['id']}/dataset-split",
        json={"split": "validation"},
    )
    assert validation.status_code == 409
    assert "par vidéo entière" in validation.json()["detail"]


def test_operation_model_api_keeps_suggestions_explicit_and_removes_model_on_project_delete(
    client,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(main_module, "MODEL_ROOT", tmp_path / "models")
    project = client.post("/api/projects", json={"nom": "Apprentissage local", "takt_s": 60}).json()
    project_id = project["id"]
    operations = [
        client.post(
            f"/api/projects/{project_id}/operations",
            json={"nom": name},
        ).json()
        for name in ("Prendre une pièce", "Visser")
    ]
    video_paths = [tmp_path / f"{name}.avi" for name in ("train", "validation", "suggestions")]
    _write_operation_video(video_paths[0], [1, 2, 1, 2])
    _write_operation_video(video_paths[1], [1, 2])
    _write_operation_video(video_paths[2], [1])
    stations = []
    for name, video_path in zip(("Entraînement", "Validation", "À vérifier"), video_paths):
        station = client.post(
            f"/api/projects/{project_id}/stations",
            json={"nom": name, "video_path": str(video_path)},
        )
        assert station.status_code == 201, station.text
        stations.append(station.json())

    for station, split in zip(stations, ("train", "validation", "excluded")):
        response = client.put(
            f"/api/stations/{station['id']}/dataset-split",
            json={"split": split},
        )
        assert response.status_code == 200, response.text

    for station, intervals in zip(
        stations[:2],
        (
            ((0, 1, 0), (1, 2, 1), (2, 3, 0), (3, 4, 1)),
            ((0, 1, 0), (1, 2, 1)),
        ),
    ):
        for start, end, operation_index in intervals:
            response = client.post(
                f"/api/stations/{station['id']}/annotations",
                json={
                    "operation_id": operations[operation_index]["id"],
                    "debut_s": start,
                    "fin_s": end,
                },
            )
            assert response.status_code == 201, response.text

    phase = client.post(
        f"/api/stations/{stations[2]['id']}/phases",
        json={
            "ordre": 1,
            "debut_s": 0,
            "fin_s": 1,
            "type_auto": "activity",
            "categorie": "Non classé",
        },
    )
    assert phase.status_code == 201, phase.text

    trained = client.post(f"/api/projects/{project_id}/operation-model/train")
    assert trained.status_code == 200, trained.text
    assert trained.json()["validation"]["accuracy_pct"] == 100.0
    assert client.get(f"/api/projects/{project_id}/operation-model").json()["model_status"] == "trained"
    training_video_suggestion = client.post(
        f"/api/stations/{stations[0]['id']}/operation-suggestions",
    )
    assert training_video_suggestion.status_code == 409
    training_annotation = client.get(f"/api/stations/{stations[0]['id']}/annotations").json()[0]
    updated = client.patch(
        f"/api/stations/{stations[0]['id']}/annotations/{training_annotation['id']}",
        json={"fin_s": 0.9},
    )
    assert updated.status_code == 200, updated.text
    assert client.get(f"/api/projects/{project_id}/operation-model").json()["model_status"] == "not_trained"
    trained = client.post(f"/api/projects/{project_id}/operation-model/train")
    assert trained.status_code == 200, trained.text

    suggestion_response = client.post(
        f"/api/stations/{stations[2]['id']}/operation-suggestions",
    )
    assert suggestion_response.status_code == 200, suggestion_response.text
    suggestions = suggestion_response.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["operation_id"] in {operation["id"] for operation in operations}
    assert suggestions[0]["accepted"] is True
    assert client.get(f"/api/stations/{stations[2]['id']}/annotations").json() == []

    accepted = client.post(
        f"/api/stations/{stations[2]['id']}/annotations",
        json={
            "operation_id": suggestions[0]["operation_id"],
            "debut_s": suggestions[0]["debut_s"],
            "fin_s": suggestions[0]["fin_s"],
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert client.get(f"/api/projects/{project_id}/operation-model").json()["model_status"] == "trained"

    model_path = tmp_path / "models" / f"project_{project_id}_operations.yml"
    metadata_path = tmp_path / "models" / f"project_{project_id}_operations.json"
    assert model_path.is_file() and metadata_path.is_file()
    deleted = client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200, deleted.text
    assert not model_path.exists() and not metadata_path.exists()
