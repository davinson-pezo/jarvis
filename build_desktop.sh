#!/bin/bash
# Compila la versión de escritorio (Tkinter) en dist/Jarvis.app
set -e

echo "==> [Desktop] Compilando Jarvis.app..."
pyinstaller \
  --noconfirm \
  --windowed \
  --name "Jarvis" \
  --osx-bundle-identifier com.jarvis.desktop \
  --add-data "jarvis_core.py:." \
  --collect-data customtkinter \
  --hidden-import "google.genai" \
  --hidden-import "pydantic" \
  jarvis_app.py

echo "==> [Desktop] Permiso de micrófono en Info.plist..."
plutil -insert NSMicrophoneUsageDescription \
  -string "Jarvis necesita el micrófono para escucharte." \
  dist/Jarvis.app/Contents/Info.plist || true

echo "==> [Desktop] Firmando ad-hoc..."
xattr -cr dist/Jarvis.app
codesign --force --deep --sign - dist/Jarvis.app

echo "[OK] dist/Jarvis.app"
