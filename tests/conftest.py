from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.db as database
import app.main as main_module
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main_module, "EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(main_module, "VIDEO_ROOT", tmp_path / "videos")
    with TestClient(app, client=("127.0.0.1", 8000)) as test_client:
        setup = test_client.post(
            "/api/auth/setup",
            json={"username": "pytest-admin", "password": "pytest-admin-password"},
        )
        assert setup.status_code == 201, setup.text
        yield test_client
