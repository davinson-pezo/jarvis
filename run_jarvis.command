#!/bin/bash
# Script para arrancar Jarvis Web sin complicaciones de compilación.
# Haz doble clic para iniciar.

# Obtener la carpeta donde está este script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=== J.A.R.V.I.S. Neural Link ==="
echo "Iniciando entorno virtual..."

if [ ! -d ".venv" ]; then
    echo "ERROR: No se encuentra la carpeta .venv."
    echo "Por favor, ejecuta setup.command primero."
    read -p "Presiona Enter para salir..."
    exit 1
fi

# Matar procesos previos en el puerto 5005
lsof -ti:5005 | xargs kill -9 2>/dev/null || true

source .venv/bin/activate
echo "Cargando cerebro y motores de voz..."
python jarvis_web.py
