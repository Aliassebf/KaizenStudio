from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.auth import login_is_rate_limited, record_failed_login

import app.db as database
from app.config import server_bind_configuration
import app.main as main_module
from app.main import app


def test_first_run_setup_creates_admin_and_secures_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "setup.db")
    monkeypatch.setattr(main_module, "EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(main_module, "VIDEO_ROOT", tmp_path / "videos")

    with TestClient(app, client=("127.0.0.1", 8000)) as client:
        assert client.get("/api/auth/status").json() == {"setup_required": True}
        assert client.get("/api/auth/status").headers["cache-control"] == "no-store"
        assert client.get("/").url.path == "/setup"
        assert client.get("/api/projects").status_code == 503

        setup = client.post(
            "/api/auth/setup",
            json={"username": "admin.local", "password": "a-strong-admin-password"},
        )
        assert setup.status_code == 201, setup.text
        assert setup.json()["is_admin"] is True
        assert client.cookies.get("kaizen_session")
        assert "httponly" in setup.headers["set-cookie"].lower()
        assert "samesite=strict" in setup.headers["set-cookie"].lower()
        assert setup.headers["cache-control"] == "no-store"
        assert client.get("/api/auth/status").json() == {"setup_required": False}
        assert client.get("/api/auth/me").json()["username"] == "admin.local"
        assert client.post(
            "/api/auth/setup",
            json={"username": "attacker", "password": "another-strong-password"},
        ).status_code == 409


def test_initial_admin_claims_projects_from_pre_auth_database(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                takt_s REAL NOT NULL,
                cree_le TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO projects (nom, takt_s) VALUES ('Etude existante', 60)"
        )
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)
    monkeypatch.setattr(main_module, "EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(main_module, "VIDEO_ROOT", tmp_path / "videos")

    with TestClient(app, client=("127.0.0.1", 8000)) as client:
        setup = client.post(
            "/api/auth/setup",
            json={"username": "legacy-admin", "password": "legacy-admin-password"},
        )
        assert setup.status_code == 201, setup.text
        projects = client.get("/api/projects")
        assert projects.status_code == 200, projects.text
        assert [project["nom"] for project in projects.json()] == ["Etude existante"]


def test_initial_admin_cannot_be_claimed_from_another_computer(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "remote-setup.db")
    monkeypatch.setattr(main_module, "EXPORT_ROOT", tmp_path / "exports")
    monkeypatch.setattr(main_module, "VIDEO_ROOT", tmp_path / "videos")

    with TestClient(app, client=("192.168.1.50", 8000)) as remote_client:
        setup = remote_client.post(
            "/api/auth/setup",
            json={"username": "remote-admin", "password": "another-strong-password"},
        )
        assert setup.status_code == 403
        assert remote_client.get("/api/auth/status").json() == {"setup_required": True}


def test_lan_binding_requires_a_private_ip_and_tls_certificate(tmp_path, monkeypatch):
    monkeypatch.delenv("KAIZEN_STUDIO_HOST", raising=False)
    monkeypatch.delenv("KAIZEN_STUDIO_SSL_CERTFILE", raising=False)
    monkeypatch.delenv("KAIZEN_STUDIO_SSL_KEYFILE", raising=False)
    monkeypatch.delenv("KAIZEN_STUDIO_ALLOW_INSECURE_LAN", raising=False)
    assert server_bind_configuration() == ("127.0.0.1", None, None)

    monkeypatch.setenv("KAIZEN_STUDIO_HOST", "192.168.1.20")
    with pytest.raises(RuntimeError, match="HTTPS"):
        server_bind_configuration()

    monkeypatch.setenv("KAIZEN_STUDIO_ALLOW_INSECURE_LAN", "1")
    assert server_bind_configuration() == ("192.168.1.20", None, None)

    certificate = tmp_path / "server.crt"
    private_key = tmp_path / "server.key"
    certificate.write_text("certificate")
    private_key.write_text("private key")
    monkeypatch.setenv("KAIZEN_STUDIO_SSL_CERTFILE", str(certificate))
    monkeypatch.setenv("KAIZEN_STUDIO_SSL_KEYFILE", str(private_key))
    assert server_bind_configuration() == ("192.168.1.20", str(certificate), str(private_key))

    monkeypatch.setenv("KAIZEN_STUDIO_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="privée"):
        server_bind_configuration()

    monkeypatch.setenv("KAIZEN_STUDIO_HOST", "8.8.8.8")
    with pytest.raises(RuntimeError, match="privée"):
        server_bind_configuration()


def test_login_attempts_are_rate_limited():
    username = "rate-limit-test-user"
    remote_ip = "192.0.2.77"
    assert not login_is_rate_limited(username, remote_ip)
    for _ in range(10):
        record_failed_login(username, remote_ip)
    assert login_is_rate_limited(username, remote_ip)


def test_local_login_admin_management_and_private_project_isolation(client):
    created_user = client.post(
        "/api/admin/users",
        json={"username": "operator.local", "password": "a-strong-user-password"},
    )
    assert created_user.status_code == 201, created_user.text
    assert created_user.json()["is_admin"] is False

    admin_project = client.post(
        "/api/projects",
        json={"nom": "Projet administrateur", "takt_s": 60},
    ).json()
    admin_station = client.post(
        f"/api/projects/{admin_project['id']}/stations",
        json={"nom": "Poste confidentiel"},
    ).json()
    admin_cycle = client.post(
        f"/api/stations/{admin_station['id']}/cycles",
        json={"debut_s": 0, "fin_s": 10},
    ).json()
    assert admin_cycle["source"] == "manual"

    client.cookies.clear()
    assert client.get("/api/projects").status_code == 401
    user_login = client.post(
        "/api/auth/login",
        json={"username": "operator.local", "password": "a-strong-user-password"},
    )
    assert user_login.status_code == 200, user_login.text
    assert user_login.json()["is_admin"] is False
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{admin_project['id']}").status_code == 404
    assert client.get(f"/api/stations/{admin_station['id']}").status_code == 404
    assert client.get(f"/api/stations/{admin_station['id']}/cycles").status_code == 404
    assert client.get(f"/projects/{admin_project['id']}/summary").status_code == 404
    assert client.get(f"/review/{admin_station['id']}").status_code == 404
    assert client.get(f"/api/stations/{admin_station['id']}/video").status_code == 404
    assert client.get("/api/settings").status_code == 403
    user_project = client.post(
        "/api/projects",
        json={"nom": "Projet utilisateur", "takt_s": 45},
    ).json()
    assert [item["id"] for item in client.get("/api/projects").json()] == [user_project["id"]]
    assert client.get("/admin/users").status_code == 403

    assert client.post("/api/auth/logout").status_code == 200
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "pytest-admin", "password": "pytest-admin-password"},
    )
    assert admin_login.status_code == 200
    assert [item["id"] for item in client.get("/api/projects").json()] == [admin_project["id"]]


