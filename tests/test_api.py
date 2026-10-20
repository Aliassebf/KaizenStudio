from __future__ import annotations

def test_project_and_station_lifecycle(client):
    response = client.post("/api/projects", json={"nom": "Poste A", "takt_s": 60})
    assert response.status_code == 201, response.text
    project = response.json()
    project_id = project["id"]

    station = client.post(f"/api/projects/{project_id}/stations", json={"nom": "Station 1", "video_path": "C:/tmp/video.mp4"})
    assert station.status_code == 201, station.text
    station_id = station.json()["id"]

    phase = client.post(
        f"/api/stations/{station_id}/phases",
        json={
            "ordre": 1,
            "debut_s": 0.0,
            "fin_s": 5.0,
            "type_auto": "activity",
            "description": "Poser la pièce",
            "categorie": "VA",
            "commentaire": "Estimation initiale",
            "chrono_reel_s": 4.8,
            "mouvement_moyen_pct": 42.0,
        },
    )
    assert phase.status_code == 201, phase.text

    summary = client.get(f"/api/projects/{project_id}/summary")
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["project"]["nom"] == "Poste A"
    assert len(payload["stations"]) == 1
    assert payload["stations"][0]["VA"] == 5.0
    assert payload["stations"][0]["comparaison_chrono"][0]["erreur_absolue_pct"] == 4.17
    assert payload["stations"][0]["comparaison_chrono"][0]["type_auto"] == "activity"
    assert payload["comparaison_chrono"]["phases_chronometrees"] == 1
    assert payload["comparaison_chrono"]["erreur_absolue_moyenne_pct"] == 4.17


def test_station_analysis_configuration_is_saved_per_section(client):
    project = client.post("/api/projects", json={"nom": "Réglages", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste réglages"},
    ).json()
    other_station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Autre poste"},
    ).json()
    station_id = station["id"]

    review = client.put(
        f"/api/stations/{station_id}/analysis-configuration",
        json={
            "section": "review",
            "values": {
                "threshold_pct": 12.5,
                "min_phase_seconds": 1.8,
                "window_start": 2.0,
                "window_end": 45.0,
            },
        },
    )
    assert review.status_code == 200, review.text

    cycles = client.put(
        f"/api/stations/{station_id}/analysis-configuration",
        json={
            "section": "cycles",
            "values": {"minimum_stop": 3.0, "minimum_cycle": 8.0},
        },
    )
    assert cycles.status_code == 200, cycles.text

    saved = client.get(f"/api/stations/{station_id}")
    assert saved.status_code == 200, saved.text
    assert saved.json()["analysis_configuration"] == {
        "review": {
            "threshold_pct": 12.5,
            "min_phase_seconds": 1.8,
            "window_start": 2.0,
            "window_end": 45.0,
        },
        "cycles": {"minimum_stop": 3.0, "minimum_cycle": 8.0},
    }
    assert client.get(f"/api/stations/{other_station['id']}").json()["analysis_configuration"] == {}

    invalid = client.put(
        f"/api/stations/{station_id}/analysis-configuration",
        json={"section": "review", "values": {"unknown_setting": "bad"}},
    )
    assert invalid.status_code == 422
    out_of_range = client.put(
        f"/api/stations/{station_id}/analysis-configuration",
        json={"section": "review", "values": {"threshold_pct": 120}},
    )
    assert out_of_range.status_code == 422
    confirmation = client.put(
        f"/api/stations/{station_id}/analysis-configuration",
        json={
            "section": "ergonomics",
            "values": {"official_method_confirmed": "on"},
        },
    )
    assert confirmation.status_code == 422


