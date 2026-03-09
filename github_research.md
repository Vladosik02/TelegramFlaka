# 🔍 GitHub Research — Telegram Fitness/Trainer Bots
> Что можно позаимствовать для нашего бота. Обновлено: 08.03.2026

---

## ⭐ ТОП-5 репозиториев для изучения

### 1. NextSet Fitness Tracker Telegram Bot
🔗 https://github.com/voevodinaua-lab/NextSet-Fitness-Tracker-Telegram-Bot
**Stars:** активный, PostgreSQL, Python
**Что делает:** силовые + кардио тренировки, статистика, экспорт CSV/Excel, замеры тела, кастомные упражнения
**Что взять:**
- Архитектура handlers по домену: `handlers_training.py`, `handlers_statistics.py`, `handlers_measurements.py`, `handlers_exercises.py`, `handlers_export.py`
- **Экспорт в CSV/Excel** — пользователь может выгрузить всю историю тренировок
- **Кастомные упражнения** — пользователь добавляет свои, хранятся в БД
- Разделение `utils_constants.py` для всех констант

---

### 2. ChatGPT Telegram Bot (n3d1117) ⭐⭐⭐
🔗 https://github.com/n3d1117/chatgpt-telegram-bot
**Stars:** 6000+, Python, OpenAI/Anthropic, production-ready
**Что взять:**
- **Авто-суммаризация контекста** — после N сообщений контекст сжимается (у нас нет этого!)
- **Авто-сброс контекста** — после 180 мин неактивности новая сессия
- **Стриминг ответов** — ответы печатаются в реальном времени (`bot.send_chat_action(TYPING)`)
- **Трекинг токенов/бюджетов** — `/stats` показывает сколько потрачено
- **Whitelist пользователей** — только разрешённые USER_IDs
- **Voice → Text (Whisper)** — голосовые сообщения расшифровываются и обрабатываются

---

### 3. ProgressBot (Seinfeld method)
🔗 https://github.com/kiote/progressbot
**Stars:** Python, PostgreSQL
**Что делает:** 21-day habit challenge, ежедневный чекин, стрик
**Что взять:**
- **21-day challenge framework** — конкретный срок, дедлайн создаёт мотивацию
- **Seinfeld streaks** — визуализация "не ломай цепочку"
- Webhook вместо polling — не проверять постоянно, а получать push

---

### 4. Groundhog (mood tracker)
🔗 https://github.com/dennis-tra/groundhog
**Stars:** Python, Google Sheets sync
**Что делает:** 3 чекина в день (утро/день/вечер), оценка настроения 0-5, синк в Google Sheets
**Что взять:**
- **Google Sheets как дашборд** — пользователь видит все данные в таблице в реальном времени
- Dual-worksheet: рейтинги отдельно, заметки отдельно
- Простая шкала 0-5 через клавиатуру — быстрый ввод

---

### 5. GymBot (group features)
🔗 https://github.com/AsafSH6/GymBot
**Stars:** Python, MongoDB
**Что делает:** групповой бот — друзья создают группу, бот мотивирует всех
**Что взять:**
- **Групповой режим** — accountability partner feature
- Публичные достижения в группе
- Мотивация через социальное давление

---

## 🧩 Конкретные фичи для v2

| Приоритет | Фича | Источник | Сложность |
|-----------|------|----------|-----------|
| 🔴 Высокий | Авто-суммаризация контекста | n3d1117 | Средняя |
| 🔴 Высокий | Голосовые сообщения → текст (Whisper) | n3d1117 | Средняя |
| 🔴 Высокий | Стриминг ответов (печатается в реальном времени) | n3d1117 | Низкая |
| 🟡 Средний | Экспорт CSV/Excel с историей тренировок | NextSet | Низкая |
| 🟡 Средний | Кастомные упражнения пользователя | NextSet | Низкая |
| 🟡 Средний | Трекинг использования токенов + бюджет | n3d1117 | Средняя |
| 🟡 Средний | 21-day challenge с дедлайном | ProgressBot | Низкая |
| 🟢 Низкий | Google Sheets дашборд | Groundhog | Высокая |
| 🟢 Низкий | Групповой/accountability режим | GymBot | Высокая |

---

## 🚀 Что внедрить в первую очередь (в текущую версию)

### 1. Стриминг ответов — 30 мин работы
```python
# ai/client.py — добавить streaming
async def stream_response(chat_id, context, system, messages):
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    full_text = ""
    msg = await context.bot.send_message(chat_id, "...")
    with client.messages.stream(model=MODEL, system=system, messages=messages) as stream:
        for chunk in stream.text_stream:
            full_text += chunk
            if len(full_text) % 50 == 0:  # update every 50 chars
                await msg.edit_text(full_text)
    return full_text
```

### 2. Авто-суммаризация контекста — 1-2 часа
```python
# ai/context_builder.py — если >15 сообщений, сжать
MAX_MESSAGES = 15
SUMMARY_PROMPT = "Сожми эту переписку в 3-5 предложений, сохранив ключевые факты о тренировках и самочувствии."

async def maybe_compress_context(user_id: int):
    messages = get_recent_conversation(user_id, limit=20)
    if len(messages) >= MAX_MESSAGES:
        summary = await ask(SUMMARY_PROMPT, messages)
        clear_conversation(user_id)
        save_summary_as_context(user_id, summary)
```

### 3. Голосовые сообщения — 2-3 часа
```python
# bot/handlers.py — добавить voice handler
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = await update.message.voice.get_file()
    audio_path = f"/tmp/{update.effective_user.id}_voice.ogg"
    await voice.download_to_drive(audio_path)
    with open(audio_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(
            model="whisper-1", file=f, language="ru"
        )
    # дальше обрабатываем как текст
    await handle_message_text(update, context, text=transcript.text)
```

### 4. Экспорт CSV — 1 час
```python
# bot/commands.py — /export команда
async def cmd_export(update, context):
    workouts = get_workouts_range(user_id, days=90)
    csv_content = "date,type,duration,intensity\n"
    for w in workouts:
        csv_content += f"{w['date']},{w['type']},{w['duration_min']},{w['intensity']}\n"
    await update.message.reply_document(
        document=csv_content.encode(),
        filename=f"workouts_{user_id}.csv"
    )
```
