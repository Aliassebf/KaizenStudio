from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from .config import server_bind_configuration


HOST, CERTFILE, KEYFILE = server_bind_configuration()
PORT = 8000
SCHEME = "https" if CERTFILE else "http"
URL = f"{SCHEME}://{HOST}:{PORT}/"


def _open_browser_when_ready() -> None:
    health_url = f"{SCHEME}://{HOST}:{PORT}/api/health"
    for _ in range(60):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(URL)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    print(f"Kaizen Studio est lancé, mais l'ouverture automatique du navigateur a échoué. Ouvrez {URL}")


def main() -> None:
    access_mode = "ordinateur" if HOST == "127.0.0.1" else "réseau local configuré"
    print(f"Kaizen Studio démarre sur {URL} (accès limité à cet {access_mode}).")
    if HOST != "127.0.0.1" and not CERTFILE:
        print(
            "AVERTISSEMENT DE SÉCURITÉ : HTTP n'est pas chiffré. "
            "Les identifiants, vidéos et données peuvent être interceptés. "
            "Utilisez uniquement un réseau privé isolé et faites filtrer le port 8000 par l'IT."
        )
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        ssl_certfile=CERTFILE,
        ssl_keyfile=KEYFILE,
    )


if __name__ == "__main__":
    main()