def test_station_cycles_can_be_saved_suggested_and_compared_in_summary(client):
    project = client.post("/api/projects", json={"nom": "Cycles", "takt_s": 30}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste répétitif"},
    ).json()
    phase_data = [
        (0, 8, "activity"),
        (8, 11, "stop"),
        (11, 21, "activity"),
        (21, 24, "stop"),
        (24, 32, "activity"),
    ]
    for order, (start, end, phase_type) in enumerate(phase_data, start=1):
        response = client.post(
            f"/api/stations/{station['id']}/phases",
            json={
                "ordre": order,
                "debut_s": start,
                "fin_s": end,
                "type_auto": phase_type,
            },
        )
        assert response.status_code == 201, response.text

    candidates = client.get(f"/api/stations/{station['id']}/cycle-candidates")
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["candidates"] == [
        {"debut_s": 0.0, "fin_s": 8.0},
        {"debut_s": 11.0, "fin_s": 21.0},
        {"debut_s": 24.0, "fin_s": 32.0},
    ]
    assert "Vérifiez-les" in candidates.json()["warning"]

    saved_cycles = []
    for candidate in candidates.json()["candidates"]:
        response = client.post(
            f"/api/stations/{station['id']}/cycles",
            json={**candidate, "source": "auto"},
        )
        assert response.status_code == 201, response.text
        saved_cycles.append(response.json())

    overlap = client.post(
        f"/api/stations/{station['id']}/cycles",
        json={"debut_s": 7, "fin_s": 9},
    )
    assert overlap.status_code == 409
    assert client.get(f"/api/stations/{station['id']}/cycles").json() == saved_cycles

    summary = client.get(f"/api/projects/{project['id']}/summary")
    cycle_summary = summary.json()["stations"][0]
    assert cycle_summary["statistiques_cycles"] == {
        "nombre": 3,
        "moyenne_s": 8.67,
        "mediane_s": 8.0,
        "minimum_s": 8.0,
        "maximum_s": 10.0,
        "ecart_type_s": 0.94,
        "coefficient_variation_pct": 10.88,
    }
    assert [cycle["duree_s"] for cycle in cycle_summary["cycles"]] == [8.0, 10.0, 8.0]
    assert client.delete(f"/api/stations/{station['id']}/cycles/{saved_cycles[0]['id']}").status_code == 200


def test_project_takt_can_be_updated_and_is_used_in_summary(client):
    project = client.post("/api/projects", json={"nom": "Takt modifiable", "takt_s": 60}).json()

    updated = client.patch(
        f"/api/projects/{project['id']}",
        json={"takt_s": 42.5},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["takt_s"] == 42.5
    summary = client.get(f"/api/projects/{project['id']}/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["project"]["takt_s"] == 42.5


def test_project_takt_update_requires_positive_value_and_existing_project(client):
    project = client.post("/api/projects", json={"nom": "Takt invalide", "takt_s": 60}).json()

    invalid = client.patch(f"/api/projects/{project['id']}", json={"takt_s": 0})
    missing = client.patch("/api/projects/999999", json={"takt_s": 30})

    assert invalid.status_code == 422
    assert missing.status_code == 404


def test_project_export_filename_uses_sanitized_project_name(client):
    project = client.post(
        "/api/projects",
        json={"nom": "Montage EIC NEXGEN", "takt_s": 60},
    ).json()

    response = client.get(f"/api/projects/{project['id']}/export.xlsx")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        "attachment; filename*=utf-8''kaizen_studio_Montage%20EIC%20NEXGEN.xlsx"
    )

    unsafe_project = client.post(
        "/api/projects",
        json={"nom": "Projet/ligne:1", "takt_s": 60},
    ).json()
    unsafe_export = client.get(f"/api/projects/{unsafe_project['id']}/export.xlsx")

    assert unsafe_export.status_code == 200
    assert unsafe_export.headers["content-disposition"] == (
        'attachment; filename="kaizen_studio_Projet_ligne_1.xlsx"'
    )


def test_project_operation_catalog_groups_manual_names_and_ignores_generated_labels(client):
    project = client.post("/api/projects", json={"nom": "Opérations", "takt_s": 60}).json()
    first_station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste 1"},
    ).json()
    second_station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste 2"},
    ).json()

    for station_id, description in (
        (first_station["id"], "Visser le capot"),
        (first_station["id"], "visser le capot"),
        (first_station["id"], "Activité détectée — à décrire"),
        (second_station["id"], "Contrôler la pièce"),
    ):
        response = client.post(
            f"/api/stations/{station_id}/phases",
            json={
                "ordre": 1,
                "debut_s": 0,
                "fin_s": 2,
                "type_auto": "activity",
                "description": description,
            },
        )
        assert response.status_code == 201, response.text

    response = client.get(f"/api/projects/{project['id']}/operations")
    assert response.status_code == 200, response.text
    assert [
        {"nom": row["nom"], "occurrences": row["occurrences"], "annotations": row["annotations"]}
        for row in response.json()
    ] == [
        {"nom": "Contrôler la pièce", "occurrences": 1, "annotations": 0},
        {"nom": "Visser le capot", "occurrences": 2, "annotations": 0},
    ]

    missing = client.get("/api/projects/999999/operations")
    assert missing.status_code == 404


