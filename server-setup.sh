#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# server-setup.sh — Первичная настройка VPS с нуля (Ubuntu 22.04)
# Запускать ОДИН РАЗ под root сразу после создания сервера
#
# Использование:
#   ssh root@YOUR_SERVER_IP
#   curl -sSL https://raw.githubusercontent.com/YOURNAME/REPO/main/server-setup.sh | bash
#   или загрузить вручную и запустить: chmod +x server-setup.sh && ./server-setup.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${COLOR_GREEN}[✓]${NC} $1"; }
warn() { echo -e "${COLOR_YELLOW}[!]${NC} $1"; }
err()  { echo -e "${COLOR_RED}[✗]${NC} $1"; exit 1; }

[ "$EUID" -eq 0 ] || err "Запускать от root: sudo bash server-setup.sh"

# ── 1. Обновление системы ─────────────────────────────────────────────────────
log "Обновление пакетов..."
apt-get update -q && apt-get upgrade -y -q

# ── 2. Базовые утилиты ────────────────────────────────────────────────────────
log "Установка базовых утилит..."
apt-get install -y -q \
    curl wget git unzip htop ufw fail2ban \
    ca-certificates gnupg lsb-release

# ── 3. Docker ─────────────────────────────────────────────────────────────────
log "Установка Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    log "Docker установлен: $(docker --version)"
else
    warn "Docker уже установлен: $(docker --version)"
fi

# ── 4. Docker Compose plugin ──────────────────────────────────────────────────
log "Проверка Docker Compose..."
docker compose version &>/dev/null || \
    apt-get install -y docker-compose-plugin
log "Docker Compose: $(docker compose version)"

# ── 5. Создание деплой-пользователя ──────────────────────────────────────────
DEPLOY_USER="deploy"
if ! id "$DEPLOY_USER" &>/dev/null; then
    log "Создание пользователя $DEPLOY_USER..."
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
    usermod -aG docker "$DEPLOY_USER"
    mkdir -p /home/$DEPLOY_USER/.ssh
    chmod 700 /home/$DEPLOY_USER/.ssh

    # Копируем authorized_keys от root (для CI/CD)
    if [ -f /root/.ssh/authorized_keys ]; then
        cp /root/.ssh/authorized_keys /home/$DEPLOY_USER/.ssh/
        chown -R "$DEPLOY_USER:$DEPLOY_USER" /home/$DEPLOY_USER/.ssh
        chmod 600 /home/$DEPLOY_USER/.ssh/authorized_keys
        log "SSH ключи скопированы в $DEPLOY_USER"
    fi
else
    warn "Пользователь $DEPLOY_USER уже существует"
fi

# ── 6. Директория приложения ──────────────────────────────────────────────────
APP_DIR="/opt/trainer-bot"
log "Создание директории $APP_DIR..."
mkdir -p "$APP_DIR"/{data,backups}
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

# ── 7. Firewall (UFW) ─────────────────────────────────────────────────────────
log "Настройка файрвола..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
# Для webhook-варианта (опционально): ufw allow 443/tcp
ufw --force enable
log "UFW статус:"
ufw status

# ── 8. Fail2ban ───────────────────────────────────────────────────────────────
log "Настройка fail2ban..."
systemctl enable fail2ban
systemctl start fail2ban

# ── 9. SSH hardening ──────────────────────────────────────────────────────────
log "Усиление SSH..."
sed -i 's/#PermitRootLogin yes/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# ── 10. Автообновление безопасности ──────────────────────────────────────────
log "Настройка автообновлений..."
apt-get install -y -q unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades

# ── 11. Ротация логов ─────────────────────────────────────────────────────────
cat > /etc/logrotate.d/trainer-bot << 'EOF'
/opt/trainer-bot/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 0644 deploy deploy
}
EOF

# ── 12. Итог ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
log "Сервер готов к деплою!"
echo ""
echo "Следующие шаги:"
echo "  1. Загрузить код: su - deploy && cd /opt/trainer-bot && git clone REPO ."
echo "  2. Создать .env: cp .env.example .env && nano .env"
echo "  3. Запустить: docker compose up -d --build"
echo "  4. Проверить: docker compose logs -f"
echo "═══════════════════════════════════════════════════════════"
