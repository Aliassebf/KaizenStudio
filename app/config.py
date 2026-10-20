from __future__ import annotations

import os
import ipaddress
from pathlib import Path


def default_data_dir() -> Path:
    override = os.environ.get("KAIZEN_STUDIO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Kaizen Studio"

    return Path.home() / ".kaizen_studio"


DATA_DIR = default_data_dir()
DATABASE_PATH = DATA_DIR / "data" / "kaizen_studio.db"
VIDEO_ROOT = DATA_DIR / "videos"
EXPORT_ROOT = DATA_DIR / "exports"
TEMP_ROOT = DATA_DIR / "tmp"
MODEL_ROOT = DATA_DIR / "models"


def ensure_directories() -> None:
    for directory in (DATA_DIR, DATA_DIR / "data", VIDEO_ROOT, EXPORT_ROOT, TEMP_ROOT, MODEL_ROOT):
        directory.mkdir(parents=True, exist_ok=True)


def server_bind_configuration() -> tuple[str, str | None, str | None]:
    host = os.environ.get("KAIZEN_STUDIO_HOST", "127.0.0.1").strip()
    certfile = os.environ.get("KAIZEN_STUDIO_SSL_CERTFILE")
    keyfile = os.environ.get("KAIZEN_STUDIO_SSL_KEYFILE")
    allow_insecure_lan = os.environ.get("KAIZEN_STUDIO_ALLOW_INSECURE_LAN") == "1"
    if bool(certfile) != bool(keyfile):
        raise RuntimeError("Configurez à la fois KAIZEN_STUDIO_SSL_CERTFILE et KAIZEN_STUDIO_SSL_KEYFILE.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        if host.lower() != "localhost":
            raise RuntimeError(
                "KAIZEN_STUDIO_HOST doit être localhost ou une adresse IP privée explicite."
            ) from error
        address = ipaddress.ip_address("127.0.0.1")
    if not address.is_loopback:
        if address.version != 4 or not address.is_private or address.is_unspecified:
            raise RuntimeError("L'accès équipe doit être lié à une adresse IPv4 privée, jamais à une adresse publique.")
        if not certfile and not allow_insecure_lan:
            raise RuntimeError("HTTPS est obligatoire pour écouter sur le réseau local.")
        if not certfile and allow_insecure_lan:
            print(
                "AVERTISSEMENT : accès HTTP non chiffré sur le réseau local. "
                "Les identifiants, vidéos et données peuvent être interceptés."
            )
    if certfile and (not Path(certfile).is_file() or not Path(keyfile).is_file()):
        raise RuntimeError("Les fichiers du certificat TLS et de sa clé privée doivent exister.")
    return host, certfile, keyfile
