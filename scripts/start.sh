#!/bin/bash
# start.sh — Script de arranque del Asistente Personal AI
# Uso: bash scripts/start.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════╗"
echo "║   [BOOT] Asistente Personal AI       ║"
echo "╚══════════════════════════════════════╝"

# 1. Verificar que Python está disponible
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 no encontrado. Instálalo primero."
    exit 1
fi

# 2. Activar entorno virtual si existe
if [ -d "$PROJECT_DIR/venv" ]; then
    echo "[BOOT] Activando entorno virtual..."
    source "$PROJECT_DIR/venv/bin/activate"
elif [ -d "$PROJECT_DIR/.venv" ]; then
    echo "[BOOT] Activando entorno virtual..."
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo "[WARN] No se encontró entorno virtual. Usando Python del sistema."
fi

# 3. Verificar archivo .env
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "⚠️  Archivo .env no encontrado."
    echo "   Copia .env.example a .env y configura tus API keys."
    exit 1
fi

# 4. Crear directorio de logs
mkdir -p "$PROJECT_DIR/logs"

# 5. Iniciar el asistente
echo "[BOOT] Iniciando asistente..."
cd "$PROJECT_DIR"
python3 main.py

echo "[BOOT] Asistente detenido."
