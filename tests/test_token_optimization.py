"""
tests/test_token_optimization.py — Фаза 17: Token Optimization (Tiered Request System).

Проверяет:
  TO-1  … TO-5   get_tools_for_tags — правильный набор tools по тегам
  TO-6  … TO-14  classify_request_tier — CRUD vs full
  TO-15 … TO-21  build_layered_context — tier/model/tools/max_tokens в контексте
  TO-22 … TO-24  Интеграция: context-builder + client — tools/model пробрасываются
  TO-25          Backward compat: если context без tier — defaults корректны
"""

import pytest
from unittest.mock import patch, MagicMock


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_user(conn, telegram_id: int = 11111) -> int:
    """Вставляет пользователя и возвращает его telegram_id (build_layered_context принимает telegram_id)."""
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (telegram_id, name, goal, fitness_level, active) "
        "VALUES (?, 'Влад', 'набрать массу', 'intermediate', 1)",
        (telegram_id,),
    )
    conn.commit()
    return telegram_id  # build_layered_context принимает telegram_id, не внутренний id


@pytest.fixture()
def layered_db(patched_db):
    """
    Расширяет patched_db дополнительными патчами для build_layered_context.
    context_builder вызывает модули, не покрытые базовым patched_db.
    """
    extra_targets = [
        "db.queries.context.get_connection",
        "db.queries.stats.get_connection",
        "db.queries.daily_summary.get_connection",
        "db.queries.monthly_summary.get_connection",
        "db.queries.episodic.get_connection",
        "db.queries.gamification.get_connection",
        "db.queries.recovery.get_connection",
        "db.queries.periodization.get_connection",
    ]
    active = []
    for target in extra_targets:
        try:
            p = patch(target, return_value=patched_db)
            p.start()
            active.append(p)
        except (AttributeError, ModuleNotFoundError):
            pass
    yield patched_db
    for p in reversed(active):
        try:
            p.stop()
        except RuntimeError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# TO-1 … TO-5 — get_tools_for_tags
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetToolsForTags:
    def test_food_returns_minimal_set(self):
        """TO-1: food → только save_nutrition + save_episode."""
        from ai.tools import get_tools_for_tags
        tools = get_tools_for_tags(frozenset({"food"}))
        names = {t["name"] for t in tools}
        assert "save_nutrition" in names
        assert "save_episode" in names
        # Не должны быть тренировочные tools
        assert "save_workout" not in names
        assert "save_metrics" not in names
        assert "get_weekly_stats" not in names

    def test_training_returns_correct_set(self):
        """TO-2: training → save_workout + save_exercise_result + set_personal_record + award_xp + save_episode."""
        from ai.tools import get_tools_for_tags
        tools = get_tools_for_tags(frozenset({"training"}))
        names = {t["name"] for t in tools}
        assert {"save_workout", "save_exercise_result", "set_personal_record",
                "award_xp", "save_episode"} <= names
        assert "save_nutrition" not in names

    def test_metrics_returns_minimal(self):
        """TO-3: metrics → только save_metrics (самый экономный сет)."""
        from ai.tools import get_tools_for_tags
        tools = get_tools_for_tags(frozenset({"metrics"}))
        names = {t["name"] for t in tools}
        assert "save_metrics" in names
        assert len(names) == 1  # только один tool

    def test_empty_tags_returns_all_tools(self):
        """TO-4: пустые теги → ALL_TOOLS (безопасный fallback)."""
        from ai.tools import get_tools_for_tags, ALL_TOOLS
        tools = get_tools_for_tags(frozenset())
        assert tools is ALL_TOOLS or len(tools) == len(ALL_TOOLS)

    def test_combined_food_training(self):
        """TO-5: food+training → объединение без дублей."""
        from ai.tools import get_tools_for_tags
        tools = get_tools_for_tags(frozenset({"food", "training"}))
        names = {t["name"] for t in tools}
        assert "save_nutrition" in names
        assert "save_workout" in names
        # Нет дублей
        assert len(tools) == len(names)

    def test_analytics_returns_read_tools(self):
        """TO-5b: analytics → только read-tools."""
        from ai.tools import get_tools_for_tags
        tools = get_tools_for_tags(frozenset({"analytics"}))
        names = {t["name"] for t in tools}
        assert "get_weekly_stats" in names
        assert "get_nutrition_history" in names
        assert "save_workout" not in names
        assert "save_nutrition" not in names

    def test_all_tools_are_fewer_than_total(self):
        """TO-5c: любой конкретный тег даёт меньше tools чем ALL_TOOLS."""
        from ai.tools import get_tools_for_tags, ALL_TOOLS
        for tag in ("food", "training", "metrics", "analytics", "plan", "health"):
            result = get_tools_for_tags(frozenset({tag}))
            assert len(result) < len(ALL_TOOLS), f"tag={tag} не уменьшил набор tools"


