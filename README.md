# 🤖 Jarvis

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/) [![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/) [![AI: Gemini](https://img.shields.io/badge/AI-Gemini-4285F4.svg)](https://ai.google.dev) [![Bilingual](https://img.shields.io/badge/bilingual-ES%20%7C%20EN-brightgreen.svg)](#-language-detection)

Bilingual (Spanish / English) voice assistant for macOS, inspired by Tony Stark's JARVIS. Listens continuously through the microphone, thinks with **Google Gemini** (with live Google Search), and replies out loud using macOS's native `say` engine. Detects the language of every utterance independently, so you can switch between Spanish and English mid-conversation and Jarvis follows.

Ships as two macOS apps that share the same core:

- 🖥️ **Jarvis.app** — native HUD built with CustomTkinter.
- 🌐 **Jarvis Web.app** — launches a local Flask + Socket.IO server and opens the HUD in your browser.

---

## ✨ Features

- 🎙️ **Continuous listening** — no wake word needed; just talk.
- 🌍 **Per-utterance language detection** — ASR is run in parallel as `es-ES` and `en-US`, and a marker-scoring system picks the transcript that's internally coherent with its own language. Includes an asymmetric bias that fixes Spanish-ASR hallucinations from English audio.
- 🧠 **Gemini + Google Search** — real-time answers (weather, news, prices, scores). Model is `gemini-2.5-flash` by default; `gemini-2.5-pro` or any other Gemini model can be selected via `.env`.
- 💬 **Short-term memory** — keeps the last 8 conversational turns so follow-ups work ("and what about tomorrow?").
- 🔊 **Bilingual voices** — `Daniel` (en_GB, the classic British Jarvis sound) and `Jorge` (es_ES) by default, configurable per-language. Falls back gracefully to Oliver/Alex… or Diego/Juan… if the preferred voice isn't installed.
- 🧼 **TTS-aware output** — the response is stripped of markdown, code fences, and `[1]` citation marks before being read, so the speech is clean.
- ⌨️ **Text input (web HUD)** — type instead of talking; Jarvis still replies with voice. Useful on calls or in noisy rooms.
- 🎨 **HUD visuals** — animated arc reactor that changes color per state (idle / listening / thinking / speaking) and reacts to real mic audio levels.
- 📦 **Double-click launch** — ships as two `.app` bundles; no terminal required after setup.

## 📋 Requirements

- macOS (uses `say` for TTS and `open` to launch the browser).
- Python 3.11+ (tested on 3.14).
- [Homebrew](https://brew.sh) for `python-tk` (only if you use the desktop app).
- A microphone (and Microphone permission granted to the app on first run).
- A Gemini API key — **free** at [Google AI Studio](https://aistudio.google.com/apikey).

## 🚀 Quick install

```bash
git clone https://github.com/davinson-pezo/jarvis.git
cd jarvis
cp .env.example .env
# edit .env and paste your GEMINI_API_KEY
./setup.command
```

`setup.command` recreates the venv, installs dependencies, and runs PyInstaller to produce both `.app` bundles inside `dist/`. Copy them to `/Applications` and launch with a double click.

## 🛠️ Manual install (dev mode)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # and paste your API key
```

Run directly without bundling:

```bash
python jarvis_app.py        # desktop HUD
python jarvis_web.py        # web HUD on http://localhost:5005
```

## ⚙️ Environment variables

All optional except `GEMINI_API_KEY`. See `.env.example` for the full list:

- `GEMINI_API_KEY` — **required**, your Gemini API key.
- `FLASK_SECRET_KEY` — session-signing key for the web server. If empty, a random one is generated each startup (which invalidates web sessions across restarts).
- `JARVIS_MODEL` — Gemini model name (default `gemini-2.5-flash`). Try `gemini-2.5-pro` for smarter but slightly slower replies.
- `JARVIS_VOICE_EN` / `JARVIS_VOICE_ES` — override the `say` voice for each language. Defaults: `Daniel` / `Jorge`. See available voices with `say -v '?'`.
- `JARVIS_NO_BROWSER=1` — skip the automatic browser open for the web app (useful for remote hosts).

## 🎙️ Usage

On launch, Jarvis greets you in English — *"Good evening, sir. Systems are online."* — and immediately enters continuous listening. The loop is `LISTENING → THINKING → SPEAKING → LISTENING`, with a short cooldown after each reply so it doesn't hear its own voice. Phrases of up to ~20 seconds with natural pauses work fine; speak in Spanish or English and Jarvis will reply in the same language with the matching voice.

**Desktop HUD** (`Jarvis.app`): a dark window with an animated arc reactor on the left, a transmission log on the right showing everything Jarvis hears and says, a current voice / language readout, a linear audio spectrum below, and a `SHUTDOWN` button in the footer.

**Web HUD** (`Jarvis Web.app`): the same HUD rendered in your browser, plus a text input box in the transmission panel (`Type a command, or just speak...`) and a footer showing `CORE TEMP`, `MODE: CONTINUOUS`, and `UPTIME`. Typing + Enter (or clicking `SEND`) sends the message to Jarvis, which replies out loud. The `Jarvis Web.app` bundle runs as a macOS background agent (no Dock icon, no App Switcher entry) — its UI lives entirely in the browser tab.

**Shutdown:** click `SHUTDOWN` in either HUD. The desktop app fades out and speaks *"Good bye, sir."* before quitting; the web version pops a confirmation, then overlays `SHUTTING DOWN / Good bye, sir.` and terminates the server. You can also force-quit from Activity Monitor.

> ℹ️ A wake-word scaffolding (`jarvis`, `hey jarvis`, `hola jarvis`, `oye jarvis`) is present in `jarvis_core.py` but is **currently inactive** — the voice loop processes every utterance it hears. If you'd prefer wake-word gating over continuous listening, wiring `contains_wake_word` into `run_voice_loop` is a good first PR.

## 🏗️ Architecture

```
jarvis_core.py       Brain — Gemini client, speech recognition, language
                     scoring, voice selection, TTS, history, callbacks.

jarvis_app.py        Desktop UI — CustomTkinter HUD with animated reactor
                     canvas, spectrum bar, log, shutdown.

jarvis_web.py        Flask + Socket.IO server — same HUD over WebSocket,
                     port 5005, auto-opens the browser.

templates/           Web HUD HTML.
static/              Web HUD CSS + JS (Canvas-based reactor + spectrum).

build_desktop.sh     PyInstaller recipe for Jarvis.app.
build_web.sh        PyInstaller recipe for Jarvis Web.app (LSUIElement=true,
                     so macOS doesn't bounce a Dock icon).
build_app.sh         Runs both above in sequence.
setup.command        Double-click installer: venv → pip → build.
```

The core is UI-agnostic: it exposes two callbacks, `on_status(status, log)` and `on_speak(text, lang)`, and a level callback for audio visualization. Both UIs just wire into those — adding a new interface (CLI, menubar, iOS client over WebSocket…) is just wiring them up.

## 🔌 Extending Jarvis — OpenClaw integration (community direction)

Out of the box, Jarvis is a **voice layer** wrapping Gemini: great at conversation and search, but it can't touch your machine. A natural next step is to bolt Jarvis onto a local agent with tool-use capabilities — [**OpenClaw**](https://openclaw.ai) is a strong candidate on macOS.

```
🎙️  Mic  →  Jarvis (ASR + language + wake logic)
                     ↓
                  OpenClaw (local agent on port 18789, Bearer auth)
                     ↓  tool-use
          ┌──────────┼──────────┬──────────┬──────────┐
        Files     Apps       Mail      Calendar    Shell
                     ↓
🔊  say  ←  Jarvis (TTS in the detected language)
```

Concretely, this would unlock things like:

- 📁 *"Jarvis, create a folder on my Desktop called 'Taxes 2026' and move every PDF from Downloads into it."*
- 🧭 *"Open Spotify and play focus music."* (via Shortcuts / AppleScript bridges)
- 📬 *"Read me the latest unread email from María and draft a reply."*
- 🗓️ *"What's on my calendar for Thursday? Add a 3 pm slot titled 'Dentist'."*

**Why this isn't merged into `main`:** OpenClaw isn't universally installed, and forcing that dependency just to chat with Gemini would be overkill. The current repo keeps the Gemini-only path clean so anyone with a free API key can run it.

**Where the integration hooks in:** `JarvisCore.think()` in `jarvis_core.py`. Instead of calling `self.client.models.generate_content(...)`, it could POST to an OpenClaw gateway and pipe the response back through the existing `on_speak` / `on_status` callbacks. Language scoring and voice routing keep working unchanged. Keep the OpenClaw path opt-in via something like `JARVIS_BRAIN=openclaw` in `.env` so existing users aren't affected. PRs welcome.

## 🌐 Language detection

ASR is sent to Google Speech Recognition in parallel as both `es-ES` and `en-US`. Each returned transcript is then scored by how well it matches its claimed language:

- Spanish markers: accents / `ñ` / `¿¡` (+3 flat), plus common function words (`el`, `la`, `qué`, `cómo`, `porque`, …).
- English markers: common function words (`the`, `is`, `what`, `can`, `would`, `please`, `sir`, …).

When both transcripts are internally coherent (score ≥ 2 for their own language) and the Spanish lead is ≤ 2 points, Jarvis picks the English one. This corrects a well-known behavior of Google's Spanish ASR: it happily returns a plausible Spanish sentence when the audio is actually English ("what is the weather like" → "qué es el wéder laik"), whereas the English ASR rarely does the opposite.

For typed input in the web HUD, the same scoring is used to pick the reply language.

## 🛡️ Privacy & Security

- Your Gemini API key lives only in `.env`, which is git-ignored.
- Voice goes to Google ASR; reasoning goes to Gemini. No other third parties.
- No telemetry, no analytics, no tracking, no local persistence beyond an in-memory 8-turn history that dies with the process.
- The `.app` bundles are ad-hoc code-signed (no Apple Developer account required); on first run macOS may ask you to grant Microphone permission.

## ☕ Support the Project

If this tool has been helpful and you'd like to support its development, feel free to buy me a coffee!

[![PayPal](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate?business=davinson@gmail.com&no_recurring=0&item_name=Jarvis+Support&currency_code=EUR)

## 📄 License

MIT — see [LICENSE](LICENSE).

## 🙏 Credits

Brain: [Google Gemini](https://ai.google.dev). TTS: macOS `say`. ASR: Google Speech Recognition via the [`SpeechRecognition`](https://github.com/Uberi/speech_recognition) library. Desktop UI: [CustomTkinter](https://customtkinter.tomschimansky.com). Web UI: [Flask](https://flask.palletsprojects.com) + [Flask-SocketIO](https://flask-socketio.readthedocs.io). Packaging: [PyInstaller](https://pyinstaller.org).
