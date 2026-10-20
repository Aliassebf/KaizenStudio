"""Suivi local de posture (MediaPipe) : points d'articulation et angles 2D estimés.

Les angles sont calculés en PIXELS (et non sur les coordonnées normalisées
MediaPipe x/largeur, y/hauteur, qui déformaient les angles selon le format de
l'image : en 1920×1080, un tronc à 20° sortait à ≈ 12° en paysage, ≈ 33° en portrait).
Seules les images échantillonnées sont décodées ; horodatage réel des images.
Format de sortie inchangé : time_s, width, height, points, angles.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import cv2

from .video import frame_timestamp_s, open_video_capture, orient_video_frame

POSE_LANDMARKS = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}
MIN_VISIBILITY = 0.35
MAX_PROCESS_WIDTH = 640

Point = tuple[float, float]

_JOINT_ANGLES: dict[str, tuple[str, str, str]] = {
    "left_elbow": ("left_elbow", "left_shoulder", "left_wrist"),
    "right_elbow": ("right_elbow", "right_shoulder", "right_wrist"),
    "left_shoulder": ("left_shoulder", "left_hip", "left_elbow"),
    "right_shoulder": ("right_shoulder", "right_hip", "right_elbow"),
    "left_knee": ("left_knee", "left_hip", "left_ankle"),
    "right_knee": ("right_knee", "right_hip", "right_ankle"),
}


def angle_degrees(first: Point | None, vertex: Point | None, last: Point | None) -> float | None:
    """Angle 2D au sommet, en degrés."""
    if first is None or vertex is None or last is None:
        return None
    ax, ay = first[0] - vertex[0], first[1] - vertex[1]
    bx, by = last[0] - vertex[0], last[1] - vertex[1]
    magnitude = math.hypot(ax, ay) * math.hypot(bx, by)
    if magnitude == 0:
        return None
    cosine = max(-1.0, min(1.0, (ax * bx + ay * by) / magnitude))
    return math.degrees(math.acos(cosine))


def _midpoint(first: Point | None, second: Point | None) -> Point | None:
    if first is None or second is None:
        return None
    return ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)


def _inclination_from_vertical(upper: Point | None, lower: Point | None) -> float | None:
    if upper is None or lower is None:
        return None
    dx, dy = upper[0] - lower[0], upper[1] - lower[1]
    if dx == 0 and dy == 0:
        return None
    return round(math.degrees(math.atan2(abs(dx), abs(dy))), 1)


def compute_angles(points: dict[str, dict[str, float]], width: int, height: int) -> dict[str, float | None]:
    """Angles articulaires à partir de points normalisés, recalculés en pixels."""

    def pixel(name: str) -> Point | None:
        value = points.get(name)
        if value is None or value["visibility"] < MIN_VISIBILITY:
            return None
        return value["x"] * width, value["y"] * height

    angles: dict[str, float | None] = {
        key: angle_degrees(pixel(first), pixel(vertex), pixel(last))
        for key, (vertex, first, last) in _JOINT_ANGLES.items()
    }
    shoulder_mid = _midpoint(pixel("left_shoulder"), pixel("right_shoulder"))
    hip_mid = _midpoint(pixel("left_hip"), pixel("right_hip"))
    angles["trunk_inclination"] = _inclination_from_vertical(shoulder_mid, hip_mid)
    return {key: None if value is None else round(value, 1) for key, value in angles.items()}


def analyze_posture_video(
    video_path: str | Path,
    start_s: float,
    end_s: float,
    sample_fps: float = 2.0,
    progress_callback: Callable[[float], None] | None = None,
) -> list[dict[str, object]]:
    """Extrait localement des points de pose et des angles 2D échantillonnés."""
    try:
        import mediapipe as mp
    except ImportError as error:
        raise RuntimeError(
            "MediaPipe n'est pas installé. Installez les dépendances de Kaizen Studio puis relancez."
        ) from error
    if sample_fps <= 0:
        raise ValueError("La fréquence d'échantillonnage doit être positive.")
    capture = open_video_capture(video_path)
    try:
        if not capture.isOpened():
            raise RuntimeError("Impossible d'ouvrir la vidéo pour le suivi de posture.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or frame_count <= 0:
            raise RuntimeError("La vidéo ne fournit pas une durée ou une fréquence d'images valide.")
        duration_s = frame_count / fps
        start_s = max(0.0, min(float(start_s), duration_s))
        end_s = min(float(end_s), duration_s)
        if end_s <= start_s:
            raise ValueError("La fenêtre de suivi doit être valide et non vide.")
        if start_s > 0:
            capture.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
        frame_index = int(round(start_s * fps))
        period = 1.0 / sample_fps
        next_sample_time = start_s
        window = end_s - start_s
        samples: list[dict[str, object]] = []
        with mp.solutions.pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as pose:
            while True:
                if not capture.grab():
                    break
                timestamp = frame_timestamp_s(capture, frame_index, fps)
                frame_index += 1
                if timestamp > end_s + 1e-6:
                    break
                if timestamp + 1e-6 < next_sample_time:
                    continue
                ok, frame = capture.retrieve()
                if not ok:
                    continue
                next_sample_time = max(next_sample_time + period, timestamp + period * 0.5)
                frame = orient_video_frame(capture, frame)
                height, width = frame.shape[:2]
                if width > MAX_PROCESS_WIDTH:
                    height = round(height * MAX_PROCESS_WIDTH / width)
                    width = MAX_PROCESS_WIDTH
                    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                result = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if result.pose_landmarks:
                    raw = result.pose_landmarks.landmark
                    points = {
                        name: {
                            "x": round(float(raw[index].x), 5),
                            "y": round(float(raw[index].y), 5),
                            "visibility": round(float(raw[index].visibility), 3),
                        }
                        for name, index in POSE_LANDMARKS.items()
                    }
                    samples.append(
                        {
                            "time_s": round(timestamp, 2),
                            "width": width,
                            "height": height,
                            "points": points,
                            "angles": compute_angles(points, width, height),
                        }
                    )
                if progress_callback:
                    progress_callback(min(0.99, (timestamp - start_s) / window))
    finally:
        capture.release()
    if progress_callback:
        progress_callback(1.0)
    return samples
