"""
jarvis_web.py — servidor Flask + SocketIO que monta el HUD de Jarvis.

- Usa JarvisCore como cerebro (voz, Gemini, idioma, wake-word, historial).
- Empuja eventos al navegador:
    * status_update { status, log, lang, voice }
    * chat_message  { role, text, lang }
    * audio_level   { level }      (30 ~ 40 Hz mientras escucha)
    * shutdown_ack                 (antes de apagar el servidor)
- Acepta eventos del navegador:
    * send_command { text }        (atajo de texto para probar)
    * shutdown                     (apaga con 'Good bye, sir')
"""

from __future__ import annotations

import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from dotenv import load_dotenv
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

from jarvis_core import JarvisCore


def _load_env() -> None:
    """
    Busca el .env en rutas típicas para que el .app lo encuentre aunque se
    lance con doble clic (en ese caso el cwd es '/').
    """
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.expanduser("~/.jarvis/.env"),
        os.path.expanduser("~/Documents/jarvis_project/.env"),
    ]
    # Si estamos en el mismo directorio del script (modo dev), también.
    here = os.path.abspath(os.path.dirname(__file__))
    candidates.insert(0, os.path.join(here, ".env"))
    for path in candidates:
        if os.path.exists(path):
            load_dotenv(path)
            return
    load_dotenv()  # fallback a la búsqueda por defecto


_load_env()

# Silenciamos el ruido del servidor para que la terminal (si la hay) quede
# limpia: nada de "127.0.0.1 - GET /..." por cada request. Los logs útiles
# ya se emiten a la UI por WebSocket.
for name in ("werkzeug", "engineio", "engineio.server", "socketio", "socketio.server"):
    logging.getLogger(name).setLevel(logging.ERROR)

# En un bundle .app no hay stderr visible. Aun así, si alguien lo ejecuta
# desde terminal, los errores serios sí se ven.
logging.basicConfig(level=logging.WARNING, format="[jarvis] %(message)s")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(16)


def _resource(relative: str) -> str:
    """
    Devuelve la ruta a un recurso (templates/static) tanto si se ejecuta en
    desarrollo como si está empaquetado con PyInstaller en un .app.
    """
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base, relative)


app = Flask(
    __name__,
    template_folder=_resource("templates"),
    static_folder=_resource("static"),
)
app.config["SECRET_KEY"] = FLASK_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ---------------------------------------------------------------------------
# Pegamento entre núcleo y socket
# ---------------------------------------------------------------------------

class WebBridge:
    """
    Traduce eventos del JarvisCore a mensajes SocketIO. Mantiene además el
    último idioma/voz conocido para que el frontend pueda mostrarlo.
    """

    def __init__(self) -> None:
        self.last_lang = "en"
        self.last_status = "Booting"
        self.running = True

        self.core = JarvisCore(
            api_key=GEMINI_API_KEY,
            on_status=self.on_status,
            on_speak=self.on_speak,
        )

    # --- callbacks del núcleo ------------------------------------------------

    def on_status(self, status: str, log: str) -> None:
        self.last_status = status
        # on_status puede ser invocado desde dentro del __init__ de JarvisCore
        # (antes de que self.core esté asignado), así que nos protegemos.
        core = getattr(self, "core", None)
        voice = core.voice_for(self.last_lang) if core else "Daniel"
        socketio.emit(
            "status_update",
            {
                "status": status,
                "log": log,
                "lang": self.last_lang,
                "voice": voice,
            },
        )
        # Cuando el núcleo anuncia transcripción o respuesta, también llenamos
        # el chat lateral. Distinguimos por el prefijo que pone el propio core.
        if log.startswith("User: "):
            socketio.emit(
                "chat_message",
                {"role": "user", "text": log[len("User: "):], "lang": self.last_lang},
            )

    def on_speak(self, text: str, lang: str) -> None:
        self.last_lang = lang
        socketio.emit(
            "chat_message",
            {"role": "jarvis", "text": text, "lang": lang},
        )

    # --- niveles de audio ----------------------------------------------------

    def on_audio_level(self, level: float) -> None:
        # Con threading mode es seguro emitir desde cualquier hilo.
        socketio.emit("audio_level", {"level": level})

    # --- bucles --------------------------------------------------------------

    def run(self) -> None:
        # wait_ready=True → el núcleo espera a que el navegador se conecte
        # (handle_connect() hace core.ready_event.set()) antes de saludar,
        # así no se pierde el primer evento en una web aún sin abrir.
        self.core.run_voice_loop(
            level_callback=self.on_audio_level,
            greeting="Good evening, sir. Systems are online.",
            wait_ready=True,
        )

    # --- apagado -------------------------------------------------------------

    def shutdown(self) -> None:
        """Despedida + cierre del proceso entero."""
        self.running = False
        # Señalamos al bucle de voz que pare y cortamos cualquier habla
        # que esté en curso (antes el 'Good bye' se ponía en cola detrás
        # de la respuesta que Jarvis estaba soltando).
        self.core.stop_event.set()
        self.core.interrupt_speech()
        socketio.emit("shutdown_ack", {"message": "Good bye, sir."})
        # Pequeña pausa para que el cliente pinte el estado de apagado antes
        # de que la UI se muera.
        time.sleep(0.3)
        self.core.speak("Good bye, sir.", lang="en")
        # Le damos un pequeño respiro al `say` y cerramos a martillazos.
        threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()


