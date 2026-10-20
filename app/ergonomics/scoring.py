from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping, Sequence


RULA_TABLE_A = (
    (1, 2, 2, 2, 2, 3, 3, 3),
    (2, 2, 2, 2, 3, 3, 3, 3),
    (2, 3, 3, 3, 3, 3, 4, 4),
    (2, 3, 3, 3, 3, 4, 4, 4),
    (3, 3, 3, 3, 3, 4, 4, 4),
    (3, 4, 4, 4, 4, 4, 5, 5),
    (3, 3, 4, 4, 4, 4, 5, 5),
    (3, 4, 4, 4, 4, 4, 5, 5),
    (4, 4, 4, 4, 4, 5, 5, 5),
    (4, 4, 4, 4, 4, 5, 5, 5),
    (4, 4, 4, 4, 4, 5, 5, 5),
    (4, 4, 4, 5, 5, 5, 6, 6),
    (5, 5, 5, 5, 5, 6, 6, 7),
    (5, 6, 6, 6, 6, 7, 7, 7),
    (6, 6, 6, 7, 7, 7, 7, 8),
    (7, 7, 7, 7, 7, 8, 8, 9),
    (8, 8, 8, 8, 8, 9, 9, 9),
    (9, 9, 9, 9, 9, 9, 9, 9),
)

RULA_TABLE_B = (
    (1, 3, 2, 3, 3, 4, 5, 5, 6, 6, 7, 7),
    (2, 3, 2, 3, 4, 5, 5, 5, 6, 7, 7, 7),
    (3, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 7),
    (5, 5, 5, 6, 6, 7, 7, 7, 7, 7, 8, 8),
    (7, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8),
    (8, 8, 8, 8, 8, 8, 8, 9, 9, 9, 9, 9),
)

RULA_TABLE_C = (
    (1, 2, 3, 3, 4, 5, 5),
    (2, 2, 3, 4, 4, 5, 5),
    (3, 3, 3, 4, 4, 5, 6),
    (3, 3, 3, 4, 5, 6, 6),
    (4, 4, 4, 5, 6, 7, 7),
    (4, 4, 5, 6, 6, 7, 7),
    (5, 5, 6, 6, 7, 7, 7),
    (5, 5, 6, 7, 7, 7, 7),
)

REBA_TABLE_A = (
    ((1, 2, 3, 4), (1, 2, 3, 4), (3, 3, 5, 6)),
    ((2, 3, 4, 5), (3, 4, 5, 6), (4, 5, 6, 7)),
    ((2, 4, 5, 6), (4, 5, 6, 7), (5, 6, 7, 8)),
    ((3, 5, 6, 7), (5, 6, 7, 8), (6, 7, 8, 9)),
    ((4, 6, 7, 8), (6, 7, 8, 9), (7, 8, 9, 9)),
)

REBA_TABLE_B = (
    ((1, 2, 2), (1, 2, 3)),
    ((1, 2, 3), (2, 3, 4)),
    ((3, 4, 5), (4, 5, 5)),
    ((4, 5, 5), (5, 6, 7)),
    ((6, 7, 8), (7, 8, 8)),
    ((7, 8, 8), (8, 9, 9)),
)

REBA_TABLE_C = (
    (1, 1, 1, 2, 3, 3, 4, 5, 6, 7, 7, 7),
    (1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 7, 8),
    (2, 3, 3, 3, 4, 5, 6, 7, 7, 8, 8, 8),
    (3, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9),
    (4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9),
    (6, 6, 6, 7, 8, 8, 9, 9, 10, 10, 10, 10),
    (7, 7, 7, 8, 9, 9, 9, 10, 10, 11, 11, 11),
    (8, 8, 8, 9, 10, 10, 10, 10, 10, 11, 11, 11),
    (9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12),
    (10, 10, 10, 11, 11, 11, 11, 12, 12, 12, 12, 12),
    (11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12),
    (12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12),
)

