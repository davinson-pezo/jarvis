"""
jarvis_core.py
==============
Núcleo compartido entre la app de escritorio (Tkinter) y el servidor web (Flask).

Responsabilidades:
- Cliente Gemini con salida JSON nativa (sin frágiles strip de backticks).
- Selección de voz con Kokoro TTS (bm_fable para inglés, em_alex
  para español).
- Transcripción con fallback ES -> EN cuando el reconocimiento no entiende.
- Historial de conversación corto (memoria de sesión).
- Detección de wake-word ("jarvis" / "hey jarvis" / "hola jarvis").
- Contratos `SpeakCallback` / `StatusCallback` para que cada UI se enganche
  sin que el núcleo sepa nada de Tkinter ni de SocketIO.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional, Tuple

import speech_recognition as sr
from google import genai
from google.genai import types
import sounddevice as sd
from kokoro import KPipeline
import numpy as np

# ---------------------------------------------------------------------------
# Configuración de voces y wake-word
# ---------------------------------------------------------------------------

# Voces preferidas usando Kokoro TTS
# en: bm_fable (masculina británica) o af_heart (femenina americana, calidad A)
# es: em_alex (masculino) o ef_dora (femenina)
VOICE_PREFERENCES = {
    "en": "bm_fable",
    "es": "em_alex",
}

# Fallback final si falla el idioma
FALLBACK_VOICE = "bm_fable"

# Palabras que aceptamos como "wake-word". Incluye variaciones comunes que
# Google Speech suele confundir (jarvi, yarvis, harvey, jarbis...).
WAKE_WORDS = (
    "jarvis", "hey jarvis", "hola jarvis", "oye jarvis",
    "yarvis", "jarbis", "harvis", "charvis", "jarvi",
    "hey yarvis", "hola yarvis",
)

# El número máximo de turnos que guardamos en memoria. Un turno = 1 user + 1 assistant.
HISTORY_TURNS = 8


# ---------------------------------------------------------------------------
# Modelo de respuesta
# ---------------------------------------------------------------------------

@dataclass
class JarvisReply:
    lang: str
    text: str


# Callbacks tipados para que la UI reciba eventos del núcleo.
StatusCallback = Callable[[str, str], None]  # (status, log)
SpeakCallback = Callable[[str, str], None]   # (text, lang)


# ---------------------------------------------------------------------------
# JarvisCore
# ---------------------------------------------------------------------------

class JarvisCore:
    """Cerebro de Jarvis. Sin UI, sin hilos propios. La UI controla el ciclo."""

    SYSTEM_PROMPT = (
        "You are Jarvis, an advanced AI assistant inspired by Iron Man's JARVIS. "
        "You are helpful, direct, efficient, and slightly witty — never condescending. "
        "ALWAYS answer the actual question the user asked; don't deflect or change the topic. "
        "Address the user respectfully, once in a while (not every sentence): "
        "in English say 'sir'; in Spanish say 'señor'. "
        "NEVER mix languages: if the reply is in Spanish, do not use 'sir', only 'señor'; "
        "if the reply is in English, do not use 'señor', only 'sir'. "
        "You have access to Google Search: use it whenever the question depends on "
        "current or real-time information (weather, news, sports scores, prices, "
        "recent events, current time, current people in office, etc.). Don't say "
        "you can't access the internet — search for it. "
        "Be concise by default (2-4 sentences) but expand with detail when the "
        "question needs it (explanations, lists, steps). "
        "IMPORTANT: your output is read aloud by a text-to-speech engine, so do NOT "
        "use markdown — no asterisks, hashes, brackets, code fences, bullet points "
        "or citation marks like [1]. Plain prose only."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        on_status: Optional[StatusCallback] = None,
        on_speak: Optional[SpeakCallback] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        # El modelo es configurable por .env (JARVIS_MODEL) sin recompilar.
        # Ejemplos útiles:
        #   gemini-2.5-flash  (rápido, por defecto — pensado para voz)
        #   gemini-2.5-pro    (más listo pero algo más lento)
        #   gemini-flash-latest / gemini-pro-latest
        self.model = model or os.getenv("JARVIS_MODEL", "gemini-2.5-flash")
        self.on_status = on_status or (lambda s, l: None)
        self.on_speak = on_speak or (lambda t, l: None)

        self.recognizer = sr.Recognizer()
        # pause_threshold: cuántos segundos de silencio requiere la librería
        # para decidir que has terminado de hablar. 1.0s es un compromiso:
        # aguanta respiros normales sin cortar pero no se queda pillado.
        self.recognizer.pause_threshold = 1.0
        # IMPORTANTE: dynamic_energy_threshold=True sonaba bien pero en la
        # práctica, con micros muy sensibles, hace que el recognizer crea que
        # el ruido ambiente es "voz" y se quede esperando 30s a que termine.
        # Resultado: la app parece "escuchando" para siempre. Lo dejamos
        # en False y calibramos manualmente al abrir el mic.
        self.recognizer.dynamic_energy_threshold = False
        # Umbral inicial razonable. adjust_for_ambient_noise() lo sobreescribe
        # al empezar a escuchar.
        self.recognizer.energy_threshold = 300

        self.client: Optional[genai.Client] = None
        if self.api_key and self.api_key != "tu_api_key_de_gemini_aqui":
            self.client = genai.Client(api_key=self.api_key)

        self._history: Deque[dict] = deque(maxlen=HISTORY_TURNS * 2)
        self._history_lock = threading.Lock()

        # Evento de parada común (lo controla la UI con shutdown()).
        self.stop_event = threading.Event()

        # Evento "ya podemos empezar a hablar". La UI lo setea cuando está
        # lista (en web, cuando el primer cliente se ha conectado). Si nadie
        # lo setea, run_voice_loop espera hasta que timeout.
        self.ready_event = threading.Event()

        # Serialización de la salida de voz. Si llega un comando por texto
        # mientras el núcleo ya está hablando, el segundo speak() espera al
        # primero en lugar de solaparse (voz doble ininteligible).
        self._speech_lock = threading.Lock()
        # Proceso `say` actualmente en curso — nos vale para poder matarlo
        # desde fuera (shutdown o botón de interrupción).
        self._current_speech: Optional[subprocess.Popen] = None
        # Bandera de "estoy hablando" — la usa la UI y/o el bucle de escucha
        # para ignorar audio mientras Jarvis tiene la palabra.
        self._speaking_event = threading.Event()

        # Configuración para usar Kokoro en MPS (Apple Silicon) de forma forzada si falla algo
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

        self._voice_by_lang = {
            "en": os.getenv("JARVIS_VOICE_EN", VOICE_PREFERENCES["en"]),
            "es": os.getenv("JARVIS_VOICE_ES", VOICE_PREFERENCES["es"]),
        }
        
        # Diccionario para instanciar las pipelines de Kokoro 
        # (ej: 'a' para af_heart, 'b' para bm_fable, 'e' para em_alex/ef_dora)
        self.k_pipelines = {}
        
        # Pre-cargamos los motores para evitar delay en la primera respuesta.
        print("==> [Core] Cargando motores de voz Kokoro (en/es)...")
        self._get_pipeline_for_voice(self._voice_by_lang["en"])
        self._get_pipeline_for_voice(self._voice_by_lang["es"])
        
        # IMPORTANTE: NO llamamos a on_status aquí. La UI todavía está
        # construyéndose (ej. WebBridge aún no ha asignado self.core) y
        # cualquier callback que toque atributos de la UI explotaría.
        self._pending_voice_warning = None

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self.client is not None

    def shutdown(self) -> None:
        """Marca el núcleo como apagándose para que los bucles salgan."""
        self.stop_event.set()

    def reset_history(self) -> None:
        with self._history_lock:
            self._history.clear()

    # ------------------------------------------------------------------
    # Voz de salida (TTS con Kokoro)
    # ------------------------------------------------------------------

    def voice_for(self, lang: str) -> str:
        code = (lang or "en").lower()[:2]
        return self._voice_by_lang.get(code) or FALLBACK_VOICE

    def _get_pipeline_for_voice(self, voice_id: str) -> KPipeline:
        """Inicializa o recupera la pipeline de Kokoro basada en la inicial de la voz."""
        lang_code = voice_id[0]  # 'a' (american), 'b' (british), 'e' (es)
        if lang_code not in self.k_pipelines:
            # Especificamos repo_id para evitar el aviso de 'Defaulting...'
            self.k_pipelines[lang_code] = KPipeline(
                lang_code=lang_code, 
                model=True, 
                repo_id='hexgrad/Kokoro-82M'
            )
        return self.k_pipelines[lang_code]

    def _flush_pending_warnings(self) -> None:
        """Emite los avisos acumulados durante __init__ (cuando la UI ya existe)."""
        pass

    def speak(self, text: str, lang: str = "en") -> None:
        """
        Habla con la voz correcta según el idioma, utilizando Kokoro TTS local.
        Bloqueante. Usa un lock para serializar la voz.
        """
        if not text:
            return
        voice = self.voice_for(lang)
        pipeline = self._get_pipeline_for_voice(voice)
        
        self.on_speak(text, lang)
        with self._speech_lock:
            self._speaking_event.set()
            try:
                # Reproducimos cada fragmento generado por Kokoro en tiempo real para minimizar latencia
                for _, _, audio in pipeline(text, voice=voice, speed=1.0):
                    if self.stop_event.is_set():
                        break
                    if len(audio) > 0:
                        # sounddevice reproduce los arrays numpy. Kokoro genera en 24000 Hz.
                        sd.play(audio, samplerate=24000, blocking=True)
            except Exception as e:
                self.on_status("Error", f"TTS Error: {e}")
            finally:
                sd.stop()
                self._speaking_event.clear()

    def interrupt_speech(self) -> None:
        """
        Mata la reproducción de voz actual en sounddevice. Útil en shutdown.
        No bloquea.
        """
        try:
            sd.stop()
        except Exception:
            pass

    @property
    def is_speaking(self) -> bool:
        return self._speaking_event.is_set()

    def play_acknowledge_beep(self) -> None:
        """Pequeño beep para confirmar que se activó el wake-word."""
        try:
            subprocess.run(
                ["afplay", "/System/Library/Sounds/Tink.aiff"],
                check=False,
                timeout=2,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Reconocimiento
    # ------------------------------------------------------------------

    def calibrate(self, source: sr.Microphone, duration: float = 0.5) -> None:
        try:
            self.recognizer.adjust_for_ambient_noise(source, duration=duration)
        except Exception:
            pass

    def transcribe(self, audio: sr.AudioData) -> Optional[Tuple[str, str]]:
        """
        Transcribe el audio en AMBOS idiomas y elige el candidato cuyo texto
        sea internamente coherente con el idioma que dice ser. Antes usábamos
        solo la confianza de Google, pero el recognizer `es-ES` es tan
        permisivo que devuelve garabatos en español con confidence alta
        cuando hablas inglés — y eso robaba la elección al inglés real.

        Estrategia:
          1. Pedir ES y EN, quedarnos con el "top" de cada uno.
          2. Puntuar cada transcript por cuánto "parece" del idioma que dice
             ser (tildes, artículos, palabras-función).
          3. Ganador = mejor (net_coherencia, confidence). Empates → conf.

        Devuelve (texto, "es"|"en") o None si no entendió en ningún idioma.
        """
        candidates: list = []  # [(text, short, conf), ...]
        for lang_code, short in (("es-ES", "es"), ("en-US", "en")):
            try:
                result = self.recognizer.recognize_google(
                    audio, language=lang_code, show_all=True
                )
            except sr.UnknownValueError:
                # "No entendí nada en este idioma" no es un fallo: es la vida
                # normal del reconocedor con silencios o ruido. Probamos el
                # otro idioma sin escupir nada al log.
                continue
            except sr.RequestError:
                # Sin red, nada que hacer.
                return None

            # `recognize_google(show_all=True)` devuelve {} o "" cuando no
            # reconoce nada, y un dict con 'alternative' si reconoce.
            if not result:
                continue
            alternatives = (
                result.get("alternative", []) if isinstance(result, dict) else []
            )
            if not alternatives:
                continue

            top = alternatives[0]
            text = (top.get("transcript") or "").strip()
            if not text:
                continue
            # Google no siempre devuelve confidence. Cuando falta asumimos
            # 0.5 — lo suficientemente bajo para que cualquier otro idioma
            # con confidence explícita gane.
            conf = float(top.get("confidence", 0.5))
            candidates.append((text, short, conf))

        if not candidates:
            return None
        if len(candidates) == 1:
            return (candidates[0][0], candidates[0][1])

        # Dos candidatos — puntuamos cada uno por cuánto "parece" de su
        # idioma. `net` = soporte a su propio idioma menos soporte al otro.
        scored = []
        for text, lang, conf in candidates:
            scores = self._score_text_lang(text)
            other = "es" if lang == "en" else "en"
            net = scores[lang] - scores[other]
            # Guardamos también el score "propio" para reglas específicas.
            scored.append((net, conf, text, lang, scores[lang]))

        # Regla asimétrica a favor del inglés:
        # el reconocedor `es-ES` de Google es bastante permisivo y a menudo
        # devuelve una frase *plausible* en español aunque el audio sea en
        # inglés (p.ej. "what is the weather like" → "que es el wéder laik").
        # Esa frase tiene tildes y artículos, así que gana por coherencia
        # aunque el texto real no sea español. El inverso casi nunca pasa:
        # el reconocedor en-US rara vez hace una frase válida en inglés
        # cuando le hablas en español.
        #
        # Por tanto: si AMBOS transcripts son internamente coherentes con
        # su idioma (score_propio >= 2), damos la victoria al inglés,
        # salvo que el español aplaste al inglés por mucho margen.
        by_lang = {c[3]: c for c in scored}
        if "en" in by_lang and "es" in by_lang:
            en = by_lang["en"]
            es = by_lang["es"]
            en_own = en[4]
            es_own = es[4]
            if en_own >= 2 and es_own >= 2 and (es[0] - en[0]) <= 2:
                return (en[2], en[3])

        # Desempate por defecto: (coherencia desc, confianza desc).
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, text, lang, _ = scored[0]
        return (text, lang)

    # Marcadores para decidir si un transcript "parece" castellano o inglés.
    # No pretenden ser exhaustivos: solo contar palabras-función comunes que
    # difícilmente aparecen en el otro idioma. Espacios a los lados para que
    # `"the"` no matchee `"other"`.
    _ES_MARKERS: tuple = (
        " qué ", " cómo ", " cuál", " cuándo", " dónde", " por qué ",
        " porque ", " hola ", " buenos días", " buenas ", " gracias ",
        " eres ", " tengo ", " quiero ", " necesito ", " está ", " hace ",
        " mañana ", " hoy ", " ayer ", " puedes ", " señor", " señora",
        " el ", " la ", " los ", " las ", " un ", " una ", " unos ", " unas ",
        " de ", " en ", " es ", " y ", " para ", " con ", " por ", " que ",
        " muy ", " pero ", " también ",
    )
    _EN_MARKERS: tuple = (
        " the ", " is ", " are ", " was ", " were ", " what ", " what's ",
        " how ", " where ", " when ", " why ", " who ", " which ",
        " can ", " could ", " would ", " should ",
        " i ", " you ", " your ", " my ", " me ", " we ", " they ",
        " please ", " hello ", " hi ", " hey ", " sir ",
        " today ", " tomorrow ", " yesterday ", " now ",
        " and ", " or ", " of ", " to ", " with ", " in ", " on ", " at ",
        " do ", " does ", " did ", " have ", " has ", " had ",
        " tell ", " give ", " show ", " make ", " take ",
        " good morning ", " good evening ",
    )

    @classmethod
    def _score_text_lang(cls, text: str) -> dict:
        """Devuelve {'es': n, 'en': n} según cuántos marcadores de cada idioma
        aparecen en el texto. Un punto gordo (3) por tilde/ñ/¿/¡, un punto
        por cada palabra-función."""
        if not text:
            return {"es": 0, "en": 0}
        # Envolvemos con espacios para que los marcadores con espacios
        # (que evitan sub-matches) funcionen también al principio/final.
        padded = " " + text.lower() + " "
        es = 0
        if re.search(r"[áéíóúñ¿¡]", padded):
            es += 3
        for m in cls._ES_MARKERS:
            if m in padded:
                es += 1
        en = 0
        for m in cls._EN_MARKERS:
            if m in padded:
                en += 1
        return {"es": es, "en": en}

    def listen_phrase(
        self,
        source: sr.Microphone,
        timeout: float = 5,
        phrase_time_limit: float = 10,
    ) -> Optional[sr.AudioData]:
        try:
            return self.recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_time_limit
            )
        except sr.WaitTimeoutError:
            return None

    # ------------------------------------------------------------------
    # Wake-word
    # ------------------------------------------------------------------

    @staticmethod
    def contains_wake_word(text: str) -> bool:
        if not text:
            return False
        normalized = re.sub(r"[^a-záéíóúñü ]", " ", text.lower()).strip()
        return any(wake in normalized for wake in WAKE_WORDS)

    @staticmethod
    def strip_wake_word(text: str) -> str:
        """Quita el wake-word del comando si el usuario dijo todo en una frase."""
        if not text:
            return ""
        pattern = r"^\s*(hey |hola |oye )?jarvis[,.\s]*"
        return re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    # ------------------------------------------------------------------
    # Cerebro (Gemini)
    # ------------------------------------------------------------------

    def think(self, user_text: str, user_lang: Optional[str] = None) -> JarvisReply:
        """
        Manda la consulta a Gemini con Google Search activado para que pueda
        responder con info en tiempo real (tiempo, noticias, precios...).
        Si se conoce el idioma del usuario (detectado al transcribir), se lo
        pasamos explícitamente a Gemini; si no, lo detectamos por heurística.
        """
        if not self.client:
            return JarvisReply(
                lang="en",
                text="API key missing, sir. Please configure the environment.",
            )

        lang = (user_lang or self._guess_lang(user_text) or "en")[:2]
        if lang not in ("es", "en"):
            lang = "en"

        with self._history_lock:
            history_snapshot = list(self._history)

        # Construimos la conversación como turnos para que Gemini tenga contexto.
        contents = [
            types.Content(role=turn["role"], parts=[types.Part.from_text(text=turn["text"])])
            for turn in history_snapshot
        ]
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
        )

        # La herramienta google_search no se puede combinar con JSON mode ni
        # con response_schema, así que fijamos el idioma por system prompt.
        if lang == "es":
            lang_instruction = (
                " Responde SIEMPRE en castellano de España, tuteando al usuario."
            )
        else:
            lang_instruction = " Always reply in English."
        system_prompt = self.SYSTEM_PROMPT + lang_instruction

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.7,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - red / cuota / config
            return JarvisReply(
                lang=lang,
                text=f"I hit a snag talking to the brain, sir. ({exc.__class__.__name__})",
            )

        text = self._clean_text(response.text or "")
        if not text:
            text = (
                "Lo siento, no he obtenido respuesta." if lang == "es"
                else "Sorry, I got no answer from the brain."
            )

        with self._history_lock:
            self._history.append({"role": "user", "text": user_text})
            self._history.append({"role": "model", "text": text})

        return JarvisReply(lang=lang, text=text)

    @staticmethod
    def _clean_text(raw: str) -> str:
        """Quita markdown y citas porque suenan fatal cuando `say` los lee."""
        cleaned = raw.strip()
        # Bloques de código completos
        cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
        # Inline code `foo`
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        # Citas tipo [1], [2], [12]
        cleaned = re.sub(r"\[\d+\]", "", cleaned)
        # Links [texto](url) -> texto
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        # Markdown bold/italic/headers/blockquotes
        cleaned = re.sub(r"[*_#>]+", "", cleaned)
        # Espacios múltiples
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
        return cleaned

    @classmethod
    def _guess_lang(cls, text: str) -> str:
        """
        Detecta el idioma de un texto usando las mismas listas de marcadores
        que `_score_text_lang()`. Empate → inglés (consistente con la regla
        asimétrica que usamos en `transcribe()`).

        Se usa cuando:
          - El usuario escribe por el chat web (no hay detección de audio).
          - `transcribe()` devolvió idioma pero `think()` quiere contrastar.
        """
        if not text:
            return "en"
        scores = cls._score_text_lang(text)
        if scores["es"] > scores["en"]:
            return "es"
        if scores["en"] > scores["es"]:
            return "en"
        # Empate (ninguna marca reconocida). Caemos a la heurística mínima
        # de tildes para no perder casos cortos como "hola" sin espacios.
        lowered = text.lower()
        if re.search(r"[áéíóúñ¿¡]", lowered):
            return "es"
        # Palabras sueltas sin contexto: peso a marcadores concretos.
        for marker in ("hola", "gracias", "señor", "buenas", "dame", "dime",
                       "cuéntame", "cuenta me", "ayúdame", "ponme"):
            if marker in lowered:
                return "es"
        return "en"

    # ------------------------------------------------------------------
    # Bucle principal: escucha continua
    # ------------------------------------------------------------------

    def run_voice_loop(
        self,
        level_callback: Optional[Callable[[float], None]] = None,
        greeting: Optional[str] = None,
        wait_ready: bool = False,
        ready_timeout: float = 20.0,
    ) -> None:
        """
        Bucle principal en modo escucha continua. Estados:
        LISTENING -> (utterance detectada) -> THINKING -> SPEAKING -> LISTENING.

        `level_callback(rms)` recibe el nivel RMS (0..1) durante la escucha,
        para alimentar el visualizador.

        Si `wait_ready=True`, antes de saludar esperamos a que la UI haga
        `core.ready_event.set()` (útil en web, donde queremos que el
        navegador esté ya conectado al Socket.IO para que se vean los
        eventos del saludo).
        """
        # Avisos acumulados durante __init__ (voces que faltan, etc.).
        self._flush_pending_warnings()

        if wait_ready:
            # Esperamos a que la UI señale "listo"; si pasa el timeout
            # seguimos igualmente (mejor un saludo sin ver los eventos que
            # quedarse mudo para siempre).
            self.ready_event.wait(timeout=ready_timeout)

        if greeting:
            self.on_status("Speaking", greeting)
            self.speak(greeting, lang="en")

        if not self.ready:
            self.on_status(
                "Error",
                "Gemini API key is missing or invalid. Set GEMINI_API_KEY in .env.",
            )
            self.speak("Warning, sir. Gemini API key is missing.", lang="en")
            return

        in_listening = False
        while not self.stop_event.is_set():
            try:
                # Solo anunciamos "Listening" al entrar en ese estado.
                if not in_listening:
                    self.on_status("Listening", "Escuchando...")
                    in_listening = True

                # Usamos un timeout finito (no None) para que stop_event se
                # pueda revisar cada pocos segundos y cerrar limpio.
                # phrase_time_limit=20 + pause_threshold=1.0 permiten frases
                # de ~20 segundos con pausas naturales sin cortar.
                result = self._listen_once(
                    timeout=6,             # espera hasta 6s a que empieces a hablar
                    phrase_time_limit=20,  # corta la frase si supera 20s
                    level_callback=level_callback,
                )

                if self.stop_event.is_set():
                    break
                if not result:
                    # Silencio o no entendió — seguimos sin anunciar.
                    continue

                command, detected_lang = result
                in_listening = False

                # --- Pensar ---
                self.on_status("Thinking", f"User: {command}")
                reply = self.think(command, user_lang=detected_lang)
                if self.stop_event.is_set():
                    break

                # --- Hablar ---
                self.on_status("Speaking", reply.text)
                self.speak(reply.text, lang=reply.lang)
                if self.stop_event.is_set():
                    break

                # Cooldown post-habla: `say` libera su subprocess antes de
                # que el altavoz haya terminado físicamente de vibrar, y el
                # micro al reabrirse puede captar el eco. 1.2s es conservador
                # pero evita que Jarvis se auto-dispare.
                time.sleep(1.2)
            except Exception as exc:  # noqa: BLE001
                # Cualquier fallo NO debe matar el hilo del bucle. Lo
                # anunciamos a la UI, esperamos un poco y reintentamos.
                self.on_status(
                    "Error",
                    f"Loop crash ({exc.__class__.__name__}): {exc} — reintento en 2s",
                )
                time.sleep(2)
                in_listening = False

    def _listen_once(
        self,
        timeout: float,
        phrase_time_limit: float,
        level_callback: Optional[Callable[[float], None]] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Abre el micro UNA vez, escucha una frase y la transcribe.
        Devuelve (texto, idioma) o None. Si se proporciona `level_callback`,
        envolvemos el stream para emitir el nivel RMS en cada chunk que lea el
        reconocedor — sin competir por los samples.
        """
        try:
            with sr.Microphone() as source:
                # Recalibración corta cada vez que abrimos el mic: se
                # autoadapta al ambiente si ha cambiado (ventilador, etc.).
                self.calibrate(source, duration=0.4)

                if level_callback is not None:
                    source.stream = _LevelSniffingStream(
                        source.stream, source.SAMPLE_WIDTH, level_callback
                    )

                audio = self.listen_phrase(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit,
                )
        except OSError as exc:
            # Típicamente: mic sin permiso, mic ocupado por otra app, o
            # dispositivo de audio desconectado.
            self.on_status(
                "Error",
                f"Mic error: {exc}. Revisa Ajustes → Privacidad → Micrófono.",
            )
            return None
        except Exception as exc:  # noqa: BLE001
            # Cualquier otro fallo (PyAudio, hilos) — lo anunciamos en vez
            # de morir en silencio.
            self.on_status(
                "Error",
                f"Listen failure ({exc.__class__.__name__}): {exc}",
            )
            return None
        finally:
            # Devolvemos el visualizador a cero cuando cerramos el micro.
            if level_callback is not None:
                try:
                    level_callback(0.0)
                except Exception:
                    pass

        if audio is None:
            # Timeout sin audio: también lo logueamos (sin spam) para que
            # veas que el recognizer está vivo pero no te oye.
            return None

        # Transcribir, con protección ante fallos de red / Google.
        try:
            return self.transcribe(audio)
        except sr.UnknownValueError:
            # Defensa extra por si el UnknownValueError se cuela desde una
            # ruta que no cubrimos en `transcribe()`. Silencioso: no es un
            # error real, es "Google no entendió nada".
            return None
        except Exception as exc:  # noqa: BLE001
            self.on_status(
                "Error",
                f"Transcribe failure ({exc.__class__.__name__}): {exc}",
            )
            return None


