#!/bin/bash
# ==========================================================
# vault_backup.sh -- Backup cifrado del vault
# Uso: vault_backup.sh [destino]
#
# El backup se comprime con tar+gzip y se cifra con GPG
# (cifrado simetrico AES-256). La passphrase se solicita
# de forma interactiva o via variable BACKUP_PASSPHRASE.
# ==========================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Vault por defecto (desarrollo = memory_vault, produccion = /mnt/assistant_vault)
VAULT_PATH="${VAULT_PATH:-$PROJECT_DIR/memory_vault}"
BACKUP_DIR="${1:-$HOME/backups/asistente}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/vault_backup_$DATE.tar.gz.gpg"

# Maximo de backups a retener
MAX_BACKUPS="${MAX_BACKUPS:-7}"

echo "==========================================="
echo "  BACKUP CIFRADO DEL VAULT"
echo "==========================================="
echo "  Origen:  $VAULT_PATH"
echo "  Destino: $BACKUP_FILE"
echo ""

# Verificar que el vault existe
if [ ! -d "$VAULT_PATH" ]; then
    echo "[ERROR] Vault no encontrado: $VAULT_PATH"
    exit 1
fi

# Verificar que gpg esta instalado
if ! command -v gpg &> /dev/null; then
    echo "[ERROR] gpg no esta instalado. Instala con: sudo apt install gnupg"
    exit 1
fi

# Crear directorio de backups con permisos restrictivos
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Crear backup comprimido y cifrado (SEC-08)
echo "[*] Creando backup cifrado..."
if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
    # Modo no interactivo (cron, systemd)
    tar -cz \
        -C "$(dirname "$VAULT_PATH")" \
        "$(basename "$VAULT_PATH")" \
        --exclude="*.pyc" \
        --exclude="__pycache__" \
        | gpg --symmetric --cipher-algo AES256 \
              --batch --yes --passphrase "$BACKUP_PASSPHRASE" \
              -o "$BACKUP_FILE"
else
    # Modo interactivo (solicita passphrase)
    tar -cz \
        -C "$(dirname "$VAULT_PATH")" \
        "$(basename "$VAULT_PATH")" \
        --exclude="*.pyc" \
        --exclude="__pycache__" \
        | gpg --symmetric --cipher-algo AES256 \
              -o "$BACKUP_FILE"
fi

# Verificar y proteger el backup
if [ -f "$BACKUP_FILE" ]; then
    chmod 600 "$BACKUP_FILE"
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[OK] Backup cifrado creado: $BACKUP_FILE ($SIZE)"
else
    echo "[ERROR] Error creando backup"
    exit 1
fi

# Limpiar backups antiguos (retener los ultimos N)
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/vault_backup_*.tar.gz.gpg 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt "$MAX_BACKUPS" ]; then
    echo ""
    echo "[*] Limpiando backups antiguos (reteniendo $MAX_BACKUPS)..."
    ls -1t "$BACKUP_DIR"/vault_backup_*.tar.gz.gpg | tail -n +$((MAX_BACKUPS + 1)) | xargs rm -f
    DELETED=$((BACKUP_COUNT - MAX_BACKUPS))
    echo "    Eliminados: $DELETED backups antiguos"
fi

# Listar backups existentes
echo ""
echo "Backups existentes:"
ls -1th "$BACKUP_DIR"/vault_backup_*.tar.gz.gpg 2>/dev/null | head -5 | while read f; do
    size=$(du -h "$f" | cut -f1)
    echo "  $(basename "$f") ($size)"
done

echo ""
echo "==========================================="
echo "[OK] BACKUP CIFRADO COMPLETADO"
echo "==========================================="
echo ""
echo "Para restaurar:"
echo "  gpg -d $BACKUP_FILE | tar -xzf - -C /destino/"