SCENARIOS = ("min", "probable", "max")
RULA_LEVELS = (
    (2, "Acceptable"),
    (4, "À investiguer"),
    (6, "À investiguer et changer bientôt"),
    (7, "Changement immédiat"),
)
REBA_LEVELS = (
    (1, "Négligeable"),
    (3, "Faible"),
    (7, "Moyen"),
    (10, "Élevé"),
    (15, "Très élevé"),
)


def _level(score: int, levels: Sequence[tuple[int, str]]) -> str:
    return next(label for maximum, label in levels if score <= maximum)


def _pick(value: Any, scenario: str, favorable: Any, typical: Any, adverse: Any) -> Any:
    if value is not None:
        return value
    return {"min": favorable, "probable": typical, "max": adverse}[scenario]


def _segment_score(
    angle: float | None,
    scenario: str,
    *,
    missing_low: float,
    missing_typical: float,
    missing_high: float,
) -> float:
    return float(_pick(angle, scenario, missing_low, missing_typical, missing_high))


def _score_rula_side(
    side: str,
    angles: Mapping[str, Any],
    factors: Mapping[str, Any],
    view: str,
    scenario: str,
) -> dict[str, Any]:
    shoulder = angles.get(f"{side}_shoulder")
    elbow = angles.get(f"{side}_elbow")
    knee = angles.get(f"{side}_knee")
    forearm_flexion = 180.0 - float(elbow) if elbow is not None else None
    knee_flexion = 180.0 - float(knee) if knee is not None else None
    neck_flexion = _segment_score(
        angles.get("neck"),
        scenario,
        missing_low=0,
        missing_typical=15,
        missing_high=30,
    )
    wrist_flexion = _segment_score(
        angles.get(f"{side}_wrist"),
        scenario,
        missing_low=0,
        missing_typical=7.5,
        missing_high=20,
    )

    shoulder_value = _segment_score(
        shoulder,
        scenario,
        missing_low=0,
        missing_typical=30,
        missing_high=95,
    )
    if shoulder is None:
        shoulder_flexion = shoulder_value
        shoulder_abduction_from_view = scenario == "max"
    elif view in {"profil_gauche", "profil_droit"}:
        shoulder_flexion = shoulder_value
        shoulder_abduction_from_view = False
    elif view == "face":
        shoulder_flexion = 0.0
        shoulder_abduction_from_view = shoulder_value >= 20
    else:
        shoulder_flexion = shoulder_value if scenario != "max" else shoulder_value + 20
        shoulder_abduction_from_view = scenario != "min" and shoulder_value >= 20

    arm_score = (
        1 if -20 <= shoulder_flexion <= 20
        else 2 if shoulder_flexion < -20 or shoulder_flexion < 45
        else 3 if shoulder_flexion <= 90
        else 4
    )
    arm_raised = _pick(factors.get("epaule_surelevee"), scenario, False, False, True)
    arm_abduction = _pick(
        factors.get("abduction_bras"),
        scenario,
        shoulder_abduction_from_view and scenario == "min",
        shoulder_abduction_from_view,
        True,
    )
    arm_supported = _pick(factors.get("bras_soutenu"), scenario, True, False, False)
    arm_score = max(1, min(6, arm_score + int(bool(arm_raised)) + int(bool(arm_abduction)) - int(bool(arm_supported))))

    forearm_value = _segment_score(
        forearm_flexion,
        scenario,
        missing_low=80,
        missing_typical=50,
        missing_high=120,
    )
    forearm_score = 1 if 60 <= forearm_value <= 100 else 2
    forearm_crossed = _pick(factors.get("avant_bras_croise_ligne_mediane"), scenario, False, False, True)
    forearm_score = min(3, forearm_score + int(bool(forearm_crossed)))

    wrist_score = 1 if abs(wrist_flexion) < 1e-9 else 2 if abs(wrist_flexion) <= 15 else 3
    wrist_deviation = _pick(factors.get("deviation_poignet"), scenario, False, False, True)
    wrist_score = min(4, wrist_score + int(bool(wrist_deviation)))
    rotation = _pick(factors.get("rotation_poignet"), scenario, "milieu", "milieu", "proche_butee")
    rotation_score = 1 if rotation == "milieu" else 2

    rula_a = RULA_TABLE_A[(arm_score - 1) * 3 + (forearm_score - 1)][(wrist_score - 1) * 2 + rotation_score - 1]
    trunk_angle = _segment_score(
        angles.get("trunk_inclination") if view in {"profil_gauche", "profil_droit"} else None,
        scenario,
        missing_low=0,
        missing_typical=20,
        missing_high=65,
    )
    trunk_angle = abs(trunk_angle)
    trunk_score = 1 if trunk_angle < 1 else 2 if trunk_angle <= 20 else 3 if trunk_angle <= 60 else 4
    trunk_twist = _pick(factors.get("torsion_tronc"), scenario, False, False, True)
    observed_lateral_trunk = view == "face" and angles.get("trunk_inclination") is not None
    trunk_lean = _pick(
        factors.get("inclinaison_laterale_tronc"),
        scenario,
        False,
        abs(float(angles["trunk_inclination"])) > 10 if observed_lateral_trunk else False,
        True,
    )
    trunk_score = min(6, trunk_score + int(bool(trunk_twist)) + int(bool(trunk_lean)))

    neck_score = 4 if neck_flexion < 0 else 1 if neck_flexion <= 10 else 2 if neck_flexion <= 20 else 3
    neck_score = min(6, neck_score
                     + int(bool(_pick(factors.get("torsion_cou"), scenario, False, False, True)))
                     + int(bool(_pick(factors.get("inclinaison_laterale_cou"), scenario, False, False, True))))
    leg_support = _pick(factors.get("appui_jambes"), scenario, "bilateral", "bilateral", "instable")
    legs_score = 1 if leg_support in {"bilateral", "assis"} else 2
    table_b = RULA_TABLE_B[neck_score - 1][(trunk_score - 1) * 2 + legs_score - 1]

    frequency = float(_pick(factors.get("frequence_geste_par_min"), scenario, 0, 4.1, 8))
    static = bool(_pick(factors.get("posture_statique_sup_1min"), scenario, False, False, True))
    muscle = int(static or frequency > 4)
    load = float(_pick(factors.get("charge_kg"), scenario, 0, 3, 12))
    effort = _pick(factors.get("type_effort"), scenario, "intermittent", "repete", "choc")
    if effort == "choc" or load > 10:
        force = 3
    elif load < 2:
        force = 0
    elif load <= 10 and effort == "intermittent":
        force = 1
    elif load <= 10:
        force = 2

    score_c = min(8, rula_a + muscle + force)
    score_d = min(9, table_b + muscle + force)
    final_score = RULA_TABLE_C[score_c - 1][min(7, score_d) - 1]
    return {
        "cote": "gauche" if side == "left" else "droite",
        "angles_convertis": {
            "flexion_bras": round(shoulder_flexion, 1),
            "flexion_avant_bras": round(forearm_value, 1),
            "flexion_genou": None if knee_flexion is None else round(knee_flexion, 1),
        },
        "detail": {
            "bras": arm_score,
            "avant_bras": forearm_score,
            "poignet": wrist_score,
            "rotation": rotation_score,
            "table_A": rula_a,
            "cou": neck_score,
            "tronc": trunk_score,
            "jambes": legs_score,
            "table_B": table_b,
            "muscle_A": muscle,
            "force_A": force,
            "score_C": score_c,
            "muscle_B": muscle,
            "force_B": force,
            "score_D": score_d,
            "table_C": final_score,
        },
        "lectures_tables": [
            f"RULA A : bras {arm_score}, avant-bras {forearm_score}, poignet {wrist_score}, rotation {rotation_score} → {rula_a}.",
            f"RULA B : cou {neck_score}, tronc {trunk_score}, jambes {legs_score} → {table_b}.",
            f"RULA C : score C {score_c}, score D {score_d} → {final_score}.",
        ],
        "score": final_score,
        "niveau": _level(final_score, RULA_LEVELS),
    }


