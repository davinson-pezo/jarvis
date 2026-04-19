# Jarvis

Bilingual (Spanish / English) voice assistant for macOS, inspired by Tony Stark's Jarvis. Listens through the microphone, replies using the system's `say` voice, and uses **Google Gemini** as its brain. Automatically detects the language you speak in and answers in the same one — even if you switch mid-session.

It ships with two interfaces:

- **Jarvis.app** — desktop HUD built with CustomTkinter.
- **Jarvis Web.app** — Flask + Socket.IO server that opens a HUD in your browser.

Both share the same core (`jarvis_core.py`).

---

## Requirements

- macOS (uses `say` for TTS and `open` for the browser).
- Python 3.11+ (tested on 3.14).
- [Homebrew](https://brew.sh) to install `python-tk`.
- A microphone.
- A Gemini API key — **free** at [Google AI Studio](https://aistudio.google.com/apikey).

## Quick install

```bash
git clone https://github.com/davinson-pezo/jarvis.git
cd jarvis
cp .env.example .env
# edit .env and paste your GEMINI_API_KEY
./setup.command
```

`setup.command` creates the venv, installs dependencies, and builds both `.app` bundles in `dist/`. You can copy them to `/Applications` and launch them with a double click.

## Manual install (dev mode)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # and fill in your API key
```

Run in dev mode:

```bash
python jarvis_app.py        # desktop
python jarvis_web.py        # web (opens http://localhost:5005)
```

## Environment variables

All optional except `GEMINI_API_KEY`. See `.env.example` for the full list:

- `GEMINI_API_KEY` — **required**, your Gemini API key.
- `FLASK_SECRET_KEY` — session signing key for the web server.
- `JARVIS_VOICE_ES` / `JARVIS_VOICE_EN` — macOS `say` voices per language (defaults: `Jorge` / `Daniel`). List available voices with `say -v '?'`.
- `JARVIS_MODEL` — Gemini model (default: `gemini-2.5-flash`).
- `JARVIS_NO_BROWSER=1` — skip the automatic browser open for the web app.

## Usage

Say **"Jarvis"** to wake him up; he will listen for a few seconds, think, and reply. You can keep talking without repeating the wake word while the conversation is active.

Text shortcut (web only): there is an input box in the side HUD to type to him instead of talking. Useful when you're on a call.

Shutdown: shutdown button in the HUD, or quit from Activity Monitor.

## Architecture

```
jarvis_core.py   —  Brain: Gemini, voice, speech recognition, language, wake word, history.
jarvis_app.py    —  Desktop UI (CustomTkinter).
jarvis_web.py    —  Flask + Socket.IO server (browser HUD).
templates/       —  Web HUD HTML.
static/          —  Web HUD CSS / JS.
build_*.sh       —  PyInstaller scripts for packaging .app bundles.
```

The core exposes callbacks (`on_status`, `on_speak`) that both the desktop UI and the web bridge consume — adding a new interface is just wiring into those callbacks.

## Language detection

Jarvis sends audio to Google ASR in parallel as both `es-ES` and `en-US`, and scores each transcript with a language-marker system (articles, conjugations, ¿¡ punctuation, accents, etc.). When both transcripts are internally coherent, it applies a small bias toward English — empirically the Spanish ASR tends to hallucinate plausible Spanish sentences from English audio, and this bias corrects that artifact.

## ☕ Support the Project

If this tool has been helpful and you'd like to support its development, feel free to buy me a coffee!

[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate?business=davinson@gmail.com&no_recurring=0&item_name=Jarvis+Support&currency_code=EUR)

## License

MIT — see [LICENSE](LICENSE).

## Credits

Brain: [Google Gemini](https://ai.google.dev). Voice: macOS `say`. ASR: Google Speech Recognition via the [`SpeechRecognition`](https://github.com/Uberi/speech_recognition) library. UI: [CustomTkinter](https://customtkinter.tomschimansky.com) and [Flask-SocketIO](https://flask-socketio.readthedocs.io).
