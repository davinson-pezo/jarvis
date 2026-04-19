# 🤖 Jarvis

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/) [![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/) [![AI: Gemini](https://img.shields.io/badge/AI-Gemini-4285F4.svg)](https://ai.google.dev) [![Bilingual](https://img.shields.io/badge/bilingual-ES%20%7C%20EN-brightgreen.svg)](#-language-detection)

Bilingual (Spanish / English) voice assistant for macOS, inspired by Tony Stark's Jarvis. Listens through the microphone, replies using the system's `say` voice, and uses **Google Gemini** as its brain. Automatically detects the language you speak in and answers in the same one — even if you switch mid-session.

It ships with two interfaces:

- 🖥️ **Jarvis.app** — desktop HUD built with CustomTkinter.
- 🌐 **Jarvis Web.app** — Flask + Socket.IO server that opens a HUD in your browser.

Both share the same core (`jarvis_core.py`).

---

## ✨ Features

- 🎙️ **Voice-first** — wake-word activation, natural conversation without repeating the trigger.
- 🌍 **Truly bilingual** — per-utterance language detection with a hallucination-resistant scoring system.
- 🧠 **Gemini-powered** — fast, configurable (`gemini-2.5-flash` by default, swap to `gemini-2.5-pro` via `.env`).
- 💬 **Text fallback** — type to Jarvis from the web HUD when you can't talk out loud.
- 📦 **Ships as `.app` bundles** — one double click, no terminal required.
- 🔒 **Local-first** — your API key never leaves `.env`, nothing is shipped to third parties beyond Gemini and Google ASR.

## 📋 Requirements

- macOS (uses `say` for TTS and `open` for the browser).
- Python 3.11+ (tested on 3.14).
- [Homebrew](https://brew.sh) to install `python-tk`.
- A microphone.
- A Gemini API key — **free** at [Google AI Studio](https://aistudio.google.com/apikey).

## 🚀 Quick install

```bash
git clone https://github.com/davinson-pezo/jarvis.git
cd jarvis
cp .env.example .env
# edit .env and paste your GEMINI_API_KEY
./setup.command
```

`setup.command` creates the venv, installs dependencies, and builds both `.app` bundles in `dist/`. You can copy them to `/Applications` and launch them with a double click.

## 🛠️ Manual install (dev mode)

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

## ⚙️ Environment variables

All optional except `GEMINI_API_KEY`. See `.env.example` for the full list:

- `GEMINI_API_KEY` — **required**, your Gemini API key.
- `FLASK_SECRET_KEY` — session signing key for the web server.
- `JARVIS_VOICE_ES` / `JARVIS_VOICE_EN` — macOS `say` voices per language (defaults: `Jorge` / `Daniel`). List available voices with `say -v '?'`.
- `JARVIS_MODEL` — Gemini model (default: `gemini-2.5-flash`).
- `JARVIS_NO_BROWSER=1` — skip the automatic browser open for the web app.

## 🎙️ Usage

Jarvis runs in **continuous-listen mode** — no wake word required. Launch the app and it greets you with *"Good evening, sir. Systems are online."* From that moment on, just speak. It picks up whatever you say in Spanish or English, thinks, and replies in the same language with the matching voice.

The loop is: `LISTENING → THINKING → SPEAKING → LISTENING`. A short cooldown after each reply keeps it from hearing its own voice. Phrases up to ~20 seconds with natural pauses work fine.

**Text input (web HUD)** — as an alternative to speaking, type your command in the transmission log input box and hit `SEND`. Useful on meetings, noisy rooms, or when you just want to test something quickly. Jarvis still replies with voice.

**Shutdown** — the big `SHUTDOWN` button in the footer triggers an animated goodbye (*"Good bye, sir."*) and then cleanly kills the process. Closing the terminal / browser tab alone doesn't stop it; you can also quit from Activity Monitor if needed.

> ℹ️ A wake-word scaffold (`jarvis`, `hey jarvis`, `hola jarvis`, `oye jarvis`) exists in `jarvis_core.py` but is currently unused. If you prefer wake-word-gated behavior over continuous listening, hooking it into `run_voice_loop` is a good first contribution.

## 🏗️ Architecture

```
jarvis_core.py   —  Brain: Gemini, voice, speech recognition, language, wake word, history.
jarvis_app.py    —  Desktop UI (CustomTkinter).
jarvis_web.py    —  Flask + Socket.IO server (browser HUD).
templates/       —  Web HUD HTML.
static/          —  Web HUD CSS / JS.
build_*.sh       —  PyInstaller scripts for packaging .app bundles.
```

The core exposes callbacks (`on_status`, `on_speak`) that both the desktop UI and the web bridge consume — adding a new interface is just wiring into those callbacks.

## 🔌 Extending Jarvis — OpenClaw integration (community direction)

As it stands, Jarvis is a **voice layer** wrapping Gemini: great at conversation and reasoning, but it can't touch your machine. A natural next step is to bolt Jarvis onto a local agent with tool-use capabilities — [**OpenClaw**](https://openclaw.ai) is a strong candidate for macOS.

The architecture would look like this:

```
🎙️  Mic  →  Jarvis (wake word, ASR, language)
                     ↓
                  OpenClaw (local agent on port 18789, Bearer auth)
                     ↓  tool-use
          ┌──────────┼──────────┬──────────┬──────────┐
        Files     Apps       Mail      Calendar    Shell
                     ↓
🔊  say  ←  Jarvis (TTS in the detected language)
```

Concretely, on a Mac this would unlock things like:

- 📁 *"Jarvis, create a folder on my Desktop called 'Taxes 2026' and move every PDF from Downloads into it."*
- 🧭 *"Open Spotify, play some focus music, and dim the lights."* (via Shortcuts / AppleScript bridges)
- 📬 *"Read me the latest unread email from María and draft a reply saying I'll call her tomorrow."*
- 🗓️ *"What's on my calendar for Thursday? Add a 3 pm slot titled 'Dentist'."*
- 🧰 Cross-app workflows that would otherwise require half a dozen clicks.

**Why this isn't merged into `main`:** OpenClaw isn't universally installed, and forcing that dependency on everyone just to chat with Gemini would be overkill. The current repo keeps the Gemini-only path clean so anyone with a free API key can run it.

**If you want to take this on:** the integration point is `JarvisCore.think()` in `jarvis_core.py`. Instead of (or in addition to) calling `self.client.models.generate_content(...)`, the method could POST to an OpenClaw gateway and pipe the response back through the existing `on_speak` / `on_status` callbacks. The bilingual scoring and voice routing keep working unchanged. PRs welcome — and if you build it, please keep the OpenClaw path opt-in (e.g. `JARVIS_BRAIN=openclaw` in `.env`) so Gemini-only users aren't affected.

## 🌐 Language detection

Jarvis sends audio to Google ASR in parallel as both `es-ES` and `en-US`, and scores each transcript with a language-marker system (articles, conjugations, ¿¡ punctuation, accents, etc.). When both transcripts are internally coherent, it applies a small bias toward English — empirically the Spanish ASR tends to hallucinate plausible Spanish sentences from English audio, and this bias corrects that artifact.

## 🛡️ Privacy & Security

- Your Gemini API key lives only in `.env`, which is git-ignored.
- Voice transcription goes to Google ASR; chat reasoning goes to Gemini. No other third parties.
- No telemetry, no analytics, no tracking.
- The `.app` bundles are ad-hoc code-signed (no developer account required).

## ☕ Support the Project

If this tool has been helpful and you'd like to support its development, feel free to buy me a coffee!

[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate?business=davinson@gmail.com&no_recurring=0&item_name=Jarvis+Support&currency_code=EUR)

## 📄 License

MIT — see [LICENSE](LICENSE).

## 🙏 Credits

Brain: [Google Gemini](https://ai.google.dev). Voice: macOS `say`. ASR: Google Speech Recognition via the [`SpeechRecognition`](https://github.com/Uberi/speech_recognition) library. UI: [CustomTkinter](https://customtkinter.tomschimansky.com) and [Flask-SocketIO](https://flask-socketio.readthedocs.io).