def _score_reba_side(
    side: str,
    angles: Mapping[str, Any],
    factors: Mapping[str, Any],
    view: str,
    scenario: str,
) -> dict[str, Any]:
    shoulder = angles.get(f"{side}_shoulder")
    elbow = angles.get(f"{side}_elbow")
    knee = angles.get(f"{side}_knee")
    forearm_flexion = 180.0 - float(elbow) if elbow is not None else None
    knee_flexion = 180.0 - float(knee) if knee is not None else None

    trunk_angle = _segment_score(
        angles.get("trunk_inclination") if view in {"profil_gauche", "profil_droit"} else None,
        scenario,
        missing_low=0,
        missing_typical=20,
        missing_high=65,
    )
    trunk_angle = abs(trunk_angle)
    trunk_score = 1 if trunk_angle < 1 else 2 if trunk_angle <= 20 else 3 if trunk_angle <= 60 else 4
    observed_lateral_trunk = view == "face" and angles.get("trunk_inclination") is not None
    lateral_trunk = _pick(
        factors.get("inclinaison_laterale_tronc"),
        scenario,
        False,
        abs(float(angles["trunk_inclination"])) > 10 if observed_lateral_trunk else False,
        True,
    )
    trunk_score = min(5, trunk_score
                      + int(bool(_pick(factors.get("torsion_tronc"), scenario, False, False, True)))
                      + int(bool(lateral_trunk)))
    neck_angle = _segment_score(angles.get("neck"), scenario, missing_low=0, missing_typical=15, missing_high=30)
    neck_score = 2 if neck_angle < 0 or neck_angle > 20 else 1
    neck_score = min(3, neck_score
                     + int(bool(_pick(factors.get("torsion_cou"), scenario, False, False, True)))
                     + int(bool(_pick(factors.get("inclinaison_laterale_cou"), scenario, False, False, True))))
    leg_support = _pick(factors.get("appui_jambes"), scenario, "bilateral", "bilateral", "instable")
    legs_score = 2 if leg_support in {"unilateral", "instable"} else 1
    if leg_support != "assis":
        knee_value = _segment_score(
            knee_flexion,
            scenario,
            missing_low=0,
            missing_typical=15,
            missing_high=70,
        )
        legs_score += int(30 <= knee_value <= 60) + 2 * int(knee_value > 60)
    legs_score = min(4, legs_score)
    reba_a = REBA_TABLE_A[trunk_score - 1][neck_score - 1][legs_score - 1]
    load = float(_pick(factors.get("charge_kg"), scenario, 0, 3, 12))
    effort = _pick(factors.get("type_effort"), scenario, "intermittent", "repete", "choc")
    load_score = 0 if load < 5 else 1 if load <= 10 else 2
    if effort == "choc":
        load_score += 1
    score_a = reba_a + load_score

    shoulder_value = _segment_score(shoulder, scenario, missing_low=0, missing_typical=30, missing_high=95)
    if shoulder is None:
        arm_angle = shoulder_value
        abduction_by_view = scenario == "max"
    elif view == "face":
        arm_angle = 0
        abduction_by_view = shoulder_value >= 20
    elif view in {"profil_gauche", "profil_droit"}:
        arm_angle = shoulder_value
        abduction_by_view = False
    else:
        arm_angle = shoulder_value if scenario != "max" else shoulder_value + 20
        abduction_by_view = scenario != "min" and shoulder_value >= 20
    arm_score = (
        1 if -20 <= arm_angle <= 20
        else 2 if arm_angle < -20 or arm_angle < 45
        else 3 if arm_angle <= 90
        else 4
    )
    arm_score = min(
        6,
        max(
            1,
            arm_score
            + int(bool(_pick(factors.get("abduction_bras"), scenario, abduction_by_view and scenario == "min", abduction_by_view, True)))
            + int(bool(_pick(factors.get("epaule_surelevee"), scenario, False, False, True)))
            - int(bool(_pick(factors.get("bras_soutenu"), scenario, True, False, False))),
        ),
    )
    forearm_value = _segment_score(forearm_flexion, scenario, missing_low=80, missing_typical=50, missing_high=120)
    forearm_score = 1 if 60 <= forearm_value <= 100 else 2
    wrist_angle = _segment_score(
        angles.get(f"{side}_wrist"),
        scenario,
        missing_low=0,
        missing_typical=7.5,
        missing_high=20,
    )
    wrist_score = 1 if abs(wrist_angle) <= 15 else 2
    wrist_score = min(3, wrist_score
                      + int(bool(_pick(factors.get("deviation_poignet"), scenario, False, False, True))))
    reba_b = REBA_TABLE_B[arm_score - 1][forearm_score - 1][wrist_score - 1]
    grip = _pick(factors.get("prise"), scenario, "bonne", "acceptable", "inacceptable")
    grip_score = {"bonne": 0, "acceptable": 1, "mauvaise": 2, "inacceptable": 3}[grip]
    score_b = reba_b + grip_score
    table_c = REBA_TABLE_C[min(12, score_a) - 1][min(12, score_b) - 1]
    frequency = float(_pick(factors.get("frequence_geste_par_min"), scenario, 0, 4.1, 8))
    static = bool(_pick(factors.get("posture_statique_sup_1min"), scenario, False, False, True))
    unstable = leg_support == "instable"
    activity = int(static) + int(frequency > 4) + int(unstable)
    final_score = min(15, table_c + activity)
    return {
        "cote": "gauche" if side == "left" else "droite",
        "angles_convertis": {
            "flexion_bras": round(arm_angle, 1),
            "flexion_avant_bras": round(forearm_value, 1),
            "flexion_genou": None if knee_flexion is None else round(knee_flexion, 1),
        },
        "detail": {
            "tronc": trunk_score,
            "cou": neck_score,
            "jambes": legs_score,
            "table_A": reba_a,
            "charge": load_score,
            "score_A": score_a,
            "bras": arm_score,
            "avant_bras": forearm_score,
            "poignet": wrist_score,
            "table_B": reba_b,
            "prise": grip_score,
            "score_B": score_b,
            "table_C": table_c,
            "activite": activity,
        },
        "lectures_tables": [
            f"REBA A : tronc {trunk_score}, cou {neck_score}, jambes {legs_score} → {reba_a} ; charge {load_score} → score A {score_a}.",
            f"REBA B : bras {arm_score}, avant-bras {forearm_score}, poignet {wrist_score} → {reba_b} ; prise {grip_score} → score B {score_b}.",
            f"REBA C : score A {score_a}, score B {score_b} → {table_c} ; activité {activity} → {final_score}.",
        ],
        "score": final_score,
        "niveau": _level(final_score, REBA_LEVELS),
    }


