#!/usr/bin/env bash
# =============================================================================
# scripts/deploy_orange_pi.sh -- Despliegue de Py-Assistant en Orange Pi Zero 2W
#
# Uso:
#   1. Desde tu PC (via SSH):
#       scp -r ~/Py-Assistant user@orangepi.local:~/
#       ssh user@orangepi.local "bash ~/Py-Assistant/scripts/deploy_orange_pi.sh"
#
#   2. Directamente en el Orange Pi:
#       bash scripts/deploy_orange_pi.sh
#
# Variables de entorno configurables (sobreescribir antes de correr):
#   PYBOT_USER   : usuario del sistema para el servicio (default: $USER)
#   PYBOT_DIR    : directorio de instalacion (default: ~/Py-Assistant)
#   PYBOT_VAULT  : directorio del vault (default: dentro de PYBOT_DIR)
# =============================================================================
set -euo pipefail

# -- Colores --
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

info()  { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*"; exit 1; }

PYBOT_USER="${PYBOT_USER:-$USER}"
PYBOT_DIR="${PYBOT_DIR:-$HOME/Py-Assistant}"
PYBOT_VENV="$PYBOT_DIR/venv"
SERVICE_NAME="pyassistant"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo ""
echo "=========================================="
echo "  Py-Assistant — Deploy Orange Pi Zero 2W"
echo "=========================================="
echo ""

# -- Verificar que somos ARM --
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]] && [[ "$ARCH" != "armv7l" ]]; then
    warn "Arquitectura detectada: $ARCH (esperado aarch64/armv7l)"
    warn "Este script esta disenado para Orange Pi / Raspberry Pi."
    read -r -p "¿Continuar de todas formas? [y/N] " resp
    [[ "$resp" =~ ^[Yy]$ ]] || error "Abortado."
fi

# -- 1. Dependencias del sistema --
info "Paso 1: Instalando dependencias del sistema..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git ffmpeg build-essential libssl-dev \
    curl wget htop screen tmux

# Verificar version de Python
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python $PY_VERSION detectado."
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
    info "Python >= 3.11 ✅"
else
    warn "Python < 3.11 detectado. El asistente requiere >= 3.11."
    warn "Considera instalar Python 3.11+ desde deadsnakes PPA."
fi

# -- 2. Preparar directorio --
info "Paso 2: Preparando directorio de instalacion: $PYBOT_DIR"
mkdir -p "$PYBOT_DIR"
cd "$PYBOT_DIR"

# -- 3. Entorno virtual --
info "Paso 3: Creando entorno virtual Python..."
if [[ ! -d "$PYBOT_VENV" ]]; then
    python3 -m venv "$PYBOT_VENV"
    info "Entorno virtual creado en: $PYBOT_VENV"
else
    info "Entorno virtual ya existe."
fi

info "Instalando dependencias de Python (requirements.txt)..."
"$PYBOT_VENV/bin/pip" install --upgrade pip -q
"$PYBOT_VENV/bin/pip" install -r requirements.txt -q
info "Dependencias instaladas ✅"

# -- 4. Configurar .env si no existe --
if [[ ! -f "$PYBOT_DIR/.env" ]]; then
    warn ".env no encontrado. Copiando .env.example como plantilla..."
    cp "$PYBOT_DIR/.env.example" "$PYBOT_DIR/.env"
    chmod 600 "$PYBOT_DIR/.env"
    warn "IMPORTANTE: Edita $PYBOT_DIR/.env con tus API keys antes de arrancar."
    warn "  nano $PYBOT_DIR/.env"
else
    info ".env ya configurado ✅"
fi

# -- 5. Crear directorios de runtime --
info "Paso 4: Creando directorios de runtime..."
mkdir -p "$PYBOT_DIR/memory_vault"
mkdir -p "$PYBOT_DIR/memory_vault/waq"
mkdir -p "$PYBOT_DIR/memory_vault/notes"
mkdir -p "$PYBOT_DIR/memory_vault/media"
mkdir -p "$PYBOT_DIR/logs"
chmod 700 "$PYBOT_DIR/memory_vault"
info "Directorios creados ✅"

# -- 6. Servicio systemd --
info "Paso 5: Configurando servicio systemd '$SERVICE_NAME'..."

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Py-Assistant — Asistente Personal IA
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${PYBOT_USER}
WorkingDirectory=${PYBOT_DIR}
ExecStart=${PYBOT_VENV}/bin/python3 ${PYBOT_DIR}/main.py
Restart=always
RestartSec=10s
StandardOutput=append:${PYBOT_DIR}/logs/assistant.log
StandardError=append:${PYBOT_DIR}/logs/assistant.log

# Hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=${PYBOT_DIR}

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
info "Servicio systemd configurado ✅"

# -- 7. Resumen final --
echo ""
echo "=========================================="
echo "  ✅ INSTALACION COMPLETADA"
echo "=========================================="
echo ""
echo "  Directorio : $PYBOT_DIR"
echo "  Servicio   : $SERVICE_NAME"
echo "  Dashboard  : http://localhost:8765"
echo ""
echo "  Próximos pasos:"
echo "  1. Edita el .env:   nano $PYBOT_DIR/.env"
echo "  2. Arranca:         sudo systemctl start $SERVICE_NAME"
echo "  3. Ver logs:        journalctl -u $SERVICE_NAME -f"
echo "  4. Dashboard:       curl http://localhost:8765/status"
echo ""
