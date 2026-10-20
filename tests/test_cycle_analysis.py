from app.services.cycle_analysis import cycle_duration_statistics, suggest_cycles


def test_cycle_suggestions_split_at_long_stops_only():
    phases = [
        {"debut_s": 0, "fin_s": 8, "type_auto": "activity"},
        {"debut_s": 8, "fin_s": 11, "type_auto": "stop"},
        {"debut_s": 11, "fin_s": 14, "type_auto": "activity"},
        {"debut_s": 14, "fin_s": 15, "type_auto": "stop"},
        {"debut_s": 15, "fin_s": 25, "type_auto": "activity"},
    ]

    assert suggest_cycles(phases, min_stop_seconds=2, min_cycle_seconds=5) == [
        {"debut_s": 0.0, "fin_s": 8.0},
        {"debut_s": 11.0, "fin_s": 25.0},
    ]


def test_cycle_duration_statistics_avoid_claiming_variability_from_one_cycle():
    stats = cycle_duration_statistics([{"debut_s": 2, "fin_s": 7}])

    assert stats == {
        "nombre": 1,
        "moyenne_s": 5.0,
        "mediane_s": 5.0,
        "minimum_s": 5.0,
        "maximum_s": 5.0,
        "ecart_type_s": None,
        "coefficient_variation_pct": None,
    }
