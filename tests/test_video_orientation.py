from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.analysis.video import open_video_capture, orient_video_frame


class FakeCapture:
    def __init__(self, orientation: float = 90, auto_orientation: float = 0) -> None:
        self.orientation = orientation
        self.auto_orientation = auto_orientation
        self.released = False
        self.set_calls: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return not self.released

    def release(self) -> None:
        self.released = True

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_ORIENTATION_AUTO:
            return self.auto_orientation
        if prop == cv2.CAP_PROP_ORIENTATION_META:
            return self.orientation
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        self.set_calls.append((prop, value))
        if prop == cv2.CAP_PROP_ORIENTATION_AUTO:
            self.auto_orientation = value
        return True


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (90, [[4, 1], [5, 2], [6, 3]]),
        (180, [[6, 5, 4], [3, 2, 1]]),
        (270, [[3, 6], [2, 5], [1, 4]]),
    ],
)
def test_orient_video_frame_applies_rotation_when_backend_does_not(
    orientation: int,
    expected: list[list[int]],
) -> None:
    capture = FakeCapture(orientation=orientation)
    frame = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)

    result = orient_video_frame(capture, frame)

    np.testing.assert_array_equal(result, np.array(expected, dtype=np.uint8))


def test_orient_video_frame_does_not_rotate_when_backend_already_applies_it() -> None:
    capture = FakeCapture(orientation=90, auto_orientation=1)
    frame = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)

    result = orient_video_frame(capture, frame)

    assert result is frame


def test_open_video_capture_prefers_ffmpeg_and_enables_auto_orientation(monkeypatch) -> None:
    capture = FakeCapture(auto_orientation=0)
    opened: list[tuple[object, ...]] = []

    def fake_video_capture(*args: object) -> FakeCapture:
        opened.append(args)
        return capture

    monkeypatch.setattr(cv2, "VideoCapture", fake_video_capture)

    result = open_video_capture("video.mp4")

    assert result is capture
    assert opened == [("video.mp4", cv2.CAP_FFMPEG)]
    assert capture.set_calls == [(cv2.CAP_PROP_ORIENTATION_AUTO, 1)]
