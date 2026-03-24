# 🚀 Деплой Trainer Bot на VPS

## Рекомендуемый сервер

| Провайдер | Тариф | Цена | Характеристики |
|-----------|-------|------|----------------|
| **Hetzner** | CX11 | €3.29/мес | 1 vCPU, 2GB RAM, 20GB SSD — **рекомендуется** |
| DigitalOcean | Basic | $4/мес | 1 vCPU, 1GB RAM, 25GB SSD |

> Бот потребляет ~50-80 MB RAM. CX11 более чем достаточно.

---

## ⚡ Быстрый старт (5 шагов)

### 1. Создать сервер

- Зарегистрироваться на [hetzner.com](https://hetzner.com) или [digitalocean.com](https://digitalocean.com)
- Создать VPS: **Ubuntu 22.04 LTS**, добавить SSH ключ
- Записать IP-адрес сервера

### 2. Настройка сервера (один раз)

```bash
# Подключиться по SSH
ssh root@YOUR_SERVER_IP

# Скачать и запустить скрипт настройки
curl -sSL https://raw.githubusercontent.com/YOURNAME/REPO/main/server-setup.sh -o setup.sh
chmod +x setup.sh && ./setup.sh
```

Скрипт автоматически установит Docker, создаст пользователя `deploy`, настроит файрвол и hardening.

### 3. Клонировать репозиторий

```bash
# Переключиться на деплой-пользователя
su - deploy

# Клонировать проект
git clone https://github.com/YOURNAME/trainer-bot.git /opt/trainer-bot
cd /opt/trainer-bot
```

### 4. Настроить переменные среды

```bash
cp .env.example .env
nano .env
```

Заполнить обязательно:
```env
TELEGRAM_TOKEN=ваш_токен_от_BotFather
ANTHROPIC_API_KEY=ваш_ключ_от_console.anthropic.com
```

### 5. Запустить бота

```bash
docker compose up -d --build

# Проверить что работает
docker compose ps
docker compose logs -f
```

**Готово! Бот работает.** Он будет автоматически перезапускаться при сбоях.

---

## 🔁 Настройка автодеплоя через GitHub Actions

После первого ручного деплоя — настроить CI/CD, чтобы `git push` автоматически обновлял бота.

### Шаг 1: Создать SSH-ключ для CI/CD

```bash
# На своей машине (не на сервере)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/trainer_deploy_key

# Скопировать публичный ключ на сервер
ssh-copy-id -i ~/.ssh/trainer_deploy_key.pub deploy@YOUR_SERVER_IP
```

### Шаг 2: Добавить секреты в GitHub

Перейти в: **GitHub репозиторий → Settings → Secrets and variables → Actions → New repository secret**

| Имя секрета | Значение |
|-------------|----------|
| `SERVER_HOST` | IP-адрес сервера |
| `SERVER_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | Содержимое `~/.ssh/trainer_deploy_key` (приватный ключ) |
| `SERVER_PORT` | `22` (необязательно) |

### Шаг 3: Пуш = автодеплой

```bash
git add .
git commit -m "feat: update prompts"
git push origin main
# → GitHub Actions автоматически задеплоит изменения
```

Статус деплоя виден в: **GitHub репозиторий → Actions**

---

## 📋 Команды управления

```bash
# Все команды выполнять в /opt/trainer-bot

# Статус бота
./deploy.sh --status

# Логи в реальном времени
./deploy.sh --logs
# или напрямую:
docker compose logs -f --tail=100

# Обновить из git и перезапустить
./deploy.sh

# Пересобрать образ (после изменений зависимостей)
./deploy.sh --build

# Перезапустить без обновления
./deploy.sh --restart

# Остановить бота
./deploy.sh --stop

# Запустить снова
docker compose up -d
```

---

## 💾 Резервные копии

Бот делает автоматический бэкап БД каждое 1-е число месяца в `backups/`.

**Ручной бэкап:**
```bash
cp /opt/trainer-bot/data/trainer.db \
   /opt/trainer-bot/backups/manual-$(date +%Y%m%d-%H%M%S).db
```

**Скачать БД на свою машину:**
```bash
# На своей машине:
scp deploy@YOUR_SERVER_IP:/opt/trainer-bot/data/trainer.db ./trainer_backup.db
```

---

## 🔄 Откат к предыдущей версии

```bash
cd /opt/trainer-bot

# Посмотреть историю коммитов
git log --oneline -10

# Откатиться к конкретному коммиту
git checkout abc1234

# Перезапустить с этой версией
docker compose up -d --build
```

---

## 📊 Мониторинг (бесплатно)

Настроить [UptimeRobot](https://uptimerobot.com) для мониторинга доступности:
- Это Telegram-бот, не HTTP-сервис, поэтому прямой пинг не работает
- Вместо этого: мониторим SSH-доступность или docker healthcheck

**Уведомления о падениях через Telegram:**
```bash
# Добавить в crontab (crontab -e):
*/5 * * * * docker inspect trainer_bot --format='{{.State.Status}}' | grep -q running || \
  curl -s "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage?chat_id=YOUR_CHAT_ID&text=⚠️+Бот+упал!"
```

---

## 🔧 Troubleshooting

**Бот не отвечает:**
```bash
docker compose logs --tail=50
# Искать ошибки: ERROR, CRITICAL, Traceback
```

**Ошибка токена:**
```bash
cat .env | grep TELEGRAM_TOKEN
# Убедиться что токен без пробелов и кавычек
```

**Бот не стартует после ребута сервера:**
```bash
# Docker должен стартовать автоматически (systemctl enable docker)
# Проверить:
sudo systemctl status docker
docker compose ps
# Если не поднялся:
cd /opt/trainer-bot && docker compose up -d
```

**Нет места на диске:**
```bash
df -h
docker system prune -a  # Очистить все неиспользуемые образы
# Очистить старые бэкапы:
ls -lh /opt/trainer-bot/backups/
rm /opt/trainer-bot/backups/pre-deploy-*.db  # Удалить старые CI бэкапы
```

---

## 🔐 Безопасность

После настройки сервера:
- ✅ SSH только по ключу (пароли отключены)
- ✅ Файрвол: открыт только порт 22
- ✅ Fail2ban защищает от брутфорса
- ✅ Docker контейнер запускается от non-root пользователя
- ✅ `.env` никогда не попадает в git
- ✅ Автообновления безопасности Ubuntu включены
