from __future__ import annotations

import pytest

from app.ergonomics.scoring import score_posture, summarize_series


KNOWN_FACTORS = {
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

KNOWN_ANGLES = (
    {
        "left_shoulder": 0, "right_shoulder": 0, "left_elbow": 90, "right_elbow": 90,
        "left_knee": 180, "right_knee": 180, "trunk_inclination": 0, "neck": 0,
        "left_wrist": 0, "right_wrist": 0,
    },
    {
        "left_shoulder": 30, "right_shoulder": 10, "left_elbow": 90, "right_elbow": 90,
        "left_knee": 180, "right_knee": 180, "trunk_inclination": 10, "neck": 5,
        "left_wrist": 5, "right_wrist": 0,
    },
    {
        "left_shoulder": 60, "right_shoulder": 45, "left_elbow": 120, "right_elbow": 90,
        "left_knee": 150, "right_knee": 160, "trunk_inclination": 30, "neck": 15,
        "left_wrist": 20, "right_wrist": 10,
    },
    {
        "left_shoulder": 100, "right_shoulder": 95, "left_elbow": 130, "right_elbow": 130,
        "left_knee": 110, "right_knee": 110, "trunk_inclination": 70, "neck": 35,
        "left_wrist": 25, "right_wrist": 25,
    },
    {
        "left_shoulder": 45, "right_shoulder": 20, "left_elbow": 80, "right_elbow": 85,
        "left_knee": 130, "right_knee": 140, "trunk_inclination": 20, "neck": 20,
        "left_wrist": 15, "right_wrist": 8,
    },
)


@pytest.mark.parametrize("angles,expected_score", list(zip(KNOWN_ANGLES, (1, 3, 4, 5, 3))))
def test_known_rula_cases(angles, expected_score):
    result = score_posture(41.0, angles, "profil_gauche", KNOWN_FACTORS)

    assert result["rula"]["score_min"] == expected_score
    assert result["rula"]["score_probable"] == expected_score
    assert result["rula"]["score_max"] == expected_score
    assert result["rula"]["cote_retenu"] in {"gauche", "droite"}
    assert result["rula"]["detail"]["table_A"] >= 1
    assert result["rula"]["detail"]["table_B"] >= 1
    assert result["rula"]["detail"]["table_C"] == expected_score


@pytest.mark.parametrize("angles,expected_score", list(zip(KNOWN_ANGLES, (1, 1, 4, 9, 3))))
def test_known_reba_cases(angles, expected_score):
    result = score_posture(41.0, angles, "profil_gauche", KNOWN_FACTORS)

    assert result["reba"]["score_min"] == expected_score
    assert result["reba"]["score_probable"] == expected_score
    assert result["reba"]["score_max"] == expected_score
    assert result["reba"]["cote_retenu"] in {"gauche", "droite"}
    assert result["reba"]["detail"]["table_A"] >= 1
    assert result["reba"]["detail"]["table_B"] >= 1
    assert result["reba"]["detail"]["table_C"] + result["reba"]["detail"]["activite"] == expected_score


def test_requested_41_second_example_converts_angles_and_reports_uncertainty():
    result = score_posture(
        41.0,
        {
            "left_elbow": 96.2,
            "right_elbow": 132.9,
            "left_shoulder": 0.9,
            "right_shoulder": 12.4,
            "left_knee": 168.4,
            "right_knee": 156.4,
            "trunk_inclination": 2.6,
        },
        "inconnue",
        {},
    )

    assert result["instant_s"] == 41.0
    assert result["angles_convertis"]["flexion_avant_bras_g"] == 83.8
    assert result["angles_convertis"]["flexion_avant_bras_d"] == 47.1
    assert result["angles_convertis"]["flexion_genou_g"] == 11.6
    assert result["angles_convertis"]["flexion_genou_d"] == 23.6
    assert result["fiabilite"] == "faible"
    assert result["rula"]["score_min"] <= result["rula"]["score_probable"] <= result["rula"]["score_max"]
    assert result["reba"]["score_min"] <= result["reba"]["score_probable"] <= result["reba"]["score_max"]
    assert result["hypotheses"]
    assert result["questions_evaluateur"]
    assert len(result["questions_evaluateur"]) <= 5
    assert result["rula"]["cotes"][0]["cote"] == "gauche"
    assert result["rula"]["cotes"][1]["cote"] == "droite"


def test_temporal_summary_discards_occluded_and_aberrant_frames():
    base = {
        "left_elbow": 90, "right_elbow": 90, "left_shoulder": 10, "right_shoulder": 10,
        "left_knee": 170, "right_knee": 170, "trunk_inclination": 5,
    }
    samples = [
        {"time_s": 0.0, "angles": base},
        {"time_s": 0.5, "angles": {**base, "left_shoulder": 15}},
        {"time_s": 1.0, "angles": {**base, "left_shoulder": 60}},
        {"time_s": 1.5, "angles": {**base, "left_shoulder": 17}},
        {"time_s": 2.0, "angles": {**base, "left_knee": None}},
    ]

    result = summarize_series(samples, "profil_gauche", KNOWN_FACTORS)

    assert result["nombre_images_valides"] == 3
    assert result["images_occultees_ecartees"] == 1
    assert result["images_saut_aberrant_ecartees"] == 1
    assert result["posture_plus_defavorable"] is not None
    assert result["posture_plus_frequente"] is not None
    assert result["frequence_estimee_gestes_min"] >= 0


def test_temporal_summary_detects_static_posture_over_one_minute():
    angles = {
        "left_elbow": 90, "right_elbow": 90, "left_shoulder": 10, "right_shoulder": 10,
        "left_knee": 170, "right_knee": 170, "trunk_inclination": 5,
    }
    samples = [{"time_s": time_s, "angles": angles} for time_s in range(0, 62) if time_s % 1 == 0]

    result = summarize_series(samples, "profil_gauche", KNOWN_FACTORS)

    assert result["posture_statique_sup_60s"] is True
    assert result["duree_statique_max_s"] >= 60


def test_temporal_summary_detects_more_than_four_repeated_gestures_per_minute():
    samples = []
    for index in range(121):
        time_s = index * 0.5
        pulse = max(0, 1 - abs((time_s % 10) - 2) / 2)
        angles = {
            "left_elbow": 90,
            "right_elbow": 90,
            "left_shoulder": 10 + 30 * pulse,
            "right_shoulder": 10,
            "left_knee": 170,
            "right_knee": 170,
            "trunk_inclination": 5,
        }
        samples.append({"time_s": time_s, "angles": angles})

    result = summarize_series(samples, "profil_gauche", KNOWN_FACTORS)

    assert result["frequence_estimee_gestes_min"] > 4
    assert result["repetitivite_superieure_4_min"] is True
