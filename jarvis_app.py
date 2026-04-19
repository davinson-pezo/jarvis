"""
jarvis_app.py — aplicación de escritorio de Jarvis.

Arquitectura:
- JarvisCore (en jarvis_core.py) hace todo el trabajo de audio, Gemini y voz.
- Esta capa solo se encarga de la ventana Tkinter/CustomTkinter:
  - HUD central con arc reactor (Canvas) reaccionando al estado.
  - Barras de visualizador que responden al nivel real del micrófono.
  - Panel lateral con la conversación.
  - Botón SHUTDOWN con despedida animada ("Good bye, sir").
"""

from __future__ import annotations

import math
import os
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import List

import customtkinter as ctk
from dotenv import load_dotenv

from jarvis_core import JarvisCore


def _load_env() -> None:
    """Busca el .env en rutas típicas (para que el .app lo encuentre)."""
    here = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(here, ".env"),
        os.path.join(os.getcwd(), ".env"),
        os.path.expanduser("~/.jarvis/.env"),
        os.path.expanduser("~/Documents/jarvis_project/.env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            load_dotenv(path)
            return
    load_dotenv()


_load_env()

# ---------------------------------------------------------------------------
# Paleta estilo HUD
# ---------------------------------------------------------------------------
BG = "#05090f"
PANEL_BG = "#0a141f"
CYAN = "#00f6ff"
DIM_CYAN = "#0a5c6b"
RED = "#ff3c3c"
GOLD = "#ffb14a"
WHITE = "#ffffff"


@dataclass
class ReactorPalette:
    outer: str
    middle: str
    inner: str
    core: str
    glow: str


PALETTES = {
    "idle":      ReactorPalette(DIM_CYAN, DIM_CYAN, CYAN,   CYAN, CYAN),
    "listening": ReactorPalette(RED,      "#882020", CYAN,   WHITE, RED),
    "thinking":  ReactorPalette(GOLD,     GOLD,      CYAN,   GOLD,  GOLD),
    "speaking":  ReactorPalette(CYAN,     CYAN,      WHITE,  WHITE, CYAN),
    "offline":   ReactorPalette("#333",   "#222",    "#444", "#555", "#222"),
}


# ---------------------------------------------------------------------------
# Widget del reactor (puro Canvas + bucle de animación)
# ---------------------------------------------------------------------------

class ReactorCanvas(tk.Canvas):
    """Arc reactor animado. Reacciona al estado y al nivel de audio."""

    SIZE = 360

    def __init__(self, master):
        super().__init__(
            master,
            width=self.SIZE,
            height=self.SIZE,
            bg=BG,
            highlightthickness=0,
            bd=0,
        )
        self._state = "idle"
        self._audio_level = 0.0
        self._smoothed_level = 0.0
        self._angle_outer = 0.0
        self._angle_middle = 0.0
        self._tick = 0
        self._running = True
        self._animate()

    # Público
    def set_state(self, state: str) -> None:
        state = state.lower()
        if state not in PALETTES:
            state = "idle"
        self._state = state

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))

    def stop(self) -> None:
        self._running = False

    # Animación
    def _animate(self) -> None:
        if not self._running:
            return
        self._tick += 1
        # suavizado exponencial para que el visualizador no tiemble
        self._smoothed_level += (self._audio_level - self._smoothed_level) * 0.3

        palette = PALETTES[self._state]
        # Velocidades según estado
        if self._state == "thinking":
            self._angle_outer = (self._angle_outer + 6) % 360
            self._angle_middle = (self._angle_middle - 9) % 360
        elif self._state == "listening":
            self._angle_outer = (self._angle_outer + 2) % 360
            self._angle_middle = (self._angle_middle - 3) % 360
        elif self._state == "speaking":
            self._angle_outer = (self._angle_outer + 4) % 360
            self._angle_middle = (self._angle_middle - 2) % 360
        else:
            self._angle_outer = (self._angle_outer + 1) % 360
            self._angle_middle = (self._angle_middle - 1.5) % 360

        self._draw(palette)
        self.after(33, self._animate)  # ~30 FPS

    def _draw(self, p: ReactorPalette) -> None:
        self.delete("all")
        cx = cy = self.SIZE / 2

        # "Respiración" del reactor: una onda base + el nivel de audio real.
        breathe = (math.sin(self._tick / 14.0) + 1) / 2  # 0..1
        pulse = 0.6 + 0.4 * self._smoothed_level if self._state == "listening" else 0.85 + 0.15 * breathe

        # --- Glow ---
        glow_r = 130 * pulse
        for i in range(6, 0, -1):
            r = glow_r + i * 6
            color = _mix(p.glow, BG, 0.85 - i * 0.12)
            self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=1)

        # --- Aro exterior punteado (rotando) ---
        outer_r = 155
        self._dashed_ring(cx, cy, outer_r, self._angle_outer, p.outer, segments=36, length=6)

        # --- Aro medio (doble) ---
        middle_r = 110
        self._dashed_ring(cx, cy, middle_r, self._angle_middle, p.middle, segments=18, length=10)
        self._dashed_ring(cx, cy, middle_r - 8, self._angle_middle, p.middle, segments=18, length=10)

        # --- Aro interior fijo ---
        inner_r = 72
        self.create_oval(
            cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
            outline=p.inner, width=2,
        )

        # --- Barras de visualización radial ---
        self._spectrum_bars(cx, cy, p)

        # --- Núcleo ---
        core_r = 38 * pulse
        self.create_oval(
            cx - core_r, cy - core_r, cx + core_r, cy + core_r,
            fill=p.core, outline=p.glow, width=2,
        )

        # --- HUD cross hairs ---
        self.create_line(cx - 170, cy, cx - 155, cy, fill=p.outer, width=1)
        self.create_line(cx + 155, cy, cx + 170, cy, fill=p.outer, width=1)
        self.create_line(cx, cy - 170, cx, cy - 155, fill=p.outer, width=1)
        self.create_line(cx, cy + 155, cx, cy + 170, fill=p.outer, width=1)

    def _dashed_ring(self, cx, cy, r, angle_deg, color, segments, length):
        step = 360 / segments
        for i in range(segments):
            a1 = math.radians(angle_deg + i * step)
            a2 = math.radians(angle_deg + i * step + length)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            self.create_line(x1, y1, x2, y2, fill=color, width=2)

    def _spectrum_bars(self, cx, cy, p: ReactorPalette) -> None:
        """Barras radiales que reaccionan al nivel de audio."""
        bars = 48
        base_r = 82
        level = self._smoothed_level
        for i in range(bars):
            angle = math.radians(i * (360 / bars))
            # Componente determinista + componente audio
            wave = (math.sin((self._tick / 8.0) + i * 0.4) + 1) / 2
            length = 6 + wave * 4 + level * 26
            x1 = cx + base_r * math.cos(angle)
            y1 = cy + base_r * math.sin(angle)
            x2 = cx + (base_r + length) * math.cos(angle)
            y2 = cy + (base_r + length) * math.sin(angle)
            color = p.outer if i % 3 else p.core
            self.create_line(x1, y1, x2, y2, fill=color, width=2)


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    """Mezcla lineal entre dos colores hex (#rgb o #rrggbb) con factor 0..1."""
    a = _parse_hex(hex_a)
    b = _parse_hex(hex_b)
    r = tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))
    return f"#{r[0]:02x}{r[1]:02x}{r[2]:02x}"


