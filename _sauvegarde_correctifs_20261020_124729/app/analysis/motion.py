"""Détection locale de mouvement (sans IA) et segmentation en phases.

Corrections par rapport à la version précédente :
- horodatage réel des images (vidéos VFR de smartphone) au lieu de ``index / fps`` ;
- la première phase commence au DÉBUT de la fenêtre (avant : au 2e échantillon,
  d'où un trou de 1 période d'échantillonnage) ;
- masque ROI pré-calculé une seule fois (avant : recalculé à chaque image) ;
- noyau de flou validé une fois (entier impair ≥ 1) ;
- suppression d'un calcul d'hystérésis mort (``labels`` jamais utilisé) ;
- la vidéo est toujours libérée (``try/finally``), y compris en cas d'erreur ;
- le seuil automatique est plancherisé pour éviter qu'une vidéo quasi statique
  ne génère des dizaines de micro-phases sur du bruit de capteur.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .base import AnalysisBackend, AnalysisParams, Phase
from .video import frame_timestamp_s, open_video_capture, orient_video_frame

RoiRectangle = tuple[float, float, float, float]
RoiSelection = RoiRectangle | tuple[RoiRectangle, ...]

ANALYSIS_WIDTH = 320
HYSTERESIS_LOW_RATIO = 0.6
MIN_AUTO_THRESHOLD = 0.002  # fraction de pixels


def parse_roi(
    roi: Optional[RoiRectangle | tuple[RoiRectangle, ...] | list | str],
) -> Optional[RoiSelection]:
    """Valide une ROI historique ou une liste de rectangles normalisés."""
    if roi is None:
        return None
    if isinstance(roi, str):
        stripped = roi.strip()
        if not stripped:
            return None
        if stripped.startswith("["):
            try:
                roi = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError("Format JSON invalide pour les zones d'intérêt.") from error
        else:
            try:
                roi = [float(part.strip()) for part in stripped.split(",")]
            except ValueError as error:
                raise ValueError("Les coordonnées de ROI doivent être numériques.") from error
    if not isinstance(roi, (list, tuple)) or not roi:
        raise ValueError("La ROI doit contenir un rectangle ou une liste de rectangles.")
    if len(roi) == 4 and all(isinstance(value, (int, float)) for value in roi):
        rectangles = [roi]
    else:
        rectangles = roi
    validated: list[RoiRectangle] = []
    for rectangle in rectangles:
        if not isinstance(rectangle, (list, tuple)) or len(rectangle) != 4:
            raise ValueError("Chaque ROI doit contenir x,y,largeur,hauteur.")
        try:
            x, y, width, height = (float(value) for value in rectangle)
        except (TypeError, ValueError) as error:
            raise ValueError("Les coordonnées de ROI doivent être numériques.") from error
        if not all(np.isfinite((x, y, width, height))):
            raise ValueError("Les coordonnées de ROI doivent être finies.")
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise ValueError("ROI hors limites : x,y doivent être dans [0,1] et largeur/hauteur > 0.")
        if x + width > 1.0 + 1e-6 or y + height > 1.0 + 1e-6:
            raise ValueError("ROI hors limites : x + largeur et y + hauteur doivent rester ≤ 1.")
        validated.append((x, y, width, height))
    if len(validated) > 16:
        raise ValueError("16 zones d'intérêt au maximum.")
    return validated[0] if len(validated) == 1 else tuple(validated)


def serialize_roi(roi: Optional[RoiSelection]) -> Optional[str]:
    """Conserve le format historique pour une zone et sérialise plusieurs zones en JSON."""
    if roi is None:
        return None
    if roi and isinstance(roi[0], tuple):
        return json.dumps(roi, separators=(",", ":"))
    return ",".join(str(value) for value in roi)


def roi_rectangles(roi: Optional[RoiSelection]) -> list[RoiRectangle]:
    """Normalise une sélection ROI en liste de rectangles (vide = image entière)."""
    if roi is None:
        return []
    if isinstance(roi[0], tuple):
        return list(roi)  # type: ignore[arg-type]
    return [roi]  # type: ignore[list-item]


def build_roi_mask(shape: tuple[int, int], roi: Optional[RoiSelection]) -> Optional[np.ndarray]:
    """Masque booléen (h, w) des zones d'intérêt ; None = toute l'image."""
    rectangles = roi_rectangles(roi)
    if not rectangles:
        return None
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    for x, y, roi_width, roi_height in rectangles:
        x0 = min(width - 1, int(x * width))
        y0 = min(height - 1, int(y * height))
        x1 = min(width, x0 + max(1, int(round(roi_width * width))))
        y1 = min(height, y0 + max(1, int(round(roi_height * height))))
        mask[y0:y1, x0:x1] = True
    return mask


def _odd_kernel(value: float | int) -> int:
    kernel = max(1, int(round(float(value))))
    return kernel if kernel % 2 else kernel + 1


def _fraction_to_threshold(value: Optional[float]) -> Optional[float]:
    """Convertit un seuil exprimé en pourcentage en fraction [0,1]."""
    if value is None:
        return None
    return float(value) / 100.0


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if values.size == 0:
        return values
    if window <= 1:
        return values.copy()
    kernel = np.ones(window, dtype=float) / window
    pad_left = window // 2
    pad_right = window - pad_left - 1
    padded = np.pad(values, (pad_left, pad_right), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: values.size]


def _hysteresis(labels: np.ndarray, threshold_high: float, threshold_low: float) -> list[bool]:
    if labels.size == 0:
        return []
    state = bool(labels[0] >= threshold_high)
    output = [state]
    for value in labels[1:]:
        if not state and value >= threshold_high:
            state = True
        elif state and value < threshold_low:
            state = False
        output.append(state)
    return output


def segment_motion_signal(
    samples: list[dict[str, float]],
    threshold_pct: float,
    min_duration: float,
    end_time: Optional[float] = None,
    start_time: Optional[float] = None,
) -> list[Phase]:
    """Recalcule les phases à partir du signal lissé, sans relire la vidéo.

    ``start_time`` (nouveau, optionnel) : début de la fenêtre analysée. S'il est
    fourni, la première phase démarre à cet instant et non au premier échantillon.
    """
    if not samples:
        return []
    if threshold_pct is None or not np.isfinite(threshold_pct) or threshold_pct <= 0:
        raise ValueError("Le seuil de mouvement doit être un pourcentage strictement positif.")
    times = np.asarray([sample["time_s"] for sample in samples], dtype=float)
    scores_pct = np.asarray([sample["motion_pct"] for sample in samples], dtype=float)
    if times.size > 1:
        time_deltas = np.diff(times)
        if np.any(time_deltas <= 0):
            raise ValueError("Les instants du signal doivent être strictement croissants.")
        sample_period = float(np.median(time_deltas))
    else:
        sample_period = 0.2
    scores = scores_pct / 100.0
    threshold_high = threshold_pct / 100.0
    labels = _hysteresis(scores, threshold_high, HYSTERESIS_LOW_RATIO * threshold_high)
    phases: list[dict] = []
    current_label = labels[0]
    first_start = float(times[0])
    if start_time is not None and 0 <= float(start_time) < first_start:
        first_start = float(start_time)
    segment_start = first_start
    for index in range(1, len(labels)):
        if labels[index] != current_label:
            segment_end = float(times[index - 1] + sample_period)
            phases.append(
                {"start": segment_start, "end": segment_end, "type": "activity" if current_label else "stop"}
            )
            segment_start = segment_end
            current_label = labels[index]
    final_end = float(times[-1] + sample_period)
    if end_time is not None:
        final_end = max(final_end, float(end_time))
    phases.append({"start": segment_start, "end": final_end, "type": "activity" if current_label else "stop"})
    phases = _merge_short_phases(phases, max(0.0, float(min_duration)))
    output: list[Phase] = []
    for phase in phases:
        if phase["end"] <= phase["start"]:
            continue
        indices = np.where((times >= phase["start"]) & (times <= phase["end"]))[0]
        mean_motion = float(np.mean(scores_pct[indices])) if indices.size else 0.0
        output.append(Phase(start=phase["start"], end=phase["end"], type=phase["type"], motion_mean_pct=mean_motion))
    return output


def _merge_short_phases(phases: list[dict], min_duration: float) -> list[dict]:
    """Fusionne les phases trop courtes avec la voisine la plus longue, puis les voisines de même type."""
    result = [dict(phase) for phase in phases]
    while True:
        short_index = next(
            (idx for idx, phase in enumerate(result) if phase["end"] - phase["start"] < min_duration), None
        )
        if short_index is None or len(result) == 1:
            break
        if short_index == 0:
            result[1]["start"] = result[0]["start"]
            result.pop(0)
        elif short_index == len(result) - 1:
            result[-2]["end"] = result[-1]["end"]
            result.pop()
        else:
            left = result[short_index - 1]
            right = result[short_index + 1]
            if (left["end"] - left["start"]) >= (right["end"] - right["start"]):
                left["end"] = result[short_index]["end"]
            else:
                right["start"] = result[short_index]["start"]
            result.pop(short_index)
    # Après absorption, deux voisines peuvent avoir le même type : on les recolle.
    merged: list[dict] = []
    for phase in result:
        if merged and merged[-1]["type"] == phase["type"]:
            merged[-1]["end"] = phase["end"]
        else:
            merged.append(phase)
    return merged


class MotionAnalysisBackend(AnalysisBackend):
    """Mesure locale de mouvement (sans IA), adaptée au poste existant en production."""

    name = "motion"

    def analyze(
        self,
        video_path: str | Path,
        params: AnalysisParams,
        progress_callback: Optional[Callable[[float], None]] = None,
        signal_callback: Optional[Callable[[list[dict[str, float]], float], None]] = None,
    ) -> list[Phase]:
        video = Path(video_path)
        if not video.exists():
            raise FileNotFoundError(f"Vidéo introuvable : {video}")
        cap = open_video_capture(video)
        try:
            if not cap.isOpened():
                raise OSError(f"Impossible d'ouvrir la vidéo : {video}")
            times, scores, end = self._measure(cap, params, progress_callback)
        finally:
            cap.release()

        if not scores:
            raise ValueError("Aucune image exploitable pour le calcul du mouvement.")
        times_arr = np.asarray(times, dtype=float)
        scores_arr = np.asarray(scores, dtype=float)
        sample_period = float(np.median(np.diff(times_arr))) if times_arr.size > 1 else 1.0 / max(params.fps, 1.0)
        smoothing_window = max(1, int(round(float(params.smooth_seconds) / max(sample_period, 1e-3))))
        smoothed = _moving_average(scores_arr, smoothing_window)

        threshold_high = _fraction_to_threshold(params.auto_threshold_pct)
        if threshold_high is None:
            threshold_high = max(MIN_AUTO_THRESHOLD, 0.2 * float(np.percentile(smoothed, 90)))

        signal = [
            {"time_s": round(float(time_s), 3), "motion_pct": float(score * 100.0)}
            for time_s, score in zip(times_arr, smoothed)
        ]
        if signal_callback:
            signal_callback(signal, threshold_high * 100.0)
        phase_records = segment_motion_signal(
            signal,
            threshold_high * 100.0,
            params.min_phase_seconds,
            end_time=end,
            start_time=float(params.start),
        )
        if progress_callback:
            progress_callback(1.0)
        return phase_records

    @staticmethod
    def _measure(
        cap: cv2.VideoCapture,
        params: AnalysisParams,
        progress_callback: Optional[Callable[[float], None]],
    ) -> tuple[list[float], list[float], float]:
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        total_duration = frame_count / source_fps if frame_count else 0.0
        start = float(params.start)
        end = float(params.end) if params.end is not None else total_duration
        if end <= start:
            raise ValueError(f"Fenêtre invalide ({start}s -> {end}s).")
        end = min(end, total_duration) if total_duration else end
        sample_period = 1.0 / max(1.0, float(params.fps))
        blur_kernel = _odd_kernel(params.blur)
        roi_selection = parse_roi(params.roi)

        if start > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        frame_index = int(start * source_fps)

        times: list[float] = []
        scores: list[float] = []
        previous_gray: Optional[np.ndarray] = None
        roi_mask: Optional[np.ndarray] = None
        next_sample_time = start
        window = max(end - start, 1e-6)
        while True:
            if not cap.grab():
                break
            timestamp = frame_timestamp_s(cap, frame_index, source_fps)
            frame_index += 1
            if timestamp > end + 1e-6:
                break
            if timestamp + 1e-6 < next_sample_time:
                continue
            ok_read, image = cap.retrieve()
            if not ok_read:
                continue
            next_sample_time = max(next_sample_time + sample_period, timestamp + sample_period * 0.5)
            image = orient_video_frame(cap, image)
            height, width = image.shape[:2]
            resized_height = max(1, int(height * (ANALYSIS_WIDTH / max(width, 1))))
            resized = cv2.resize(image, (ANALYSIS_WIDTH, resized_height), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
            if roi_mask is None and roi_selection is not None:
                roi_mask = build_roi_mask(gray.shape, roi_selection)
            if previous_gray is not None and previous_gray.shape == gray.shape:
                changed_pixels = cv2.absdiff(gray, previous_gray) > params.pixel_threshold
                score = float(np.mean(changed_pixels[roi_mask])) if roi_mask is not None else float(np.mean(changed_pixels))
                times.append(timestamp)
                scores.append(score)
            previous_gray = gray
            if progress_callback:
                progress_callback(min(0.8, 0.8 * (timestamp - start) / window))
        return times, scores, end