bridge = WebBridge()


# ---------------------------------------------------------------------------
# Rutas HTTP
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {
        "ready": bridge.core.ready,
        "status": bridge.last_status,
        "lang": bridge.last_lang,
    }


# ---------------------------------------------------------------------------
# Eventos Socket.IO
# ---------------------------------------------------------------------------

@socketio.on("connect")
def handle_connect():
    # La primera conexión libera al núcleo para que suelte el saludo.
    # Conexiones posteriores (recargas) simplemente vuelven a recibir el
    # estado actual; no resetean el flujo.
    bridge.core.ready_event.set()
    emit(
        "status_update",
        {
            "status": bridge.last_status,
            "log": "Connection stabilized.",
            "lang": bridge.last_lang,
            "voice": bridge.core.voice_for(bridge.last_lang),
        },
    )


@socketio.on("send_command")
def handle_command(data):
    text = (data or {}).get("text", "").strip()
    if not text:
        return

    # Si Jarvis ya está hablando, cortamos la respuesta actual antes de
    # contestar al nuevo input. Evita solapamiento de voces.
    if bridge.core.is_speaking:
        bridge.core.interrupt_speech()

    def _handle():
        bridge.on_status("Thinking", f"User: {text}")
        reply = bridge.core.think(text)
        bridge.on_status("Speaking", reply.text)
        bridge.core.speak(reply.text, lang=reply.lang)
        bridge.on_status("Idle", "Systems ready.")

    threading.Thread(target=_handle, daemon=True).start()


@socketio.on("shutdown")
def handle_shutdown():
    threading.Thread(target=bridge.shutdown, daemon=True).start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _open_browser_when_ready(
    url: str,
    host: str = "127.0.0.1",
    port: int = 5005,
    max_wait: float = 10.0,
) -> None:
    """
    Espera a que el servidor acepte conexiones en `host:port` y abre el
    navegador por defecto del usuario. Diferencias vs. la versión anterior
    (sleep(1.2) + webbrowser.open):

    - Sondeo activo del puerto: el arranque de la .app bundled puede tardar
      bastante más de 1.2s la primera vez (cold start, macOS cargando
      frameworks, codesign verificando...). Si abríamos el navegador antes
      de que el server escuchase, Safari mostraba "no se puede conectar".
    - Usamos `open` de macOS vía subprocess en lugar de `webbrowser.open`:
      dentro de un .app bundled de PyInstaller, `webbrowser.open` falla en
      silencio en algunas versiones de macOS (el módulo intenta `osascript`
      con un entorno que no siempre está). `/usr/bin/open` es la ruta
      canónica en macOS y sí funciona desde un bundle.
    - Fallback a `webbrowser` si `open` no está (p. ej. ejecutando en
      Linux).
    """

    def _go():
        # Sondeamos el puerto cada 100ms hasta max_wait segundos.
        deadline = time.time() + max_wait
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                try:
                    s.connect((host, port))
                    break
                except OSError:
                    time.sleep(0.1)
        else:
            # El servidor no llegó a escuchar — no abrimos nada.
            return

        # macOS: `open <url>` delega en LaunchServices y siempre abre el
        # navegador por defecto del usuario, incluso desde un proceso
        # bundled. Si `open` no existe (Linux), caemos a webbrowser.
        try:
            subprocess.Popen(
                ["open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


if __name__ == "__main__":
    threading.Thread(target=bridge.run, daemon=True).start()

    # Abrimos el HUD automáticamente, salvo que el usuario lo desactive
    # exportando JARVIS_NO_BROWSER=1 (útil si lo lanzas en un servidor remoto).
    if not os.getenv("JARVIS_NO_BROWSER"):
        _open_browser_when_ready("http://localhost:5005")

    socketio.run(
        app,
        host="0.0.0.0",
        port=5005,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