def test_project_operation_annotations_and_video_level_dataset_split(client):
    project = client.post("/api/projects", json={"nom": "Jeu d'opérations", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Vidéo train"},
    ).json()
    operation = client.post(
        f"/api/projects/{project['id']}/operations",
        json={"nom": "Visser le capot"},
    )
    assert operation.status_code == 201, operation.text
    operation_id = operation.json()["id"]

    first = client.post(
        f"/api/stations/{station['id']}/annotations",
        json={"operation_id": operation_id, "debut_s": 1.05, "fin_s": 2.95},
    )
    assert first.status_code == 201, first.text
    assert first.json()["debut_s"] == 1.1
    assert first.json()["fin_s"] == 3.0

    touching = client.post(
        f"/api/stations/{station['id']}/annotations",
        json={"operation_id": None, "debut_s": 3, "fin_s": 4},
    )
    assert touching.status_code == 201, touching.text
    overlap = client.post(
        f"/api/stations/{station['id']}/annotations",
        json={"operation_id": operation_id, "debut_s": 2.9, "fin_s": 3.5},
    )
    assert overlap.status_code == 409

    renamed = client.patch(
        f"/api/projects/{project['id']}/operations/{operation_id}",
        json={"nom": "Visser les vis"},
    )
    assert renamed.status_code == 200, renamed.text
    assert client.get(f"/api/stations/{station['id']}/annotations").json()[0]["operation"] == "Visser les vis"

    split = client.put(
        f"/api/stations/{station['id']}/dataset-split",
        json={"split": "validation"},
    )
    assert split.status_code == 200, split.text
    assert split.json()["split"] == "validation"
    assert client.get(f"/api/stations/{station['id']}").json()["dataset_split"] == "validation"

    dataset = client.get(f"/api/projects/{project['id']}/annotation-dataset")
    assert dataset.status_code == 200, dataset.text
    assert dataset.json()["model_status"] == "not_trained"
    assert dataset.json()["splits"]["validation"] == {"videos": 1, "annotations": 2}
    assert dataset.json()["operations"][0]["validation"] == 1

    manifest = client.get(f"/api/projects/{project['id']}/annotation-manifest")
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["format"] == "kaizen-studio-annotations-v1"
    assert manifest.json()["videos"][0]["dataset_split"] == "validation"
    assert len(manifest.json()["videos"][0]["annotations"]) == 2

    wrong_project_operation = client.post(
        f"/api/stations/{station['id']}/annotations",
        json={"operation_id": 999999, "debut_s": 5, "fin_s": 6},
    )
    assert wrong_project_operation.status_code == 422


def test_phase_type_can_be_corrected_and_persisted(client):
    project = client.post("/api/projects", json={"nom": "Correction phase", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste"},
    ).json()
    phase = client.post(
        f"/api/stations/{station['id']}/phases",
        json={"ordre": 1, "debut_s": 0, "fin_s": 4, "type_auto": "stop"},
    ).json()

    corrected = client.patch(
        f"/api/stations/{station['id']}/phases/{phase['id']}",
        json={"type_auto": "activity"},
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["type_auto"] == "activity"
    persisted = client.get(f"/api/stations/{station['id']}").json()
    assert persisted["phases"][0]["type_auto"] == "activity"


def test_ergonomic_assessments_are_manual_persisted_and_summarized_on_dashboard(client):
    project = client.post("/api/projects", json={"nom": "Cotation ergonomique", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste évalué"},
    ).json()
    phase = client.post(
        f"/api/stations/{station['id']}/phases",
        json={
            "ordre": 1,
            "debut_s": 0,
            "fin_s": 8,
            "type_auto": "activity",
            "description": "Assembler",
        },
    )
    assert phase.status_code == 201, phase.text

    missing_score = client.post(
        f"/api/stations/{station['id']}/ergonomic-assessments",
        json={
            "time_s": 3.5,
            "evaluator": "Évaluateur",
            "factors_notes": "Charge 3 kg, prise correcte, posture répétée.",
            "official_method_confirmed": True,
        },
    )
    assert missing_score.status_code == 422

    unconfirmed = client.post(
        f"/api/stations/{station['id']}/ergonomic-assessments",
        json={
            "time_s": 3.5,
            "rula_score": 5,
            "evaluator": "Évaluateur",
            "factors_notes": "Charge 3 kg, prise correcte, posture répétée.",
            "official_method_confirmed": False,
        },
    )
    assert unconfirmed.status_code == 422

    saved = client.post(
        f"/api/stations/{station['id']}/ergonomic-assessments",
        json={
            "time_s": 3.5,
            "rula_score": 5,
            "reba_score": 8,
            "evaluator": "Évaluateur",
            "factors_notes": "Charge 3 kg, prise correcte, posture répétée.",
            "official_method_confirmed": True,
        },
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["rula_level"] == "Action à court terme"
    assert saved.json()["reba_level"] == "Élevé"

    station_payload = client.get(f"/api/stations/{station['id']}").json()
    assert len(station_payload["ergonomic_assessments"]) == 1
    assert station_payload["ergonomic_assessments"][0]["reba_level"] == "Élevé"
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["project_count"] == 1
    assert payload["station_count"] == 1
    assert payload["assessment_count"] == 1
    dashboard_station = payload["projects"][0]["stations"][0]
    assert dashboard_station["latest_rula_score"] == 5
    assert dashboard_station["latest_rula_level"] == "Action à court terme"
    assert dashboard_station["latest_reba_score"] == 8
    assert dashboard_station["latest_reba_level"] == "Élevé"
    project_summary = client.get(f"/api/projects/{project['id']}/summary")
    assert project_summary.status_code == 200, project_summary.text
    summary_station = project_summary.json()["stations"][0]
    assert summary_station["latest_rula_score"] == 5
    assert summary_station["latest_rula_level"] == "Action à court terme"
    assert summary_station["latest_reba_score"] == 8
    assert summary_station["latest_reba_level"] == "Élevé"


def test_chrono_average_ignores_missing_or_zero_measurements(client):
    project = client.post("/api/projects", json={"nom": "Comparaison chrono", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste chrono"},
    ).json()

    for order, actual in ((1, 8.0), (2, None), (3, 0.0)):
        response = client.post(
            f"/api/stations/{station['id']}/phases",
            json={
                "ordre": order,
                "debut_s": (order - 1) * 10.0,
                "fin_s": (order - 1) * 10.0 + 10.0,
                "type_auto": "activity",
                "categorie": "VA",
                "chrono_reel_s": actual,
            },
        )
        assert response.status_code == 201, response.text

    summary = client.get(f"/api/projects/{project['id']}/summary").json()
    station_summary = summary["stations"][0]
    assert station_summary["comparaison_chrono"][0]["erreur_absolue_pct"] == 25.0
    assert station_summary["comparaison_chrono"][1]["erreur_absolue_pct"] is None
    assert station_summary["comparaison_chrono"][2]["erreur_absolue_pct"] is None
    assert summary["comparaison_chrono"]["phases_chronometrees"] == 1
    assert summary["comparaison_chrono"]["erreur_absolue_moyenne_pct"] == 25.0


def test_default_settings_are_local_and_constrained(client):
    settings = client.get("/api/settings")
    assert settings.status_code == 200, settings.text
    assert settings.json()["allow_outbound_network"] == "false"
    assert settings.json()["purge_days"] == "90"

    for invalid_days in ("0", "-1", "3651", "invalid"):
        response = client.post("/api/settings", json={"purge_days": invalid_days})
        assert response.status_code == 422


def test_health_exposes_local_only_mode(client, monkeypatch):
    monkeypatch.delenv("KAIZEN_STUDIO_HOST", raising=False)
    monkeypatch.delenv("KAIZEN_STUDIO_SSL_CERTFILE", raising=False)
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["local_only"] is True
    assert payload["network_default"] is False
    assert payload["transport_warning"] is None

    monkeypatch.setenv("KAIZEN_STUDIO_HOST", "192.168.1.20")
    monkeypatch.delenv("KAIZEN_STUDIO_SSL_CERTFILE", raising=False)
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["local_only"] is False
    assert "HTTP non chiffré" in payload["transport_warning"]


def test_phase_adjust_split_and_merge_are_persisted(client):
    project = client.post("/api/projects", json={"nom": "Édition des phases", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste édition"},
    ).json()
    phase_ids = []
    for order, (start, end) in enumerate(((0.0, 3.0), (3.0, 6.0)), start=1):
        response = client.post(
            f"/api/stations/{station['id']}/phases",
            json={
                "ordre": order,
                "debut_s": start,
                "fin_s": end,
                "type_auto": "activity" if order == 1 else "stop",
                "categorie": "Non classé",
            },
        )
        assert response.status_code == 201, response.text
        phase_ids.append(response.json()["id"])

    edited = client.patch(
        f"/api/stations/{station['id']}/phases/{phase_ids[0]}",
        json={"fin_s": 2.8, "description": "Assembler", "categorie": "VA"},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["fin_s"] == 2.8

    split = client.post(
        f"/api/stations/{station['id']}/phases/{phase_ids[0]}/split",
        json={"temps_s": 1.4},
    )
    assert split.status_code == 201, split.text
    phases = split.json()
    assert len(phases) == 3
    assert phases[0]["fin_s"] == phases[1]["debut_s"] == 1.4
    assert [phase["ordre"] for phase in phases] == [1, 2, 3]

    merged = client.post(
        f"/api/stations/{station['id']}/phases/merge",
        json={"phase_ids": [phases[0]["id"], phases[1]["id"]]},
    )
    assert merged.status_code == 200, merged.text
    assert len(merged.json()) == 2
    assert merged.json()[0]["fin_s"] == 2.8
    assert [phase["ordre"] for phase in merged.json()] == [1, 2]

    overlap = client.patch(
        f"/api/stations/{station['id']}/phases/{merged.json()[0]['id']}",
        json={"fin_s": 3.1},
    )
    assert overlap.status_code == 422
