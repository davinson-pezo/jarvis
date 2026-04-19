#!/bin/bash
# Construye LAS DOS .app (desktop + web) en dist/.
# Requiere: source .venv/bin/activate  &&  pip install pyinstaller
set -e

echo "==> Preparando entorno..."
source .venv/bin/activate

echo "==> Limpiando compilaciones previas..."
rm -rf build dist Jarvis.spec "Jarvis Web.spec"

bash build_desktop.sh
bash build_web.sh

echo
echo "[OK] Las dos apps están en:"
echo "     dist/Jarvis.app         (escritorio)"
echo "     dist/Jarvis Web.app     (servidor web + abre navegador)"
