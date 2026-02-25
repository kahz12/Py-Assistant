# Despliegue en Orange Pi Zero 2W

> **Hardware objetivo:** Orange Pi Zero 2W (2GB RAM, Cortex-A53 @1.5GHz, aarch64)

## Imagen de SO Recomendada

| Opcion | Enlace | Notas |
|---|---|---|
| **Armbian** (recomendado) | [armbian.com](https://www.armbian.com/orange-pi-zero-2w/) | Bookworm + kernel 6.6, Python 3.11 |
| Ubuntu Server 22.04 | Imagen oficial Orange Pi | Alternativa estable |

Flashear con `balenaEtcher` o `rpi-imager` a una microSD ≥16GB (Class 10 / A1).

---

## 1. Configuracion Inicial del Hardware

```bash
# Conectar via SSH (usuario: root / orangepi)
ssh root@<IP_ORANGE_PI>

# Cambiar contrasena y crear usuario no-root
passwd
adduser aria
usermod -aG sudo aria

# Configurar hostname
hostnamectl set-hostname pyassistant
```

---

## 2. Clonar o Transferir el Proyecto

**Opcion A — Git (recomendado):**
```bash
# En el Orange Pi
git clone https://github.com/tu-usuario/Py-Assistant.git ~/Py-Assistant
```

**Opcion B — Transferencia directa desde tu PC:**
```bash
# En tu PC
rsync -avz --exclude='venv/' --exclude='memory_vault/' \
    ~/Py-Assistant/ aria@orangepi.local:~/Py-Assistant/
```

---

## 3. Ejecutar el Script de Despliegue

```bash
cd ~/Py-Assistant
bash scripts/deploy_orange_pi.sh
```

El script instala automaticamente:
- Python 3.11+ y dependencias del sistema (ffmpeg, libssl-dev, etc.)
- Entorno virtual Python con todos los paquetes de `requirements.txt`
- Servicio `systemd` con restart automático y hardening de seguridad

---

## 4. Configurar Variables de Entorno

```bash
nano ~/Py-Assistant/.env
```

Minimo necesario:
```
TELEGRAM_BOT_TOKEN=tu_token
GROQ_API_KEY=tu_clave_groq
```

Permisos correctos:
```bash
chmod 600 ~/Py-Assistant/.env
```

---

## 5. Arrancar y Verificar el Servicio

```bash
# Arrancar el servicio
sudo systemctl start pyassistant

# Verificar estado
sudo systemctl status pyassistant

# Ver logs en tiempo real
journalctl -u pyassistant -f

# Dashboard de monitoreo (en el mismo Orange Pi)
curl http://localhost:8765/status
```

---

## 6. LUKS2 para el Vault (Opcional, Alta Seguridad)

Si quieres cifrado a nivel de bloque para el `memory_vault/`:

```bash
# Instalar herramientas
sudo apt install -y cryptsetup

# Crear contenedor LUKS2 de 2GB
dd if=/dev/zero of=~/vault.img bs=1M count=2048
sudo cryptsetup luksFormat --type luks2 ~/vault.img

# Abrir y formatear
sudo cryptsetup open ~/vault.img vault_crypt
sudo mkfs.ext4 /dev/mapper/vault_crypt

# Montar
sudo mkdir -p /mnt/vault
sudo mount /dev/mapper/vault_crypt /mnt/vault
sudo chown aria:aria /mnt/vault

# Enlazar al proyecto
ln -s /mnt/vault ~/Py-Assistant/memory_vault
```

> [!NOTE]
> Necesitarás desbloquear el vault manualmente tras cada reinicio del hardware.

---

## 7. Monitoreo Remoto

Acceder al dashboard desde tu PC (via SSH tunnel):
```bash
ssh -L 8765:localhost:8765 aria@orangepi.local
# Luego abre en tu navegador: http://localhost:8765
```

Ver logs remotamente:
```bash
ssh aria@orangepi.local 'journalctl -u pyassistant -n 50 --no-pager'
```

---

## Especificaciones de Rendimiento Esperadas

| Metrica | Estimacion en Zero 2W |
|---|---|
| RAM en reposo | ~120MB |
| RAM con carga | ~200-280MB |
| Latencia respuesta (Groq) | 2-5s (depende de network) |
| Latencia con Ollama local | 15-60s (modelo pequeño) |
| Temperatura max | ~65°C (sin disipador), ~45°C (con disipador) |

> [!WARNING]
> Ollama con modelos ≥7B parámetros **no es viable** en el Zero 2W por restricciones de RAM (2GB). Usa modelos cuantizados `q4_0` de ≤3B parámetros, o usa Groq/OpenAI via API.