def test_admin_can_create_another_admin(client):
    created_admin = client.post(
        "/api/admin/users",
        json={
            "username": "second.admin",
            "password": "a-strong-admin-password",
            "is_admin": True,
        },
    )

    assert created_admin.status_code == 201, created_admin.text
    assert created_admin.json()["is_admin"] is True
    assert sum(user["is_admin"] for user in client.get("/api/admin/users").json()) == 2

    assert client.post("/api/auth/logout").status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"username": "second.admin", "password": "a-strong-admin-password"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["is_admin"] is True
    assert client.get("/api/admin/users").status_code == 200


def test_password_change_and_account_deactivation_revoke_sessions(client):
    account = client.post(
        "/api/admin/users",
        json={"username": "operator.reset", "password": "initial-user-password"},
    ).json()

    login = client.post(
        "/api/auth/login",
        json={"username": "operator.reset", "password": "initial-user-password"},
    )
    assert login.status_code == 200
    changed = client.put(
        "/api/auth/password",
        json={
            "current_password": "initial-user-password",
            "new_password": "replacement-password",
        },
    )
    assert changed.status_code == 200
    assert client.get("/api/projects").status_code == 401

    assert client.post(
        "/api/auth/login",
        json={"username": "operator.reset", "password": "replacement-password"},
    ).status_code == 200
    previous_session = client.cookies.get("kaizen_session")
    disabled = client.patch(
        f"/api/admin/users/{account['id']}/active",
        json={"is_active": False},
    )
    assert disabled.status_code == 403

    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": "pytest-admin", "password": "pytest-admin-password"},
    ).status_code == 200
    disabled = client.patch(
        f"/api/admin/users/{account['id']}/active",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": "operator.reset", "password": "replacement-password"},
    ).status_code == 401
    client.cookies.set("kaizen_session", previous_session)
    assert client.get("/api/projects").status_code == 401


def test_admin_can_reset_own_password_and_must_log_in_again(client):
    reset = client.put(
        "/api/admin/users/1/password",
        json={"new_password": "new-admin-password"},
    )

    assert reset.status_code == 200, reset.text
    assert client.get("/api/projects").status_code == 401
    login = client.post(
        "/api/auth/login",
        json={"username": "pytest-admin", "password": "new-admin-password"},
    )
    assert login.status_code == 200, login.text
