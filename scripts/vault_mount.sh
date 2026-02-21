#!/bin/bash
# ═══════════════════════════════════════════════════
# vault_mount.sh — Monta/desmonta el vault LUKS2
# Uso: vault_mount.sh [mount|unmount|status]
# ═══════════════════════════════════════════════════
set -e

VAULT_IMG="${VAULT_IMG:-/home/$(whoami)/vault.img}"
MAPPER_NAME="assistant_vault"
MOUNT_POINT="/mnt/assistant_vault"

mount_vault() {
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        echo "✅ Vault ya está montado en $MOUNT_POINT"
        return 0
    fi

    if [ ! -f "$VAULT_IMG" ]; then
        echo "❌ No se encontró $VAULT_IMG"
        echo "   Ejecuta primero: sudo scripts/vault_setup.sh"
        exit 1
    fi

    echo "🔓 Abriendo vault LUKS2..."
    cryptsetup open "$VAULT_IMG" "$MAPPER_NAME"

    mkdir -p "$MOUNT_POINT"
    mount /dev/mapper/"$MAPPER_NAME" "$MOUNT_POINT"

    echo "✅ Vault montado en $MOUNT_POINT"
}

unmount_vault() {
    if ! mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        echo "ℹ️  Vault no está montado."
        # Intentar cerrar mapper si existe
        if [ -e /dev/mapper/"$MAPPER_NAME" ]; then
            cryptsetup close "$MAPPER_NAME" 2>/dev/null || true
        fi
        return 0
    fi

    echo "🔒 Desmontando vault..."
    umount "$MOUNT_POINT"
    cryptsetup close "$MAPPER_NAME"
    echo "✅ Vault cerrado y desmontado."
}

status_vault() {
    echo "═══════════════════════════════════"
    echo "📊 ESTADO DEL VAULT"
    echo "═══════════════════════════════════"

    if [ -f "$VAULT_IMG" ]; then
        size=$(du -h "$VAULT_IMG" 2>/dev/null | cut -f1)
        echo "  📀 Imagen: $VAULT_IMG ($size)"
    else
        echo "  ❌ Imagen no encontrada: $VAULT_IMG"
    fi

    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        used=$(df -h "$MOUNT_POINT" | tail -1 | awk '{print $3}')
        avail=$(df -h "$MOUNT_POINT" | tail -1 | awk '{print $4}')
        pct=$(df -h "$MOUNT_POINT" | tail -1 | awk '{print $5}')
        echo "  ✅ Montado en: $MOUNT_POINT"
        echo "  💾 Usado: $used / Disponible: $avail ($pct)"
    else
        echo "  🔒 Vault no está montado"
    fi

    echo "═══════════════════════════════════"
}

# Verificar root para mount/unmount
if [ "$1" = "mount" ] || [ "$1" = "unmount" ]; then
    if [ "$EUID" -ne 0 ]; then
        echo "❌ Requiere root. Ejecuta con: sudo $0 $1"
        exit 1
    fi
fi

case "$1" in
    mount)   mount_vault ;;
    unmount) unmount_vault ;;
    status)  status_vault ;;
    *)
        echo "Uso: $0 [mount|unmount|status]"
        echo ""
        echo "  mount    — Monta el vault LUKS2"
        echo "  unmount  — Desmonta y cierra el vault"
        echo "  status   — Muestra el estado del vault"
        ;;
esac
