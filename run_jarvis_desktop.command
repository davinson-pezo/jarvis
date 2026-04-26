#!/bin/bash
# Script para arrancar Jarvis Desktop sin complicaciones de compilación.
# Haz doble clic para iniciar.

# Obtener la carpeta donde está este script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== J.A.R.V.I.S. Desktop System ==="
echo "Iniciando entorno virtual..."

if [ ! -d ".venv" ]; then
    echo "ERROR: No se encuentra la carpeta .venv."
    exit 1
fi

source .venv/bin/activate
echo "Cargando HUD y motores de voz..."
python jarvis_app.py
