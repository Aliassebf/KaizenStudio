from __future__ import annotations

import subprocess

import pytest

import kaizen_studio_exe


def test_configure_local_mode_clears_lan_and_tls_settings(monkeypatch):
    monkeypatch.setenv("KAIZEN_STUDIO_SSL_CERTFILE", "server.crt")
    monkeypatch.setenv("KAIZEN_STUDIO_SSL_KEYFILE", "server.key")
    monkeypatch.setenv("KAIZEN_STUDIO_ALLOW_INSECURE_LAN", "1")
    monkeypatch.setenv("KAIZEN_STUDIO_COOKIE_SECURE", "1")

    kaizen_studio_exe.configure_server_mode("127.0.0.1", allow_insecure_lan=False)

    assert kaizen_studio_exe.os.environ["KAIZEN_STUDIO_HOST"] == "127.0.0.1"
    assert "KAIZEN_STUDIO_SSL_CERTFILE" not in kaizen_studio_exe.os.environ
    assert "KAIZEN_STUDIO_SSL_KEYFILE" not in kaizen_studio_exe.os.environ
    assert "KAIZEN_STUDIO_ALLOW_INSECURE_LAN" not in kaizen_studio_exe.os.environ
    assert "KAIZEN_STUDIO_COOKIE_SECURE" not in kaizen_studio_exe.os.environ


def test_configure_lan_mode_requires_explicit_http_opt_in(monkeypatch):
    kaizen_studio_exe.configure_server_mode("192.168.1.20", allow_insecure_lan=True)

    assert kaizen_studio_exe.os.environ["KAIZEN_STUDIO_HOST"] == "192.168.1.20"
    assert kaizen_studio_exe.os.environ["KAIZEN_STUDIO_ALLOW_INSECURE_LAN"] == "1"
    assert kaizen_studio_exe.os.environ["KAIZEN_STUDIO_COOKIE_SECURE"] == "0"
    assert "KAIZEN_STUDIO_SSL_CERTFILE" not in kaizen_studio_exe.os.environ
    assert "KAIZEN_STUDIO_SSL_KEYFILE" not in kaizen_studio_exe.os.environ


def test_private_ipv4_detection_rejects_public_addresses(monkeypatch):
    class CompletedProcess:
        stdout = "8.8.8.8\n"

    monkeypatch.setattr(kaizen_studio_exe.subprocess, "run", lambda *_args, **_kwargs: CompletedProcess())

    with pytest.raises(RuntimeError, match="pas une adresse IPv4 privée"):
        kaizen_studio_exe.detect_private_ipv4()


def test_private_ipv4_detection_reports_missing_network(monkeypatch):
    def fail_to_detect(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "powershell")

    monkeypatch.setattr(kaizen_studio_exe.subprocess, "run", fail_to_detect)

    with pytest.raises(subprocess.CalledProcessError):
        kaizen_studio_exe.detect_private_ipv4()