def score_posture(
    instant_s: float,
    angles: Mapping[str, Any],
    view_camera: str,
    factors: Mapping[str, Any],
) -> dict[str, Any]:
    """Calcule des pré-cotations RULA/REBA reproductibles pour les deux côtés."""
    if not math.isfinite(float(instant_s)) or instant_s < 0:
        raise ValueError("L’instant vidéo doit être un nombre positif et fini.")
    normalized_angles = dict(angles)
    for name, value in normalized_angles.items():
        if value is None:
            continue
        numeric_value = float(value)
        if not math.isfinite(numeric_value) or not -180 <= numeric_value <= 180:
            raise ValueError(f"L’angle {name} doit être compris entre -180° et 180°.")
        normalized_angles[name] = numeric_value
    normalized_factors = dict(factors)
    boolean_factors = {
        "torsion_tronc", "inclinaison_laterale_tronc", "torsion_cou",
        "inclinaison_laterale_cou", "epaule_surelevee", "abduction_bras",
        "bras_soutenu", "avant_bras_croise_ligne_mediane", "deviation_poignet",
        "posture_statique_sup_1min",
    }
    for key in boolean_factors:
        value = normalized_factors.get(key)
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            normalized_factors[key] = value.lower() == "true"
        elif value is not None and not isinstance(value, bool):
            raise ValueError(f"Le facteur {key} doit être Oui, Non ou non renseigné.")
    for key in ("charge_kg", "frequence_geste_par_min"):
        value = normalized_factors.get(key)
        if value is not None:
            numeric_value = float(value)
            if not math.isfinite(numeric_value) or numeric_value < 0:
                raise ValueError(f"Le facteur {key} doit être un nombre positif et fini.")
            normalized_factors[key] = numeric_value
    categorical_values = {
        "type_effort": {"intermittent", "statique", "repete", "choc"},
        "prise": {"bonne", "acceptable", "mauvaise", "inacceptable"},
        "rotation_poignet": {"milieu", "proche_butee"},
        "appui_jambes": {"bilateral", "unilateral", "assis", "instable"},
    }
    for key, allowed_values in categorical_values.items():
        value = normalized_factors.get(key)
        if value is not None and value not in allowed_values:
            raise ValueError(f"Valeur invalide pour {key}.")
    normalized_view = view_camera if view_camera in {
        "face", "profil_gauche", "profil_droit", "oblique"
    } else "inconnue"
    angle_keys = (
        "left_elbow", "right_elbow", "left_shoulder", "right_shoulder",
        "left_knee", "right_knee", "trunk_inclination", "neck",
        "left_wrist", "right_wrist",
    )
    missing = [key for key in angle_keys if normalized_angles.get(key) is None]
    if normalized_view not in {"profil_gauche", "profil_droit"}:
        missing.append("flexion du tronc (vue non latérale)")
    required_factor_labels = {
        "charge_kg": "charge",
        "type_effort": "type d’effort",
        "prise": "qualité de prise",
        "torsion_tronc": "torsion du tronc",
        "inclinaison_laterale_tronc": "inclinaison latérale du tronc",
        "torsion_cou": "torsion du cou",
        "inclinaison_laterale_cou": "inclinaison latérale du cou",
        "epaule_surelevee": "épaule surélevée",
        "abduction_bras": "abduction du bras",
        "bras_soutenu": "bras soutenu",
        "avant_bras_croise_ligne_mediane": "avant-bras croisé",
        "deviation_poignet": "déviation du poignet",
        "rotation_poignet": "rotation du poignet",
        "appui_jambes": "appui des jambes",
        "frequence_geste_par_min": "fréquence des gestes",
        "posture_statique_sup_1min": "posture statique",
    }
    missing.extend(label for key, label in required_factor_labels.items() if factors.get(key) is None)
    if normalized_view not in {"face", "profil_gauche", "profil_droit"}:
        missing.append("vue caméra exploitable (profil ou face)")

    hypotheses = [
        f"{label} : valeurs favorables, probables et défavorables utilisées pour calculer l’intervalle."
        for label in dict.fromkeys(missing)
    ]
    if normalized_view == "oblique":
        hypotheses.append(
            "Vue oblique : les angles d’épaule et de tronc peuvent combiner flexion et abduction/inclinaison latérale ; des fourchettes sont utilisées."
        )
    scenarios: dict[str, dict[str, Any]] = {}
    for scenario in SCENARIOS:
        rula_sides = [
            _score_rula_side(side, normalized_angles, normalized_factors, normalized_view, scenario)
            for side in ("left", "right")
        ]
        reba_sides = [
            _score_reba_side(side, normalized_angles, normalized_factors, normalized_view, scenario)
            for side in ("left", "right")
        ]
        rula_worst = max(rula_sides, key=lambda side: side["score"])
        reba_worst = max(reba_sides, key=lambda side: side["score"])
        scenarios[scenario] = {
            "rula": {"score": rula_worst["score"], "niveau": rula_worst["niveau"], "cote_retenu": rula_worst["cote"],
                     "cotes": rula_sides, "detail": rula_worst["detail"]},
            "reba": {"score": reba_worst["score"], "niveau": reba_worst["niveau"], "cote_retenu": reba_worst["cote"],
                     "cotes": reba_sides, "detail": reba_worst["detail"]},
        }
    rula_side_ranges = []
    reba_side_ranges = []
    for side_index in range(2):
        rula_probable = scenarios["probable"]["rula"]["cotes"][side_index]
        reba_probable = scenarios["probable"]["reba"]["cotes"][side_index]
        rula_side_ranges.append({
            **rula_probable,
            "score_min": scenarios["min"]["rula"]["cotes"][side_index]["score"],
            "score_probable": rula_probable["score"],
            "score_max": scenarios["max"]["rula"]["cotes"][side_index]["score"],
        })
        reba_side_ranges.append({
            **reba_probable,
            "score_min": scenarios["min"]["reba"]["cotes"][side_index]["score"],
            "score_probable": reba_probable["score"],
            "score_max": scenarios["max"]["reba"]["cotes"][side_index]["score"],
        })
    reliability = "élevée" if not missing else "moyenne" if len(set(missing)) <= 2 else "faible"
    return {
        "instant_s": round(float(instant_s), 1),
        "vue_camera": normalized_view,
        "angles_convertis": {
            "flexion_bras_g": 0.0 if normalized_view == "face" and normalized_angles.get("left_shoulder") is not None else normalized_angles.get("left_shoulder"),
            "flexion_bras_d": 0.0 if normalized_view == "face" and normalized_angles.get("right_shoulder") is not None else normalized_angles.get("right_shoulder"),
            "abduction_bras_g": normalized_angles.get("left_shoulder") if normalized_view == "face" else None,
            "abduction_bras_d": normalized_angles.get("right_shoulder") if normalized_view == "face" else None,
            "flexion_avant_bras_g": None if normalized_angles.get("left_elbow") is None else round(180 - float(normalized_angles["left_elbow"]), 1),
            "flexion_avant_bras_d": None if normalized_angles.get("right_elbow") is None else round(180 - float(normalized_angles["right_elbow"]), 1),
            "flexion_genou_g": None if normalized_angles.get("left_knee") is None else round(180 - float(normalized_angles["left_knee"]), 1),
            "flexion_genou_d": None if normalized_angles.get("right_knee") is None else round(180 - float(normalized_angles["right_knee"]), 1),
            "inclinaison_tronc_ou_laterale": normalized_angles.get("trunk_inclination"),
            "cou": normalized_angles.get("neck"),
            "poignet_g": normalized_angles.get("left_wrist"),
            "poignet_d": normalized_angles.get("right_wrist"),
            "interpretation_epaule": (
                "flexion du bras estimée en profil"
                if normalized_view in {"profil_gauche", "profil_droit"}
                else "abduction estimée en vue de face"
                if normalized_view == "face"
                else "flexion/abduction ambiguë ; valeurs probables et fourchettes par scénario"
            ),
            "interpretation_tronc": (
                "flexion estimée en profil"
                if normalized_view in {"profil_gauche", "profil_droit"}
                else "inclinaison latérale estimée en vue de face ; flexion non visible"
                if normalized_view == "face"
                else "flexion/inclinaison latérale ambiguë ; valeurs probables et fourchettes par scénario"
            ),
        },
        "rula": {
            "score_min": scenarios["min"]["rula"]["score"],
            "score_probable": scenarios["probable"]["rula"]["score"],
            "score_max": scenarios["max"]["rula"]["score"],
            "niveau": scenarios["probable"]["rula"]["niveau"],
            "cote_retenu": scenarios["probable"]["rula"]["cote_retenu"],
            "detail": scenarios["probable"]["rula"]["detail"],
            "cotes": rula_side_ranges,
        },
        "reba": {
            "score_min": scenarios["min"]["reba"]["score"],
            "score_probable": scenarios["probable"]["reba"]["score"],
            "score_max": scenarios["max"]["reba"]["score"],
            "niveau": scenarios["probable"]["reba"]["niveau"],
            "cote_retenu": scenarios["probable"]["reba"]["cote_retenu"],
            "detail": scenarios["probable"]["reba"]["detail"],
            "cotes": reba_side_ranges,
        },
        "fiabilite": reliability,
        "donnees_manquantes": list(dict.fromkeys(missing)),
        "hypotheses": hypotheses,
        "questions_evaluateur": [
            f"Pouvez-vous confirmer {label} sur la posture observée ?"
            for label in dict.fromkeys(missing[:5])
        ],
        "avertissement": (
            "Pré-cotation à valider par l’évaluateur selon la grille officielle RULA/REBA. "
            "Dépistage, pas diagnostic médical."
        ),
    }


