# 🚀 Деплой Flaka Bot на Google Cloud VM (systemd)

> Метод: **systemd** — надёжный автозапуск, параллельная работа с другим ботом
> Репозиторий: `TelegramFlaka`

---

## 📌 Шаг 1 — Подключиться к VM

```bash
# Через gcloud CLI:
gcloud compute ssh INSTANCE_NAME --zone=ZONE

# Или через обычный SSH:
ssh your_user@EXTERNAL_IP
```

---

## 📌 Шаг 2 — Клонировать репозиторий

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/TelegramFlaka.git
cd TelegramFlaka
```

---

## 📌 Шаг 3 — Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> ✅ Убедись что всё установилось без ошибок

---

## 📌 Шаг 4 — Создать .env файл

```bash
nano .env
```

Вставь свои значения:
```env
TELEGRAM_TOKEN=токен_от_BotFather
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...        # для Whisper (голосовые сообщения)
```

Сохрани: `Ctrl+O` → `Enter` → `Ctrl+X`

Защити файл:
```bash
chmod 600 .env
```

---

## 📌 Шаг 5 — Проверить что бот запускается вручную

```bash
source venv/bin/activate
python main.py
```

Должно появиться:
```
Bot starting...
Database ready
Scheduler started
```

Если всё ок — `Ctrl+C` и идём дальше.

---

## 📌 Шаг 6 — Создать systemd service

```bash
# Узнать своего пользователя и полный путь
whoami
pwd
```

Запомни результаты — они нужны в следующей команде.

```bash
sudo nano /etc/systemd/system/flaka-bot.service
```

Вставь (замени `YOUR_USER` и `YOUR_HOME_PATH` на свои значения):

```ini
[Unit]
Description=Flaka Trainer Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/TelegramFlaka
ExecStart=/home/YOUR_USER/TelegramFlaka/venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/home/YOUR_USER/TelegramFlaka/.env
StandardOutput=journal
StandardError=journal
SyslogIdentifier=flaka-bot

[Install]
WantedBy=multi-user.target
```

**Пример для пользователя `vladislav`:**
```ini
User=vladislav
WorkingDirectory=/home/vladislav/TelegramFlaka
ExecStart=/home/vladislav/TelegramFlaka/venv/bin/python main.py
EnvironmentFile=/home/vladislav/TelegramFlaka/.env
```

---

## 📌 Шаг 7 — Запустить

```bash
# Перезагрузить конфиги systemd
sudo systemctl daemon-reload

# Включить автозапуск при ребуте сервера
sudo systemctl enable flaka-bot

# Запустить прямо сейчас
sudo systemctl start flaka-bot

# Проверить статус
sudo systemctl status flaka-bot
```

✅ Если всё хорошо, увидишь:
```
● flaka-bot.service - Flaka Trainer Telegram Bot
     Active: active (running) since Mon 2026-03-09 ...
```

---

## 📌 Шаг 8 — Проверка параллельной работы ботов

```bash
# Оба бота должны быть active (running)
sudo systemctl status flaka-bot
sudo systemctl status ИМЯ_ВТОРОГО_БОТА

# Посмотреть все запущенные сервисы
systemctl list-units --type=service --state=running | grep bot
```

Боты работают **полностью независимо** — падение одного не влияет на другой.

---

## 🛠️ Команды управления

```bash
# Статус
sudo systemctl status flaka-bot

# Логи в реальном времени
sudo journalctl -u flaka-bot -f

# Последние 50 строк логов
sudo journalctl -u flaka-bot -n 50

# Логи за последний час
sudo journalctl -u flaka-bot --since "1 hour ago"

# Перезапустить
sudo systemctl restart flaka-bot

# Остановить
sudo systemctl stop flaka-bot
```

---

## 🔄 Обновление бота (после git push)

```bash
cd ~/TelegramFlaka

# Получить изменения
git pull

# Обновить зависимости если изменился requirements.txt
source venv/bin/activate
pip install -r requirements.txt

# Перезапустить
sudo systemctl restart flaka-bot

# Проверить
sudo systemctl status flaka-bot
```

---

## ❗ Частые ошибки

**`Failed to start` — бот не запускается:**
```bash
sudo journalctl -u flaka-bot -n 30
# Смотри на строки с ERROR или Traceback
```

**`No module named X`:**
```bash
source ~/TelegramFlaka/venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart flaka-bot
```

**`EnvironmentFile not found`:**
```bash
ls -la ~/TelegramFlaka/.env
# Если нет — создай заново (шаг 4)
```

**Telegram ошибка `Conflict: terminated by other getUpdates`:**
> Значит бот уже запущен в другом месте (другой терминал, другой сервер).
```bash
# Остановить все дубли
sudo systemctl stop flaka-bot
pkill -f "python main.py"
sudo systemctl start flaka-bot
```

---

## ✅ Финальная проверка

```bash
# 1. Оба бота запущены
sudo systemctl is-active flaka-bot     # → active
sudo systemctl is-active second-bot    # → active

# 2. Автозапуск включён
sudo systemctl is-enabled flaka-bot    # → enabled

# 3. Живые логи без ошибок
sudo journalctl -u flaka-bot -n 20
```

Напиши `/start` своему боту в Telegram — должен ответить 🎉
