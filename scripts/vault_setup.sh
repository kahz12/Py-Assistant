#!/bin/bash
# ═══════════════════════════════════════════════════
# vault_setup.sh — Configuración inicial del vault LUKS2
# Solo se ejecuta UNA VEZ durante la instalación
# ═══════════════════════════════════════════════════
set -e

VAULT_IMG="${VAULT_IMG:-/home/$(whoami)/vault.img}"
VAULT_SIZE_MB="${VAULT_SIZE_MB:-2048}"  # 2GB por defecto
MAPPER_NAME="assistant_vault"
MOUNT_POINT="/mnt/assistant_vault"

echo "═══════════════════════════════════════════"
echo "🔐 SETUP DE VAULT LUKS2"
echo "═══════════════════════════════════════════"
echo ""
echo "  Imagen:    $VAULT_IMG"
echo "  Tamaño:    ${VAULT_SIZE_MB}MB"
echo "  Montaje:   $MOUNT_POINT"
echo ""

# Verificar root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Este script requiere root. Ejecuta con: sudo $0"
    exit 1
fi

# Verificar que cryptsetup esté instalado
if ! command -v cryptsetup &> /dev/null; then
    echo "📦 Instalando cryptsetup..."
    apt-get install -y cryptsetup
fi

# Verificar que no exista ya
if [ -f "$VAULT_IMG" ]; then
    echo "⚠️  $VAULT_IMG ya existe."
    read -p "¿Sobreescribir? (s/n): " confirm
    if [ "$confirm" != "s" ]; then
        echo "Cancelado."
        exit 0
    fi
    rm -f "$VAULT_IMG"
fi

# 1. Crear imagen de disco
echo ""
echo "📀 Creando imagen de disco (${VAULT_SIZE_MB}MB)..."
dd if=/dev/zero of="$VAULT_IMG" bs=1M count="$VAULT_SIZE_MB" status=progress

# 2. Formatear con LUKS2
echo ""
echo "🔐 Formateando con LUKS2..."
echo "   Se te pedirá crear una contraseña para el vault."
echo ""
cryptsetup luksFormat --type luks2 "$VAULT_IMG"

# 3. Abrir el vault
echo ""
echo "🔓 Abriendo vault..."
cryptsetup open "$VAULT_IMG" "$MAPPER_NAME"

# 4. Formatear sistema de archivos
echo ""
echo "📁 Creando sistema de archivos ext4..."
mkfs.ext4 /dev/mapper/"$MAPPER_NAME"

# 5. Crear punto de montaje y montar
mkdir -p "$MOUNT_POINT"
mount /dev/mapper/"$MAPPER_NAME" "$MOUNT_POINT"

# 6. Crear estructura de directorios
echo ""
echo "📂 Creando estructura del vault..."
mkdir -p "$MOUNT_POINT"/{conversations,media,notes}
touch "$MOUNT_POINT"/soul_state.md
touch "$MOUNT_POINT"/user_profile.md
touch "$MOUNT_POINT"/facts.md
touch "$MOUNT_POINT"/long_term_memory.md

# 7. Permisos
chown -R "$(logname):$(logname)" "$MOUNT_POINT"
chmod 700 "$MOUNT_POINT"

# 8. Desmontar
echo ""
echo "🔒 Cerrando vault..."
umount "$MOUNT_POINT"
cryptsetup close "$MAPPER_NAME"

echo ""
echo "═══════════════════════════════════════════"
echo "✅ VAULT LUKS2 CONFIGURADO EXITOSAMENTE"
echo "═══════════════════════════════════════════"
echo ""
echo "Para usarlo, ejecuta:"
echo "  sudo scripts/vault_mount.sh mount"
echo ""
echo "En config/settings.yaml, cambia:"
echo "  vault.path: $MOUNT_POINT"
echo "  vault.encryption_method: luks2"
echo ""
