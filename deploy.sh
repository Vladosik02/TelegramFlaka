#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# deploy.sh — Ручной деплой / обновление бота на сервере
# Запускать на сервере от пользователя deploy
#
# Использование:
#   ./deploy.sh           — обновить из git и перезапустить
#   ./deploy.sh --build   — пересобрать образ (после изменений кода)
#   ./deploy.sh --logs    — показать логи
#   ./deploy.sh --status  — статус контейнера
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
APP_DIR="/opt/trainer-bot"
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${COLOR_GREEN}[✓]${NC} $1"; }
warn() { echo -e "${COLOR_YELLOW}[!]${NC} $1"; }
err()  { echo -e "${COLOR_RED}[✗]${NC} $1"; exit 1; }

cd "$APP_DIR" || err "Директория $APP_DIR не найдена. Клонируй репозиторий сначала."

# ── Флаги ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
    --logs)
        docker compose logs -f --tail=100
        exit 0
        ;;
    --status)
        docker compose ps
        docker stats trainer_bot --no-stream
        exit 0
        ;;
    --restart)
        log "Перезапуск без обновления..."
        docker compose restart
        log "Готово"
        exit 0
        ;;
    --stop)
        warn "Остановка бота..."
        docker compose down
        log "Бот остановлен"
        exit 0
        ;;
esac

# ── 1. Проверка .env ──────────────────────────────────────────────────────────
[ -f .env ] || err ".env не найден! Скопируй .env.example и заполни токены."

# ── 2. Обновление кода из git ─────────────────────────────────────────────────
log "Получение обновлений из git..."
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ] && [ "${1:-}" != "--build" ]; then
    warn "Код уже актуален. Используй --build для принудительной пересборки."
    docker compose ps
    exit 0
fi

git pull origin main
log "Код обновлён: $LOCAL → $(git rev-parse HEAD)"

# ── 3. Бэкап БД перед деплоем ────────────────────────────────────────────────
if [ -f "data/trainer.db" ]; then
    BACKUP_NAME="backups/pre-deploy-$(date +%Y%m%d-%H%M%S).db"
    cp data/trainer.db "$BACKUP_NAME"
    log "БД сохранена: $BACKUP_NAME"
fi

# ── 4. Сборка и запуск ────────────────────────────────────────────────────────
log "Сборка образа..."
docker compose build --no-cache

log "Запуск контейнера..."
docker compose up -d

# ── 5. Проверка ───────────────────────────────────────────────────────────────
log "Ожидание старта (15 сек)..."
sleep 15

if docker compose ps | grep -q "Up"; then
    log "Бот запущен успешно!"
    docker compose ps
else
    err "Что-то пошло не так. Логи:"
    docker compose logs --tail=50
fi

# ── 6. Очистка старых образов ─────────────────────────────────────────────────
log "Очистка старых Docker-образов..."
docker image prune -f --filter "until=24h"

echo ""
log "Деплой завершён. Мониторинг: ./deploy.sh --logs"
