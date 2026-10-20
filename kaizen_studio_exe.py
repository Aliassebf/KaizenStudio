from __future__ import annotations

import ipaddress
import os
import subprocess
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable

import uvicorn


PORT = 8000


def detect_private_ipv4() -> str:
    command = (
        "$config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address }; "
        "$config | ForEach-Object { $_.IPv4Address } | "
        "Where-Object { $_.IPAddress -notlike '169.254.*' } | "
        "Select-Object -First 1 -ExpandProperty IPAddress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    address = result.stdout.strip()
    try:
        parsed_address = ipaddress.ip_address(address)
    except ValueError as error:
        raise RuntimeError("Aucune adresse IPv4 valide du réseau local n'a été détectée.") from error
    if parsed_address.version != 4 or not parsed_address.is_private or parsed_address.is_unspecified:
        raise RuntimeError("L'adresse détectée n'est pas une adresse IPv4 privée utilisable.")
    return str(parsed_address)


def configure_server_mode(host: str, allow_insecure_lan: bool) -> None:
    os.environ["KAIZEN_STUDIO_HOST"] = host
    os.environ.pop("KAIZEN_STUDIO_SSL_CERTFILE", None)
    os.environ.pop("KAIZEN_STUDIO_SSL_KEYFILE", None)
    os.environ.pop("KAIZEN_STUDIO_ALLOW_INSECURE_LAN", None)
    os.environ.pop("KAIZEN_STUDIO_COOKIE_SECURE", None)
    if allow_insecure_lan:
        os.environ["KAIZEN_STUDIO_ALLOW_INSECURE_LAN"] = "1"
        os.environ["KAIZEN_STUDIO_COOKIE_SECURE"] = "0"


class KaizenLauncher:
    def __init__(
        self,
        root: tk.Tk,
        detect_address: Callable[[], str] = detect_private_ipv4,
        server_factory: Callable[..., uvicorn.Server] = uvicorn.Server,
    ) -> None:
        self.root = root
        self.detect_address = detect_address
        self.server_factory = server_factory
        self.server: uvicorn.Server | None = None
        self.server_thread: threading.Thread | None = None
        self.url: str | None = None
        self.server_error: BaseException | None = None
        self.poll_count = 0
        self._build_window()

    def _build_window(self) -> None:
        self.root.title("Kaizen Studio")
        self.root.geometry("590x390")
        self.root.minsize(520, 350)
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)

        content = ttk.Frame(self.root, padding=24)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Kaizen Studio", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            content,
            text="Choisissez où rendre le serveur accessible.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 18))

        self.mode_frame = ttk.Frame(content)
        self.mode_frame.pack(fill="x")
        ttk.Button(
            self.mode_frame,
            text="1. Ce PC uniquement (HTTP local)",
            command=self._start_local,
        ).pack(fill="x", pady=4)
        ttk.Button(
            self.mode_frame,
            text="2. Réseau privé de l'entreprise (HTTP non chiffré)",
            command=self._start_lan,
        ).pack(fill="x", pady=4)

        ttk.Label(
            content,
            text=(
                "Le mode réseau n'est pas chiffré : identifiants et vidéos peuvent être interceptés. "
                "Il doit être limité au réseau privé autorisé par l'informatique."
            ),
            wraplength=530,
            justify="left",
        ).pack(anchor="w", pady=(12, 4))

        self.status = ttk.Label(content, text="Le serveur n'est pas démarré.", wraplength=530)
        self.status.pack(anchor="w", fill="x", pady=(16, 6))

        self.url_label = ttk.Label(content, text="", wraplength=530)
        self.url_label.pack(anchor="w", fill="x")

        actions = ttk.Frame(content)
        actions.pack(fill="x", side="bottom", pady=(14, 0))
        self.open_button = ttk.Button(actions, text="Ouvrir Kaizen Studio", command=self._open_app, state="disabled")
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Arrêter le serveur", command=self._stop_server, state="disabled")
        self.stop_button.pack(side="right")

    def _start_local(self) -> None:
        configure_server_mode("127.0.0.1", allow_insecure_lan=False)
        self._start_server("127.0.0.1")

    def _start_lan(self) -> None:
        try:
            host = self.detect_address()
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            messagebox.showerror("Adresse réseau indisponible", str(error), parent=self.root)
            return

        confirmed = messagebox.askyesno(
            "Confirmer l'accès réseau non chiffré",
            (
                f"Adresse privée détectée : {host}\n\n"
                "HTTP n'est pas chiffré : mots de passe, vidéos et données peuvent être interceptés "
                "sur le réseau.\n\n"
                "Le service doit être limité aux PC autorisés par l'informatique et ne doit pas être "
                "exposé à Internet. Continuer ?"
            ),
            icon="warning",
            parent=self.root,
        )
        if not confirmed:
            return

        configure_server_mode(host, allow_insecure_lan=True)
        self._start_server(host)

    def _start_server(self, host: str) -> None:
        if self.server_thread and self.server_thread.is_alive():
            return

        try:
            from app.main import app

            url_host = f"[{host}]" if ":" in host else host
            self.url = f"http://{url_host}:{PORT}/"
            self.server_error = None
            self.poll_count = 0
            self.status.configure(text="Démarrage du serveur…")
            self.url_label.configure(text=f"Adresse : {self.url}")
            self.mode_frame.pack_forget()
            self.open_button.configure(state="disabled")
            self.stop_button.configure(state="normal")

            config = uvicorn.Config(
                app,
                host=host,
                port=PORT,
                log_level="warning",
                access_log=False,
                log_config=None,
            )
            self.server = self.server_factory(config)
            self.server_thread = threading.Thread(target=self._run_server, name="kaizen-server", daemon=True)
            self.server_thread.start()
            self.root.after(250, self._check_server_status)
        except Exception as error:
            self._show_server_error(str(error))

    def _run_server(self) -> None:
        try:
            if self.server is not None:
                self.server.run()
        except SystemExit as error:
            self.server_error = RuntimeError(f"Le serveur s'est arrêté au démarrage (code {error.code}).")
        except Exception as error:
            self.server_error = error

    def _check_server_status(self) -> None:
        if self.server_error is not None:
            self._show_server_error(str(self.server_error))
            return
        if self.server_thread is not None and not self.server_thread.is_alive():
            if self.server is not None and self.server.should_exit:
                self.status.configure(text="Serveur arrêté.")
                self.stop_button.configure(state="disabled")
                return
            self._show_server_error(
                "Le serveur s'est arrêté au démarrage. Vérifiez que le port TCP 8000 n'est pas déjà utilisé."
            )
            return
        if self.server is not None and self.server.started:
            self.status.configure(text="Kaizen Studio est démarré.")
            self.open_button.configure(state="normal")
            self._open_app()
            return

        self.poll_count += 1
        if self.poll_count >= 80:
            self._show_server_error("Le serveur n'a pas démarré dans le délai prévu.")
            return
        self.root.after(250, self._check_server_status)

    def _show_server_error(self, detail: str) -> None:
        self.status.configure(text="Le démarrage du serveur a échoué.")
        self.stop_button.configure(state="disabled")
        self.mode_frame.pack(fill="x", before=self.status)
        messagebox.showerror("Erreur de démarrage", detail, parent=self.root)

    def _open_app(self) -> None:
        if self.url:
            webbrowser.open(self.url)

    def _stop_server(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
            self.status.configure(text="Arrêt du serveur…")
            self.stop_button.configure(state="disabled")
            self.root.after(250, self._check_stopped)

    def _check_stopped(self) -> None:
        if self.server_thread is not None and self.server_thread.is_alive():
            self.root.after(250, self._check_stopped)
            return
        self.status.configure(text="Serveur arrêté.")
        self.open_button.configure(state="disabled")

    def _close_window(self) -> None:
        if self.server_thread is not None and self.server_thread.is_alive():
            if not messagebox.askyesno(
                "Arrêter Kaizen Studio ?",
                "Fermer cette fenêtre arrêtera aussi le serveur.",
                parent=self.root,
            ):
                return
            if self.server is not None:
                self.server.should_exit = True
            self.server_thread.join(timeout=10)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        from PIL import Image, ImageTk

        icon_path = os.path.join(os.path.dirname(__file__), "assets", "kaizen_studio.ico")
        if os.path.isfile(icon_path):
            window_icon = ImageTk.PhotoImage(Image.open(icon_path))
            root.iconphoto(True, window_icon)
            root._kaizen_icon = window_icon
    except (ImportError, OSError, tk.TclError):
        pass
    KaizenLauncher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
