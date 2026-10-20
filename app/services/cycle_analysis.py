from __future__ import annotations

from statistics import mean, median, pstdev
from typing import Any


def suggest_cycles(
    phases: list[dict[str, Any]],
    min_stop_seconds: float = 2.0,
    min_cycle_seconds: float = 5.0,
) -> list[dict[str, float]]:
    """Propose des intervalles séparés par des arrêts prolongés, sans les valider."""
    ordered = sorted(phases, key=lambda phase: float(phase["debut_s"]))
    if not ordered:
        return []

    cycle_start = float(ordered[0]["debut_s"])
    candidates: list[dict[str, float]] = []
    for phase in ordered:
        start = float(phase["debut_s"])
        end = float(phase["fin_s"])
        is_long_stop = phase["type_auto"] == "stop" and end - start >= min_stop_seconds
        if not is_long_stop:
            continue
        if start - cycle_start >= min_cycle_seconds:
            candidates.append({"debut_s": cycle_start, "fin_s": start})
        cycle_start = max(cycle_start, end)

    final_end = float(ordered[-1]["fin_s"])
    if final_end - cycle_start >= min_cycle_seconds:
        candidates.append({"debut_s": cycle_start, "fin_s": final_end})
    return candidates


def cycle_duration_statistics(cycles: list[dict[str, Any]]) -> dict[str, float | int | None]:
    durations = [float(cycle["fin_s"]) - float(cycle["debut_s"]) for cycle in cycles]
    if not durations:
        return {
            "nombre": 0,
            "moyenne_s": None,
            "mediane_s": None,
            "minimum_s": None,
            "maximum_s": None,
            "ecart_type_s": None,
            "coefficient_variation_pct": None,
        }

    average = mean(durations)
    deviation = pstdev(durations) if len(durations) > 1 else None
    return {
        "nombre": len(durations),
        "moyenne_s": round(average, 2),
        "mediane_s": round(median(durations), 2),
        "minimum_s": round(min(durations), 2),
        "maximum_s": round(max(durations), 2),
        "ecart_type_s": round(deviation, 2) if deviation is not None else None,
        "coefficient_variation_pct": (
            round(deviation / average * 100, 2)
            if deviation is not None and average
            else None
        ),
    }