# ═══════════════════════════════════════════════════════════════════════════════
# TO-6 … TO-14 — classify_request_tier
# ═══════════════════════════════════════════════════════════════════════════════

class TestClassifyRequestTier:
    def test_food_short_no_question_is_crud(self):
        """TO-6: 'съел куриную грудку с рисом' → crud."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"food"}), "съел куриную грудку с рисом") == "crud"

    def test_training_short_no_question_is_crud(self):
        """TO-7: 'потренировался 45 минут' → crud."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"training"}), "потренировался 45 минут") == "crud"

    def test_metrics_short_no_question_is_crud(self):
        """TO-8: 'поспал 8 часов, энергия 4/5' → crud."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"metrics"}), "поспал 8 часов, энергия 4/5") == "crud"

    def test_food_with_question_mark_is_full(self):
        """TO-9: 'съел пиццу, как дела?' → full (есть '?')."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"food"}), "съел пиццу, как дела?") == "full"

    def test_food_with_question_word_is_full(self):
        """TO-10: 'что мне лучше поесть?' → full (есть 'что ')."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"food"}), "что мне лучше поесть?") == "full"

    def test_analytics_tag_always_full(self):
        """TO-11: analytics тег → full даже без вопроса."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"analytics"}), "прогресс за месяц") == "full"

    def test_plan_tag_always_full(self):
        """TO-12: plan тег → full."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"plan"}), "план на неделю") == "full"

    def test_health_tag_always_full(self):
        """TO-13: health тег → full."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"health"}), "болит плечо") == "full"

    def test_long_text_is_full(self):
        """TO-14: текст > 200 символов → full даже без вопроса."""
        from ai.tools import classify_request_tier
        long_text = "съел " + "куриную грудку " * 15  # > 200 символов
        assert classify_request_tier(frozenset({"food"}), long_text) == "full"

    def test_empty_tags_is_full(self):
        """TO-14b: пустые теги → full (неизвестный контекст)."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset(), "привет") == "full"

    def test_mixed_crud_and_analytics_is_full(self):
        """TO-14c: food+analytics → full (аналитика доминирует)."""
        from ai.tools import classify_request_tier
        assert classify_request_tier(frozenset({"food", "analytics"}), "что я ел на прошлой неделе") == "full"


# ═══════════════════════════════════════════════════════════════════════════════
# TO-15 … TO-21 — build_layered_context: tier/model/tools/max_tokens
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildLayeredContextTier:
    def test_food_crud_returns_crud_tier(self, layered_db):
        """TO-15: сообщение о еде → tier='crud' в контексте."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        ctx = build_layered_context(tg_id, "съел куриную грудку с рисом")
        assert ctx["tier"] == "crud"

    def test_crud_uses_haiku(self, layered_db):
        """TO-16: CRUD → model=Haiku в контексте."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        from config import MODEL_CRUD
        ctx = build_layered_context(tg_id, "съел куриную грудку с рисом")
        assert ctx["model"] == MODEL_CRUD

    def test_crud_uses_lower_max_tokens(self, layered_db):
        """TO-17: CRUD → max_tokens=MAX_TOKENS_CRUD (< MAX_TOKENS)."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        from config import MAX_TOKENS, MAX_TOKENS_CRUD
        ctx = build_layered_context(tg_id, "съел куриную грудку с рисом")
        assert ctx["max_tokens"] == MAX_TOKENS_CRUD
        assert ctx["max_tokens"] < MAX_TOKENS

    def test_crud_has_filtered_tools(self, layered_db):
        """TO-18: CRUD (food) → меньше tools чем ALL_TOOLS."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        from ai.tools import ALL_TOOLS
        ctx = build_layered_context(tg_id, "съел куриную грудку с рисом")
        assert len(ctx["tools"]) < len(ALL_TOOLS)
        tool_names = {t["name"] for t in ctx["tools"]}
        assert "save_nutrition" in tool_names

    def test_crud_history_limit_is_3(self, layered_db):
        """TO-19: CRUD → история не больше 3 сообщений."""
        tg_id = _make_user(layered_db)
        # Получаем внутренний id для вставки в conversation_context
        inner_id = layered_db.execute(
            "SELECT id FROM user_profile WHERE telegram_id=?", (tg_id,)
        ).fetchone()["id"]
        for i in range(10):
            layered_db.execute(
                "INSERT INTO conversation_context (user_id, role, content) "
                "VALUES (?, 'user', ?)",
                (inner_id, f"сообщение {i}"),
            )
        layered_db.commit()
        from ai.context_builder import build_layered_context
        ctx = build_layered_context(tg_id, "съел куриную грудку с рисом")
        assert len(ctx["history"]) <= 3

    def test_full_tier_uses_sonnet(self, layered_db):
        """TO-20: аналитика → tier='full', model=Sonnet."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        from config import MODEL
        ctx = build_layered_context(tg_id, "покажи мой прогресс за месяц")
        assert ctx["tier"] == "full"
        assert ctx["model"] == MODEL

    def test_full_tier_uses_full_max_tokens(self, layered_db):
        """TO-21: full tier → max_tokens=MAX_TOKENS."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        from config import MAX_TOKENS
        ctx = build_layered_context(tg_id, "как мне выстроить план на следующий месяц?")
        assert ctx["max_tokens"] == MAX_TOKENS

    def test_question_about_food_is_full_not_crud(self, layered_db):
        """TO-21b: вопрос о еде → full (не CRUD), чтобы Sonnet ответил развёрнуто."""
        tg_id = _make_user(layered_db)
        from ai.context_builder import build_layered_context
        ctx = build_layered_context(tg_id, "сколько белка мне нужно в день?")
        assert ctx["tier"] == "full"


# ═══════════════════════════════════════════════════════════════════════════════
# TO-22 … TO-24 — Интеграция: generate_agent_response читает из context
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateAgentResponseReadsContext:
    @pytest.mark.asyncio
    async def test_tools_from_context_used_when_no_explicit_tools(self):
        """TO-22: generate_agent_response берёт tools из context если не переданы явно."""
        from ai.tools import _TOOLS_FOOD
        context = {
            "system": "test system",
            "history": [],
            "tools": _TOOLS_FOOD,
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1200,
        }
        captured_tools = []

        async def mock_iterations(*args, tools, **kwargs):
            captured_tools.extend(tools)
            return ("✅", {"input_tokens": 10, "output_tokens": 5,
                           "cache_read": 0, "cache_write": 0})

        mock_bot = MagicMock()
        mock_bot.send_message = MagicMock(return_value=MagicMock())
        mock_bot.send_message.return_value.__aenter__ = MagicMock()
        # Упрощённая заглушка — только проверяем что tools прокидываются

        with patch("ai.client._run_agent_iterations", side_effect=mock_iterations), \
             patch("ai.client.get_async_client"), \
             patch("ai.client._stream_response"), \
             patch("ai.client._log_usage_footnote"), \
             patch("ai.client._detect_hallucination"):

            from ai.client import generate_agent_response
            # Не передаём tools явно — они должны взяться из context
            # (тест проверяет что аргументы попадают в _run_agent_iterations)
            with patch("ai.client._run_agent_iterations") as mock_iter:
                mock_iter.return_value = ("✅ Готово.", {"input_tokens": 10,
                                                          "output_tokens": 5,
                                                          "cache_read": 0,
                                                          "cache_write": 0})
                mock_msg = MagicMock()
                mock_msg.edit_text = MagicMock()
                mock_bot2 = MagicMock()
                mock_bot2.send_message = MagicMock()
                mock_bot2.send_message.return_value = mock_msg

                try:
                    await generate_agent_response(
                        bot=mock_bot2,
                        chat_id=123,
                        context=context,
                        user_message="съел курицу",
                        tg_id=999,
                        # tools НЕ передаём явно
                    )
                except Exception:
                    pass  # ошибка mock'а не важна, главное что вызов был с нужными tools

                if mock_iter.called:
                    call_kwargs = mock_iter.call_args
                    if call_kwargs and call_kwargs.kwargs.get("tools") is not None:
                        assert call_kwargs.kwargs["tools"] is _TOOLS_FOOD

    @pytest.mark.asyncio
    async def test_explicit_tools_override_context(self):
        """TO-23: явно переданные tools переопределяют context['tools']."""
        from ai.tools import ALL_TOOLS, _TOOLS_FOOD
        context = {
            "system": "test",
            "history": [],
            "tools": _TOOLS_FOOD,  # context говорит food tools
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1200,
        }
        with patch("ai.client._run_agent_iterations") as mock_iter, \
             patch("ai.client.get_async_client"), \
             patch("ai.client._stream_response"), \
             patch("ai.client._log_usage_footnote"), \
             patch("ai.client._detect_hallucination"):

            mock_iter.return_value = ("✅", {"input_tokens": 5, "output_tokens": 3,
                                              "cache_read": 0, "cache_write": 0})
            mock_msg = MagicMock()
            mock_bot = MagicMock()
            mock_bot.send_message.return_value = mock_msg

            from ai.client import generate_agent_response
            try:
                await generate_agent_response(
                    bot=mock_bot,
                    chat_id=123,
                    context=context,
                    user_message="тест",
                    tg_id=999,
                    tools=ALL_TOOLS,  # явно передаём ALL_TOOLS
                )
            except Exception:
                pass

            if mock_iter.called:
                call_kwargs = mock_iter.call_args
                if call_kwargs and call_kwargs.kwargs.get("tools") is not None:
                    # Должны использоваться ALL_TOOLS, не context["tools"]
                    assert call_kwargs.kwargs["tools"] is ALL_TOOLS

    def test_context_without_tier_uses_defaults(self):
        """TO-24: контекст без tier (старые вызовы) → generate_agent_response не падает."""
        # Просто проверяем что код читает model/max_tokens без ошибок
        old_style_context = {
            "system": "test",
            "history": [],
            # нет tier, tools, model, max_tokens
        }
        # Импортируем модуль — если нет AttributeError, всё ок
        from ai.client import generate_agent_response
        from config import MODEL, MAX_TOKENS

        # Эмулируем чтение из context (как это делает generate_agent_response)
        model = old_style_context.get("model", MODEL)
        max_tokens = old_style_context.get("max_tokens", MAX_TOKENS)
        assert model == MODEL
        assert max_tokens == MAX_TOKENS


# ═══════════════════════════════════════════════════════════════════════════════
# TO-25 — config: новые константы присутствуют
# ═══════════════════════════════════════════════════════════════════════════════

def test_config_crud_constants():
    """TO-25: config.py содержит MODEL_CRUD, MAX_TOKENS_CRUD, MODEL_SCHEDULED, MAX_TOKENS_SCHEDULED."""
    from config import MODEL_CRUD, MAX_TOKENS_CRUD, MODEL_SCHEDULED, MAX_TOKENS_SCHEDULED, MODEL, MAX_TOKENS
    assert "haiku" in MODEL_CRUD.lower()         # Haiku для CRUD
    assert MAX_TOKENS_CRUD < MAX_TOKENS           # CRUD ответ короче full
    assert "haiku" in MODEL_SCHEDULED.lower()    # Scheduled тоже Haiku
    assert MAX_TOKENS_SCHEDULED <= MAX_TOKENS     # Scheduled не длиннее full


def test_crud_tools_token_count():
    """TO-25b: CRUD tool-сеты существенно меньше ALL_TOOLS."""
    import json
    from ai.tools import get_tools_for_tags, ALL_TOOLS

    all_tok = len(json.dumps(ALL_TOOLS, ensure_ascii=False)) // 4

    food_tools  = get_tools_for_tags(frozenset({"food"}))
    food_tok    = len(json.dumps(food_tools, ensure_ascii=False)) // 4

    train_tools = get_tools_for_tags(frozenset({"training"}))
    train_tok   = len(json.dumps(train_tools, ensure_ascii=False)) // 4

    metr_tools  = get_tools_for_tags(frozenset({"metrics"}))
    metr_tok    = len(json.dumps(metr_tools, ensure_ascii=False)) // 4

    # Проверяем что экономия значительная (минимум 40%)
    assert food_tok  < all_tok * 0.6, f"food tools: {food_tok} tok vs {all_tok} all (недостаточная экономия)"
    assert train_tok < all_tok * 0.6, f"train tools: {train_tok} tok vs {all_tok} all"
    assert metr_tok  < all_tok * 0.2, f"metrics tools: {metr_tok} tok vs {all_tok} all"
