from __future__ import annotations


def test_ergonomic_scoring_endpoint_is_deterministic_and_does_not_persist(client):
    project = client.post("/api/projects", json={"nom": "Pré-cotation", "takt_s": 60}).json()
    station = client.post(
        f"/api/projects/{project['id']}/stations",
        json={"nom": "Poste ergonomie"},
    ).json()
    angles = {
        "left_shoulder": 0,
        "right_shoulder": 0,
        "left_elbow": 90,
        "right_elbow": 90,
        "left_knee": 180,
        "right_knee": 180,
        "trunk_inclination": 0,
        "neck": 0,
        "left_wrist": 0,
        "right_wrist": 0,
    }
    factors = {
        "charge_kg": 0,
        "type_effort": "intermittent",
        "prise": "bonne",
        "torsion_tronc": False,
        "inclinaison_laterale_tronc": False,
        "torsion_cou": False,
        "inclinaison_laterale_cou": False,
        "epaule_surelevee": False,
        "abduction_bras": False,
        "bras_soutenu": False,
        "avant_bras_croise_ligne_mediane": False,
        "deviation_poignet": False,
        "rotation_poignet": "milieu",
        "appui_jambes": "bilateral",
        "frequence_geste_par_min": 0,
        "posture_statique_sup_1min": False,
    }

    first = client.post(
        "/api/ergonomics/score",
        json={
            "instant_s": 1.5,
            "view_camera": "profil_gauche",
            "angles": angles,
            "evaluator_factors": factors,
        },
    )
    second = client.post(
        "/api/ergonomics/score",
        json={
            "instant_s": 1.5,
            "view_camera": "profil_gauche",
            "angles": angles,
            "evaluator_factors": factors,
        },
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["rula"]["score_probable"] == 1
    assert first.json()["reba"]["score_probable"] == 1
    assert first.json()["rula"] == second.json()["rula"]
    assert first.json()["reba"] == second.json()["reba"]
    assert client.get(f"/api/stations/{station['id']}").json()["ergonomic_assessments"] == []


def test_ergonomic_scoring_endpoint_summarizes_filtered_temporal_series(client):
    angles = {
        "left_elbow": 90,
        "right_elbow": 90,
        "left_shoulder": 10,
        "right_shoulder": 10,
        "left_knee": 170,
        "right_knee": 170,
        "trunk_inclination": 5,
    }
    series = [
        {"time_s": 0.0, "angles": angles},
        {"time_s": 0.5, "angles": {**angles, "left_shoulder": 12}},
        {"time_s": 1.0, "angles": {**angles, "left_shoulder": 60}},
        {"time_s": 1.5, "angles": {**angles, "left_shoulder": 13}},
        {"time_s": 2.0, "angles": {**angles, "left_knee": None}},
    ]

    response = client.post(
        "/api/ergonomics/score",
        json={
            "instant_s": 0.5,
            "view_camera": "profil_gauche",
            "angles": angles,
            "evaluator_factors": {},
            "series": series,
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["serie_temporelle"]["images_occultees_ecartees"] == 1
    assert result["serie_temporelle"]["images_saut_aberrant_ecartees"] == 1
    assert result["serie_temporelle"]["posture_plus_defavorable"] is not None
    assert any("série temporelle" in assumption for assumption in result["hypotheses"])


def test_ergonomic_scoring_endpoint_accepts_partial_posture_and_reports_missing_angles(client):
    response = client.post(
        "/api/ergonomics/score",
        json={
            "instant_s": 105.0,
            "view_camera": "profil_droit",
            "angles": {
                "right_elbow": 134.4,
                "left_shoulder": 15.4,
                "right_shoulder": 18.6,
                "trunk_inclination": 3.0,
                "left_elbow": None,
                "left_knee": None,
                "right_knee": None,
            },
            "evaluator_factors": {},
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rula"]["score_min"] <= result["rula"]["score_probable"] <= result["rula"]["score_max"]
    assert result["reba"]["score_min"] <= result["reba"]["score_probable"] <= result["reba"]["score_max"]
    assert "left_elbow" in result["donnees_manquantes"]
    assert "left_knee" in result["donnees_manquantes"]
    assert "right_knee" in result["donnees_manquantes"]
    assert result["fiabilite"] == "faible"