def _parse_hex(h: str) -> tuple:
    """Acepta #rgb o #rrggbb y devuelve (r, g, b) en 0..255."""
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"hex inválido: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# Visualizador lineal de audio (barra bajo el reactor)
# ---------------------------------------------------------------------------

class SpectrumBar(tk.Canvas):
    WIDTH = 720
    HEIGHT = 56
    BARS = 36

    def __init__(self, master):
        super().__init__(
            master, width=self.WIDTH, height=self.HEIGHT,
            bg=BG, highlightthickness=0, bd=0,
        )
        self._history: List[float] = [0.0] * self.BARS
        self._level = 0.0
        self._running = True
        self._tick = 0
        self._animate()

    def set_level(self, level: float):
        self._level = max(0.0, min(1.0, level))

    def stop(self):
        self._running = False

    def _animate(self):
        if not self._running:
            return
        self._tick += 1
        # Empujamos el histórico para dar sensación de onda en movimiento.
        self._history.pop(0)
        # Ruido pequeño para que no esté plana del todo cuando no hay voz.
        noise = (math.sin(self._tick / 6.0) + 1) / 2 * 0.08
        self._history.append(self._level + noise)
        self._draw()
        self.after(40, self._animate)

    def _draw(self):
        self.delete("all")
        bar_w = self.WIDTH / self.BARS
        mid = self.HEIGHT / 2
        for i, v in enumerate(self._history):
            h = max(2, v * (self.HEIGHT - 6))
            x = i * bar_w + bar_w * 0.2
            color = _mix(CYAN, WHITE, min(1.0, v))
            self.create_rectangle(
                x, mid - h / 2, x + bar_w * 0.6, mid + h / 2,
                fill=color, outline="",
            )


# ---------------------------------------------------------------------------
# Aplicación principal
# ---------------------------------------------------------------------------

class JarvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("J A R V I S — V 3")
        self.geometry("880x680")
        self.resizable(False, False)
        self.configure(fg_color=BG)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        # --- Header ------------------------------------------------------
        header = ctk.CTkFrame(self, fg_color=BG, height=60)
        header.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(
            header,
            text="J.A.R.V.I.S.  v3  //  NEURAL LINK",
            font=("Helvetica", 12, "bold"),
            text_color=CYAN,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(
            header,
            text="INITIALIZING",
            font=("Helvetica", 16, "bold"),
            text_color=CYAN,
        )
        self.status_label.pack(side="right")

        # --- Cuerpo: reactor + log ---------------------------------------
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=20, pady=12)

        # Reactor a la izquierda
        reactor_frame = ctk.CTkFrame(body, fg_color=BG, width=380)
        reactor_frame.pack(side="left")
        self.reactor = ReactorCanvas(reactor_frame)
        self.reactor.pack(padx=4, pady=4)

        # Log a la derecha
        log_frame = ctk.CTkFrame(
            body, fg_color=PANEL_BG, border_width=1, border_color=DIM_CYAN,
        )
        log_frame.pack(side="right", fill="both", expand=True, padx=(12, 0))

        ctk.CTkLabel(
            log_frame, text="TRANSMISSION LOG",
            font=("Helvetica", 11, "bold"), text_color=CYAN,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.log_box = ctk.CTkTextbox(
            log_frame, font=("Courier", 12),
            text_color="#c8d8e8", fg_color="#050a10",
            wrap="word", border_width=0,
        )
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")

        # Sub-header con idioma/voz actuales
        self.meta_label = ctk.CTkLabel(
            log_frame, text="voice: — | lang: —",
            font=("Courier", 10), text_color=DIM_CYAN,
        )
        self.meta_label.pack(anchor="e", padx=12, pady=(0, 8))

        # --- Visualizador lineal ----------------------------------------
        self.spectrum = SpectrumBar(self)
        self.spectrum.pack(pady=(4, 8))

        # --- Footer: shutdown + wake hint -------------------------------
        footer = ctk.CTkFrame(self, fg_color=BG)
        footer.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkLabel(
            footer,
            text="Continuous listening: habla cuando quieras",
            font=("Helvetica", 11),
            text_color=DIM_CYAN,
        ).pack(side="left")

        self.close_btn = ctk.CTkButton(
            footer, text="SHUTDOWN",
            font=("Helvetica", 12, "bold"),
            fg_color="#330000", hover_color="#880000",
            text_color=WHITE, width=140, height=36,
            corner_radius=4,
            command=self.shutdown_jarvis,
        )
        self.close_btn.pack(side="right")

        # --- Núcleo ------------------------------------------------------
        api_key = os.getenv("GEMINI_API_KEY")
        self.core = JarvisCore(
            api_key=api_key,
            on_status=self._on_status,
            on_speak=self._on_speak,
        )

        # Nivel de audio: el callback puede llegar desde otro hilo, así que
        # no tocamos widgets directamente — solo una variable atómica.
        self._level = 0.0

        # Pump del nivel al visualizador desde el hilo principal
        self.after(33, self._pump_level)

        self.protocol("WM_DELETE_WINDOW", self.shutdown_jarvis)

        # Arrancar Jarvis en background
        self._voice_thread = threading.Thread(target=self._run_core, daemon=True)
        self._voice_thread.start()

    # ------------------------------------------------------------------
    # Bucle del núcleo en background
    # ------------------------------------------------------------------

    def _run_core(self):
        self.core.run_voice_loop(
            level_callback=self._set_level,
            greeting="Good evening, sir. Systems are online.",
        )

    def _set_level(self, level: float) -> None:
        # Llamado desde hilo de audio — solo guardamos.
        self._level = level

    def _pump_level(self):
        self.reactor.set_audio_level(self._level)
        self.spectrum.set_level(self._level)
        # Decay natural si no llega nada nuevo.
        self._level *= 0.92
        self.after(33, self._pump_level)

    # ------------------------------------------------------------------
    # Callbacks del núcleo (pueden venir de otro hilo)
    # ------------------------------------------------------------------

    def _on_status(self, status: str, log: str) -> None:
        # `after(0, ...)` marsh all al hilo de UI.
        self.after(0, self._update_ui, status, log)

    def _on_speak(self, text: str, lang: str) -> None:
        self.after(0, self._update_meta, lang)

    def _update_ui(self, status: str, log: str) -> None:
        self.status_label.configure(text=status.upper())
        self.reactor.set_state(status)
        if log:
            self._append_log(log)

    def _update_meta(self, lang: str) -> None:
        voice = self.core.voice_for(lang)
        self.meta_label.configure(text=f"voice: {voice}  |  lang: {lang}")

    def _append_log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"› {line}\n")
        self.log_box.see("end")
        # Recorta si crece demasiado.
        if int(self.log_box.index("end-1c").split(".")[0]) > 400:
            self.log_box.delete("1.0", "200.0")
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown_jarvis(self) -> None:
        """Despedida con animación de fade y cierre limpio."""
        self.close_btn.configure(state="disabled", text="SHUTTING DOWN...")
        self.status_label.configure(text="SHUTTING DOWN", text_color=RED)
        self.reactor.set_state("offline")
        self._append_log("Good bye, sir.")
        # Cortamos el bucle y el `say` que pudiera estar sonando para que el
        # adiós pueda empezar de inmediato (antes se quedaba detrás).
        self.core.shutdown()
        self.core.interrupt_speech()

        # Despedida bloqueante en un hilo para que la UI se vea apagarse.
        def _farewell():
            self.core.speak("Good bye, sir.", lang="en")
            # Espera a que termine el último `say` y luego destruye todo.
            self.after(0, self._hard_close)

        threading.Thread(target=_farewell, daemon=True).start()

    def _hard_close(self) -> None:
        try:
            self.reactor.stop()
            self.spectrum.stop()
        except Exception:
            pass
        try:
            self.destroy()
        finally:
            os._exit(0)


if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
