/* ==========================================================================
   JARVIS — Front-end HUD
   - Reactor animado en canvas (3 anillos + núcleo + barras radiales)
   - Espectro lineal que reacciona al nivel de audio real del servidor
   - Chat con burbujas User/Jarvis
   - Botón de shutdown con overlay glitch + "Good bye, sir"
   ========================================================================== */

const socket = io({ reconnection: true });

/* ------- Helpers DOM ------- */
const $ = (id) => document.getElementById(id);
const statusTitle   = $('main-status');
const chat          = $('chat-content');
const commandInput  = $('command-input');
const sendBtn       = $('send-btn');
const shutdownBtn   = $('shutdown-btn');
const shutdownOv    = $('shutdown-overlay');
const voiceInd      = $('voice-indicator');
const langInd       = $('lang-indicator');
const tempEl        = $('temp');
const uptimeEl      = $('uptime');
const connDot       = $('connection-dot');

/* ------- Estado ------- */
const state = {
    mode: 'idle',             // idle | listening | thinking | speaking | offline
    level: 0,                 // nivel de audio (0..1) suavizado
    targetLevel: 0,
    tick: 0,
    bootedAt: Date.now(),
    history: new Array(48).fill(0),
};

function setMode(mode) {
    state.mode = mode;
    document.body.classList.remove(
        'state-idle', 'state-listening', 'state-thinking',
        'state-speaking', 'state-error', 'state-offline'
    );
    document.body.classList.add(`state-${mode}`);
}

/* ==========================================================================
   SOCKET
   ========================================================================== */
socket.on('connect', () => {
    connDot.classList.remove('disconnected');
});
socket.on('disconnect', () => {
    connDot.classList.add('disconnected');
});

// Los estados de diálogo ya empujan una burbuja vía chat_message,
// así que aquí ignoramos su `log` para no duplicar.
const DIALOGUE_STATUSES = new Set(['listening', 'thinking', 'speaking']);

socket.on('status_update', (data) => {
    const status = (data.status || 'idle').toLowerCase();
    statusTitle.innerText = (data.status || 'IDLE').toUpperCase();
    setMode(status);
    if (data.voice) voiceInd.innerText = data.voice;
    if (data.lang)  langInd.innerText  = data.lang.toUpperCase();
    if (data.log && !DIALOGUE_STATUSES.has(status)) {
        addBubble(data.log, status === 'error' ? 'error' : 'system');
    }
});

socket.on('chat_message', (data) => {
    const role = data.role === 'user' ? 'user' : 'jarvis';
    addBubble(data.text, role);
});

socket.on('audio_level', (data) => {
    state.targetLevel = Math.min(1, Math.max(0, data.level || 0));
});

socket.on('shutdown_ack', () => {
    triggerShutdownUI();
});

/* ==========================================================================
   CHAT
   ========================================================================== */
function addBubble(text, kind = 'system') {
    const b = document.createElement('div');
    b.className = `bubble ${kind}`;
    b.innerText = text;
    chat.appendChild(b);
    chat.scrollTop = chat.scrollHeight;
    // Limita a los últimos 60 mensajes para no ahogar el DOM.
    while (chat.children.length > 60) chat.removeChild(chat.firstChild);
}

function sendCommand() {
    const text = commandInput.value.trim();
    if (!text) return;
    socket.emit('send_command', { text });
    commandInput.value = '';
}

sendBtn.addEventListener('click', sendCommand);
commandInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendCommand();
});

/* ==========================================================================
   SHUTDOWN
   ========================================================================== */
shutdownBtn.addEventListener('click', () => {
    if (!confirm('¿Apagar Jarvis? Esto cierra el servidor.')) return;
    shutdownBtn.disabled = true;
    socket.emit('shutdown');
    // Si el servidor muere antes de emitir shutdown_ack, disparamos igualmente.
    setTimeout(triggerShutdownUI, 400);
});

function triggerShutdownUI() {
    shutdownOv.classList.remove('hidden');
    setMode('offline');
    statusTitle.innerText = 'OFFLINE';
}

/* ==========================================================================
   REACTOR CANVAS
   ========================================================================== */
const reactor = $('reactor-canvas');
const rctx = reactor.getContext('2d');
const RW = reactor.width, RH = reactor.height;

const PALETTES = {
    idle:      { outer: '#0a5c6b', middle: '#0a5c6b', inner: '#00f6ff', core: '#00f6ff', glow: '#00f6ff' },
    listening: { outer: '#ff3c3c', middle: '#882020', inner: '#00f6ff', core: '#ffffff', glow: '#ff3c3c' },
    thinking:  { outer: '#ffb14a', middle: '#ffb14a', inner: '#00f6ff', core: '#ffb14a', glow: '#ffb14a' },
    speaking:  { outer: '#00f6ff', middle: '#00f6ff', inner: '#ffffff', core: '#ffffff', glow: '#00f6ff' },
    offline:   { outer: '#333',    middle: '#222',    inner: '#444',    core: '#555',    glow: '#222' },
    error:     { outer: '#ff3c3c', middle: '#882020', inner: '#ff3c3c', core: '#ff3c3c', glow: '#ff3c3c' },
};

let angleOuter = 0, angleMiddle = 0;

