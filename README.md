# Jarvis

Asistente de voz bilingüe (español/inglés) para macOS, al estilo del Jarvis de Tony Stark. Escucha por el micrófono, responde con la voz `say` del sistema y usa **Google Gemini** como cerebro. Detecta automáticamente el idioma en el que le hablas y contesta en el mismo — incluso si mezclas ambos en la misma sesión.

Incluye dos interfaces:

- **Jarvis.app** — HUD de escritorio en CustomTkinter.
- **Jarvis Web.app** — servidor Flask + Socket.IO que abre un HUD en el navegador.

Ambas comparten el mismo núcleo (`jarvis_core.py`).

---

## Requisitos

- macOS (usa `say` para TTS y `open` para el navegador).
- Python 3.11+ (probado con 3.14).
- [Homebrew](https://brew.sh) para instalar `python-tk`.
- Un micrófono.
- Una API key de Gemini — es **gratuita** en [Google AI Studio](https://aistudio.google.com/apikey).

## Instalación rápida

```bash
git clone <este-repo> jarvis_project
cd jarvis_project
cp .env.example .env
# edita .env y pega tu GEMINI_API_KEY
./setup.command
```

`setup.command` crea el venv, instala dependencias y compila las dos `.app` en `dist/`. Puedes copiarlas a `/Applications` y usarlas con doble clic.

## Instalación manual (modo desarrollo)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y rellena tu API key
```

Arrancar en modo dev:

```bash
python jarvis_app.py        # desktop
python jarvis_web.py        # web (abre http://localhost:5005)
```

## Variables de entorno

Todas opcionales salvo `GEMINI_API_KEY`. Ver `.env.example` para la lista completa:

- `GEMINI_API_KEY` — **obligatoria**, tu API key de Gemini.
- `FLASK_SECRET_KEY` — clave de sesión del servidor web.
- `JARVIS_VOICE_ES` / `JARVIS_VOICE_EN` — voces de `say` por idioma (por defecto `Jorge` / `Daniel`). Lista con `say -v '?'`.
- `JARVIS_MODEL` — modelo de Gemini (por defecto `gemini-2.5-flash`).
- `JARVIS_NO_BROWSER=1` — no abrir el navegador automáticamente en la web app.

## Uso

Di **"Jarvis"** para despertarlo; te escuchará durante unos segundos y luego pensará y responderá. Puedes seguir hablando sin repetir la wake-word mientras la conversación esté activa.

Atajos por texto (solo web): hay un input en el HUD lateral para escribirle en lugar de hablarle. Útil cuando estás en una llamada.

Apagado: botón de shutdown en el HUD, o cerrar la app por Activity Monitor.

## Arquitectura

```
jarvis_core.py   —  Cerebro: Gemini, voz, reconocimiento, idioma, wake-word, historial.
jarvis_app.py    —  UI de escritorio (CustomTkinter).
jarvis_web.py    —  Servidor Flask + Socket.IO (HUD en navegador).
templates/       —  HTML del HUD web.
static/          —  CSS/JS del HUD web.
build_*.sh       —  Scripts PyInstaller para empaquetar .app.
```

El core expone callbacks (`on_status`, `on_speak`) que tanto la UI de escritorio como el bridge web consumen — añadir una nueva interfaz es solo cablearse a esos callbacks.

## Detección de idioma

Jarvis envía el audio a Google ASR en paralelo como `es-ES` y `en-US`, y puntúa ambas transcripciones con un sistema de marcadores de idioma (artículos, conjugaciones, signos ¿¡, tildes, etc.). Cuando ambas versiones son internamente coherentes, aplica un pequeño sesgo hacia inglés — empíricamente el ASR español tiende a alucinar frases plausibles en español a partir de audio inglés, y este sesgo corrige ese artefacto.

## Licencia

MIT — ver [LICENSE](LICENSE).

## Créditos

Cerebro: [Google Gemini](https://ai.google.dev). Voz: `say` de macOS. ASR: Google Speech Recognition vía la librería [`SpeechRecognition`](https://github.com/Uberi/speech_recognition). UI: [CustomTkinter](https://customtkinter.tomschimansky.com) y [Flask-SocketIO](https://flask-socketio.readthedocs.io).