def summarize_series(
    samples: Sequence[Mapping[str, Any]],
    view_camera: str,
    factors: Mapping[str, Any],
) -> dict[str, Any]:
    """Filtre les repères incomplets/sauts aberrants et résume les postures observées."""
    eligible: list[Mapping[str, Any]] = []
    rejected_occlusion = 0
    rejected_jump = 0
    angle_keys = (
        "left_elbow", "right_elbow", "left_shoulder", "right_shoulder",
        "left_knee", "right_knee", "trunk_inclination",
    )
    for sample in samples:
        angles = sample.get("angles") or {}
        if any(angles.get(key) is None for key in angle_keys):
            rejected_occlusion += 1
            continue
        eligible.append(sample)

    filtered: list[Mapping[str, Any]] = []
    for sample in eligible:
        previous = filtered[-1] if filtered else None
        interval = float(sample["time_s"]) - float(previous["time_s"]) if previous else 0.0
        if previous and 0.35 <= interval <= 0.65 and any(
            abs(float(sample["angles"][key]) - float(previous["angles"][key])) > 40
            for key in angle_keys
        ):
            rejected_jump += 1
            continue
        filtered.append(sample)
    if not filtered:
        return {
            "nombre_images_valides": 0,
            "images_occultees_ecartees": rejected_occlusion,
            "images_saut_aberrant_ecartees": rejected_jump,
            "posture_plus_defavorable": None,
            "posture_plus_frequente": None,
            "frequence_estimee_gestes_min": None,
            "posture_statique_sup_60s": False,
        }

    scored = [
        score_posture(float(sample["time_s"]), sample["angles"], view_camera, factors)
        for sample in filtered
    ]
    worst_index = max(
        range(len(filtered)),
        key=lambda index: max(scored[index]["rula"]["score_probable"], scored[index]["reba"]["score_probable"]),
    )
    signatures = [
        tuple(round(float(sample["angles"][key]) / 10) for key in angle_keys)
        for sample in filtered
    ]
    signature_counts = Counter(signatures)
    common_signature = signature_counts.most_common(1)[0][0]
    frequent_index = signatures.index(common_signature)

    static_seconds = 0.0
    longest_static = 0.0
    baseline: Mapping[str, Any] | None = None
    previous_time: float | None = None
    for sample in filtered:
        time_s = float(sample["time_s"])
        current_angles = sample["angles"]
        if baseline is not None and previous_time is not None and all(
            abs(float(current_angles[key]) - float(baseline[key])) < 10 for key in angle_keys
        ):
            static_seconds += time_s - previous_time
            longest_static = max(longest_static, static_seconds)
        else:
            static_seconds = 0.0
            baseline = current_angles
        previous_time = time_s

    baseline_angles = filtered[0]["angles"]
    movement_amplitude = [
        max(abs(float(sample["angles"][key]) - float(baseline_angles[key])) for key in angle_keys)
        for sample in filtered
    ]
    gesture_peaks = sum(
        1 for index in range(1, len(movement_amplitude) - 1)
        if movement_amplitude[index] > 10
        and movement_amplitude[index] >= movement_amplitude[index - 1]
        and movement_amplitude[index] > movement_amplitude[index + 1]
        and movement_amplitude[index] - min(
            movement_amplitude[index - 1], movement_amplitude[index + 1]
        ) >= 5
    )
    duration_minutes = max(
        (float(filtered[-1]["time_s"]) - float(filtered[0]["time_s"])) / 60,
        0.5 / 60,
    )
    return {
        "nombre_images_valides": len(filtered),
        "images_occultees_ecartees": rejected_occlusion,
        "images_saut_aberrant_ecartees": rejected_jump,
        "posture_plus_defavorable": {
            "instant_s": float(filtered[worst_index]["time_s"]),
            "rula": scored[worst_index]["rula"]["score_probable"],
            "reba": scored[worst_index]["reba"]["score_probable"],
        },
        "posture_plus_frequente": {
            "instant_s": float(filtered[frequent_index]["time_s"]),
            "occurrences": signature_counts[common_signature],
        },
        "frequence_estimee_gestes_min": round(gesture_peaks / duration_minutes, 1),
        "repetitivite_superieure_4_min": gesture_peaks / duration_minutes > 4,
        "posture_statique_sup_60s": longest_static > 60,
        "duree_statique_max_s": round(longest_static, 1),
    }
