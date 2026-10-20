"""Lecture vidéo commune (OpenCV) : ouverture, orientation, horodatage fiable.

Nouveautés :
- ``opened_video()`` : gestionnaire de contexte qui garantit ``release()`` ;
- ``read_video_metadata()`` : FPS/durée en un seul endroit (plus de copier-coller
  dans main.py, motion.py, posture.py, operation_learning.py) ;
- ``frame_timestamp_s()`` : horodatage réel de l'image (CAP_PROP_POS_MSEC).
  Les vidéos de smartphone sont souvent à fréquence VARIABLE (VFR) : calculer
  ``index / fps`` introduit une dérive de plusieurs secondes sur une longue vidéo,
  ce qui fausse directement les temps d'étapes.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from os import PathLike
from typing import Iterator

import cv2
import numpy as np


def open_video_capture(video_path: str | PathLike[str]) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(str(video_path))
    if capture.isOpened():
        capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    return capture


@contextmanager
def opened_video(video_path: str | PathLike[str]) -> Iterator[cv2.VideoCapture]:
    """``with opened_video(p) as cap:`` — lève OSError si illisible, libère toujours."""
    capture = open_video_capture(video_path)
    try:
        if not capture.isOpened():
            raise OSError(f"Impossible d'ouvrir la vidéo : {video_path}")
        yield capture
    finally:
        capture.release()


def orient_video_frame(capture: cv2.VideoCapture, frame: np.ndarray) -> np.ndarray:
    if capture.get(cv2.CAP_PROP_ORIENTATION_AUTO) >= 0.5:
        return frame
    orientation = int(round(capture.get(cv2.CAP_PROP_ORIENTATION_META))) % 360
    if orientation == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if orientation == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


@dataclass(frozen=True)
class VideoMetadata:
    fps: float
    frame_count: int
    duration_s: float


def read_video_metadata(capture: cv2.VideoCapture) -> VideoMetadata:
    """FPS et durée ; lève ValueError si la vidéo ne les fournit pas."""
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or frame_count <= 0:
        raise ValueError("La vidéo ne fournit pas une durée ou une fréquence d'images valide.")
    return VideoMetadata(fps=fps, frame_count=frame_count, duration_s=frame_count / fps)


def frame_timestamp_s(capture: cv2.VideoCapture, frame_index: int, fps: float) -> float:
    """Horodatage de la DERNIÈRE image lue (grab/read).

    OpenCV/FFmpeg renvoie dans CAP_PROP_POS_MSEC le PTS de l'image courante.
    Repli sur ``index / fps`` si le backend ne fournit pas l'information.
    """
    position_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
    if position_ms > 0 or frame_index == 0:
        return position_ms / 1000.0
    return frame_index / fps if fps > 0 else 0.0