function drawReactor() {
    const p = PALETTES[state.mode] || PALETTES.idle;
    const cx = RW / 2, cy = RH / 2;

    // Velocidades por estado
    if      (state.mode === 'thinking')  { angleOuter += 0.12; angleMiddle -= 0.17; }
    else if (state.mode === 'listening') { angleOuter += 0.04; angleMiddle -= 0.06; }
    else if (state.mode === 'speaking')  { angleOuter += 0.08; angleMiddle -= 0.04; }
    else                                 { angleOuter += 0.02; angleMiddle -= 0.03; }

    // Suavizado del nivel
    state.level += (state.targetLevel - state.level) * 0.3;
    // Decay del target para que no se quede clavado si deja de haber eventos
    state.targetLevel *= 0.96;

    const breathe = (Math.sin(state.tick / 20) + 1) / 2; // 0..1
    const pulse   = state.mode === 'listening'
        ? 0.6 + 0.4 * state.level
        : 0.85 + 0.15 * breathe;

    rctx.clearRect(0, 0, RW, RH);

    /* ---- Glow ---- */
    for (let i = 6; i >= 1; i--) {
        const r = 150 * pulse + i * 8;
        rctx.strokeStyle = hexAlpha(p.glow, 0.08 * i);
        rctx.lineWidth = 1;
        circle(cx, cy, r);
        rctx.stroke();
    }

    /* ---- Anillo exterior punteado ---- */
    dashedRing(cx, cy, 195, angleOuter, p.outer, 36, 0.14);
    dashedRing(cx, cy, 178, angleOuter * 0.8, p.outer, 72, 0.05);

    /* ---- Anillos medios ---- */
    dashedRing(cx, cy, 140, angleMiddle, p.middle, 18, 0.24);
    dashedRing(cx, cy, 130, angleMiddle, p.middle, 18, 0.24);

    /* ---- Anillo interior ---- */
    rctx.strokeStyle = p.inner;
    rctx.lineWidth = 2;
    circle(cx, cy, 92);
    rctx.stroke();

    /* ---- Barras radiales (reaccionan al audio) ---- */
    const bars = 64;
    const baseR = 100;
    for (let i = 0; i < bars; i++) {
        const a = (i / bars) * Math.PI * 2;
        const wave = (Math.sin(state.tick / 6 + i * 0.4) + 1) / 2;
        const len  = 4 + wave * 6 + state.level * 34;
        const x1 = cx + baseR * Math.cos(a);
        const y1 = cy + baseR * Math.sin(a);
        const x2 = cx + (baseR + len) * Math.cos(a);
        const y2 = cy + (baseR + len) * Math.sin(a);
        rctx.strokeStyle = (i % 3 === 0) ? p.core : p.outer;
        rctx.lineWidth = 2;
        rctx.beginPath();
        rctx.moveTo(x1, y1); rctx.lineTo(x2, y2);
        rctx.stroke();
    }

    /* ---- Núcleo ---- */
    const coreR = 46 * pulse;
    const grad = rctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
    grad.addColorStop(0,   '#ffffff');
    grad.addColorStop(0.6, p.core);
    grad.addColorStop(1,   hexAlpha(p.glow, 0));
    rctx.fillStyle = grad;
    circle(cx, cy, coreR);
    rctx.fill();

    /* ---- Cross hairs ---- */
    rctx.strokeStyle = p.outer;
    rctx.lineWidth = 1;
    [[-1, 0], [1, 0], [0, -1], [0, 1]].forEach(([dx, dy]) => {
        rctx.beginPath();
        rctx.moveTo(cx + dx * 210, cy + dy * 210);
        rctx.lineTo(cx + dx * 195, cy + dy * 195);
        rctx.stroke();
    });
}

function dashedRing(cx, cy, r, angle, color, segments, length) {
    rctx.strokeStyle = color;
    rctx.lineWidth = 2.5;
    const step = (Math.PI * 2) / segments;
    for (let i = 0; i < segments; i++) {
        const a1 = angle + i * step;
        const a2 = a1 + length;
        rctx.beginPath();
        rctx.arc(cx, cy, r, a1, a2);
        rctx.stroke();
    }
}

function circle(cx, cy, r) {
    rctx.beginPath();
    rctx.arc(cx, cy, r, 0, Math.PI * 2);
}

function hexAlpha(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/* ==========================================================================
   SPECTRUM CANVAS
   ========================================================================== */
const spec = $('spectrum-canvas');
const sctx = spec.getContext('2d');
const SW = spec.width, SH = spec.height;
const BARS = 40;
const specHist = new Array(BARS).fill(0);

function drawSpectrum() {
    sctx.clearRect(0, 0, SW, SH);

    // Push the smoothed level into a rolling buffer
    specHist.shift();
    const noise = (Math.sin(state.tick / 5) + 1) / 2 * 0.06;
    specHist.push(state.level + noise);

    const barW = SW / BARS;
    const mid  = SH / 2;
    for (let i = 0; i < BARS; i++) {
        const v = specHist[i];
        const h = Math.max(2, v * (SH - 6));
        const x = i * barW + barW * 0.2;
        sctx.fillStyle = blendToWhite('#00f6ff', Math.min(1, v));
        sctx.fillRect(x, mid - h / 2, barW * 0.6, h);
    }
}

function blendToWhite(hex, t) {
    const n = parseInt(hex.slice(1), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    const mix = (c) => Math.round(c * (1 - t) + 255 * t);
    return `rgb(${mix(r)}, ${mix(g)}, ${mix(b)})`;
}

/* ==========================================================================
   LOOP + UPTIME/TEMP
   ========================================================================== */
function loop() {
    state.tick++;
    drawReactor();
    drawSpectrum();
    requestAnimationFrame(loop);
}
loop();

setInterval(() => {
    // Temperatura "simulada" (guiño al HUD)
    tempEl.innerText = (30 + Math.random() * 4).toFixed(1) + '°C';

    // Uptime real
    const s = Math.floor((Date.now() - state.bootedAt) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    uptimeEl.innerText = `${mm}:${ss}`;
}, 1000);

setMode('idle');