# ---------------------------------------------------------------------------
# Medición de nivel de audio (para el visualizador del HUD)
# ---------------------------------------------------------------------------

class _LevelSniffingStream:
    """
    Proxy que envuelve el stream de sr.Microphone. Cada vez que el reconocedor
    pide un chunk, le pasamos los samples originales y además calculamos RMS
    para alimentar al visualizador. De este modo no competimos por datos con
    el listener.
    """

    # Un RMS ~6000 ya es voz clara, 20000 es grito. Normalizamos a 0..1.
    MAX_RMS = 6000.0

    def __init__(self, inner, sample_width: int, callback: Callable[[float], None]):
        import array

        self._inner = inner
        self._width = sample_width
        self._callback = callback
        # struct code según ancho de sample (16 bits -> 'h').
        self._array_code = {1: "b", 2: "h", 4: "i"}.get(sample_width, "h")
        self._array = array

    def read(self, size, *args, **kwargs):
        data = self._inner.read(size, *args, **kwargs)
        try:
            samples = self._array.array(self._array_code)
            samples.frombytes(data)
            if samples:
                # RMS manual (sin audioop, que está deprecated en 3.13).
                total = 0
                for s in samples:
                    total += s * s
                rms = (total / len(samples)) ** 0.5
                level = min(1.0, rms / self.MAX_RMS)
                self._callback(level)
        except Exception:
            pass
        return data

    def __getattr__(self, attr):
        # Delegamos cualquier otro método (close, write, etc.) al stream real.
        return getattr(self._inner, attr)


