#!/bin/bash
# Doble clic en Finder para ejecutar.
# Recrea el venv desde cero, instala todo y compila las dos .app.
set -e

# Vamos al directorio donde vive este script
cd "$(dirname "$0")"

echo "============================================"
echo "  JARVIS — SETUP Y BUILD COMPLETO"
echo "============================================"
echo

if ! command -v brew >/dev/null 2>&1; then
  echo "[ERROR] No veo Homebrew instalado. Instálalo primero desde https://brew.sh"
  read -n 1 -s -r -p "Pulsa una tecla para cerrar..."
  exit 1
fi

PY=$(command -v python3.14 || command -v python3)
echo "[1/5] Usando Python: $PY ($($PY --version))"

echo
echo "[2/5] Comprobando Tk..."
if ! $PY -c "import tkinter" 2>/dev/null; then
  echo "      Instalando python-tk (se requiere una vez)..."
  brew install python-tk@3.14 || brew install python-tk
fi

echo
echo "[3/5] Recreando el entorno virtual..."
deactivate 2>/dev/null || true
rm -rf .venv
$PY -m venv .venv
source .venv/bin/activate

echo
echo "[4/5] Instalando dependencias..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo
echo "[5/5] Compilando las dos apps (esto tarda 1-2 minutos)..."
./build_app.sh

echo
echo "============================================"
echo "  LISTO"
echo "============================================"
echo
echo "Aplicaciones generadas:"
echo "  - dist/Jarvis.app        (escritorio)"
echo "  - dist/Jarvis Web.app    (HUD en navegador)"
echo
echo "Si quieres, cópialas a /Applications."
echo

read -n 1 -s -r -p "Pulsa una tecla para cerrar..."
