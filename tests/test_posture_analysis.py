from __future__ import annotations

import pytest

from app.analysis.posture import angle_degrees


def test_angle_degrees_measures_joint_angle_in_image_plane():
    assert angle_degrees((0.0, 1.0), (0.0, 0.0), (1.0, 0.0)) == pytest.approx(90.0)
    assert angle_degrees((-1.0, 0.0), (0.0, 0.0), (1.0, 0.0)) == pytest.approx(180.0)


def test_angle_degrees_returns_none_for_degenerate_segment():
    assert angle_degrees((0.0, 0.0), (0.0, 0.0), (1.0, 0.0)) is None
