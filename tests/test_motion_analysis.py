from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.analysis.azure_vision import AzureVisionBackend
from app.analysis.base import AnalysisParams
from app.analysis.motion import MotionAnalysisBackend, _merge_short_phases, parse_roi, serialize_roi


def _build_synthetic_video(path: Path) -> None:
    width, height = 320, 180
    fps = 25
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Impossible de créer la vidéo de test : {path}")

    for frame_idx in range(int(12 * fps)):
        time_s = frame_idx / fps
        image = np.full((height, width, 3), 60, dtype=np.uint8)

        active = (0.0 <= time_s < 2.0) or (4.0 <= time_s < 6.0) or (8.0 <= time_s < 10.0)
        if active:
            offset = int((frame_idx * 6) % (width - 80))
            cv2.rectangle(image, (offset, 30), (offset + 80, 120), (255, 255, 255), -1)
            cv2.circle(image, (220, 100), 30, (220, 220, 220), -1)
        writer.write(image)

    writer.release()


def test_motion_backend_detects_known_activity_windows(tmp_path):
    video_path = tmp_path / "synthetic_motion.avi"
    _build_synthetic_video(video_path)

    backend = MotionAnalysisBackend()
    params = AnalysisParams(
        fps=5.0,
        start=0.0,
        end=12.0,
        roi=None,
        pixel_threshold=25,
        blur=5,
        smooth_seconds=0.6,
        min_phase_seconds=1.0,
    )

    phases = backend.analyze(video_path, params)

    assert phases
    assert all(phase.start <= phase.end for phase in phases)
    assert {phase.type for phase in phases} <= {"activity", "stop"}

    expected_windows = [(0.0, 2.0), (4.0, 6.0), (8.0, 10.0)]
    for expected_start, expected_end in expected_windows:
        assert any(
            phase.type == "activity" and phase.start <= expected_start + 0.5 and phase.end >= expected_end - 0.5
            for phase in phases
        ), f"Aucune phase d'activité détectée autour de {expected_start}s / {expected_end}s"


def test_merge_short_phases_fuses_briefs_phases():
    phases = [
        {"start": 0.0, "end": 0.7, "type": "activity"},
        {"start": 0.7, "end": 2.2, "type": "stop"},
        {"start": 2.2, "end": 2.9, "type": "activity"},
    ]

    merged = _merge_short_phases(phases, 1.0)

    assert len(merged) <= 2
    assert merged[0]["start"] <= 0.0
    assert merged[-1]["end"] >= 2.9


def test_parse_and_serialize_multiple_roi_rectangles():
    expected = ((0.1, 0.2, 0.3, 0.4), (0.6, 0.1, 0.2, 0.5))
    parsed = parse_roi('[[0.1,0.2,0.3,0.4],[0.6,0.1,0.2,0.5]]')

    assert parsed == expected
    assert parse_roi(serialize_roi(parsed)) == expected
    assert parse_roi("0.1,0.2,0.3,0.4") == expected[0]


def test_motion_backend_accepts_multiple_roi_rectangles(tmp_path):
    video_path = tmp_path / "synthetic_motion_roi.avi"
    _build_synthetic_video(video_path)
    params = AnalysisParams(
        fps=5.0,
        start=0.0,
        end=12.0,
        roi=((0.0, 0.0, 0.25, 1.0), (0.75, 0.0, 0.25, 1.0)),
        min_phase_seconds=1.0,
    )

    phases = MotionAnalysisBackend().analyze(video_path, params)

    assert phases
    assert all(phase.start <= phase.end for phase in phases)


def test_multiple_rois_ignore_movement_outside_selected_areas(tmp_path):
    video_path = tmp_path / "motion_outside_roi.avi"
    width, height, fps = 320, 180, 25
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Impossible de créer la vidéo de test : {video_path}")
    for frame_idx in range(4 * fps):
        image = np.full((height, width, 3), 60, dtype=np.uint8)
        x = 110 + (frame_idx * 3) % 80
        cv2.rectangle(image, (x, 45), (x + 30, 135), (255, 255, 255), -1)
        writer.write(image)
    writer.release()

    signals = []
    params = AnalysisParams(
        fps=5.0,
        start=0.0,
        end=4.0,
        roi=((0.0, 0.0, 0.25, 1.0), (0.75, 0.0, 0.25, 1.0)),
        min_phase_seconds=0.2,
    )
    MotionAnalysisBackend().analyze(
        video_path,
        params,
        signal_callback=lambda samples, threshold: signals.extend(samples),
    )

    assert signals
    assert max(sample["motion_pct"] for sample in signals) == 0.0


def test_azure_backend_is_disabled_by_default():
    backend = AzureVisionBackend()
    with pytest.raises(RuntimeError, match="désactivé|approbation"):
        backend.analyze("ignored.mp4", AnalysisParams())
