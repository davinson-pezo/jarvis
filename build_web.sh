#!/bin/bash
# Compila la versión web (Flask + SocketIO) en dist/Jarvis Web.app
# Al hacer doble clic arranca el servidor y abre Safari en localhost:5005
set -e

echo "==> [Web] Compilando Jarvis Web.app..."
pyinstaller \
  --noconfirm \
  --windowed \
  --name "Jarvis Web" \
  --osx-bundle-identifier com.jarvis.web \
  --add-data "jarvis_core.py:." \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --hidden-import "engineio.async_drivers.threading" \
  --hidden-import "google.genai" \
  --hidden-import "pydantic" \
  --hidden-import "charset_normalizer" \
  jarvis_web.py

echo "==> [Web] Permiso de micrófono en Info.plist..."
plutil -insert NSMicrophoneUsageDescription \
  -string "Jarvis necesita el micrófono para escucharte." \
  "dist/Jarvis Web.app/Contents/Info.plist" || true

# LSUIElement=true marca la app como "agente de UI": arranca el servidor
# Flask y abre Safari, pero NO aparece en el Dock ni en el App Switcher.
# Esto soluciona el icono botando eternamente (macOS esperaba una ventana
# nativa que este bundle nunca crea; su UI es el navegador). Se cierra
# desde el botón de shutdown del HUD o desde Activity Monitor.
echo "==> [Web] LSUIElement en Info.plist (agente sin Dock)..."
plutil -insert LSUIElement -bool true \
  "dist/Jarvis Web.app/Contents/Info.plist" || \
plutil -replace LSUIElement -bool true \
  "dist/Jarvis Web.app/Contents/Info.plist"

echo "==> [Web] Firmando ad-hoc..."
xattr -cr "dist/Jarvis Web.app"
codesign --force --deep --sign - "dist/Jarvis Web.app"

echo "[OK] dist/Jarvis Web.app"
