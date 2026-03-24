"""
tests/test_resource_audit.py — Аудит расхода ресурсов (токены, модели).

Проверяет результаты оптимизаций из Resource Audit:
  RA-1  … RA-4   _TOOLS_WEEKLY_REPORT — состав и размер
  RA-5  … RA-8   generate_scheduled_agent_message принимает tools
  RA-9  … RA-11  Scheduled jobs используют MODEL_SCHEDULED (Haiku)
  RA-12          Мёртвый код удалён из context_builder
  RA-13          Удалённые импорты не поломали оставшиеся функции
"""
import inspect
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# ═══════════════════════════════════════════════════════════════════════════════
# RA-1 … RA-4 — _TOOLS_WEEKLY_REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolsWeeklyReport:
    def test_exists_and_has_5_tools(self):
        """RA-1: _TOOLS_WEEKLY_REPORT определён и содержит ровно 5 инструментов."""
        from ai.tools import _TOOLS_WEEKLY_REPORT
        assert len(_TOOLS_WEEKLY_REPORT) == 5

    def test_contains_required_read_tools(self):
        """RA-2: содержит все 4 read-инструмента + save_episode."""
        from ai.tools import _TOOLS_WEEKLY_REPORT
        names = {t["name"] for t in _TOOLS_WEEKLY_REPORT}
        required = {
            "get_weekly_stats",
            "get_nutrition_history",
            "get_personal_records",
            "get_user_profile",
            "save_episode",
        }
        assert required == names

    def test_no_destructive_write_tools(self):
        """RA-3: write-инструменты (запись данных) отсутствуют — weekly report только читает."""
        from ai.tools import _TOOLS_WEEKLY_REPORT
        names = {t["name"] for t in _TOOLS_WEEKLY_REPORT}
        forbidden = {
            "save_workout", "save_nutrition", "save_metrics",
            "save_exercise_result", "set_personal_record",
            "update_athlete_card", "award_xp", "save_training_plan",
        }
        overlap = names & forbidden
        assert not overlap, f"Нашлись write-tools в weekly report: {overlap}"

    def test_token_count_significantly_less_than_all_tools(self):
        """RA-4: ~700 токенов vs ~3500 у ALL_TOOLS — экономия минимум 60%."""
        from ai.tools import _TOOLS_WEEKLY_REPORT, ALL_TOOLS
        all_tok  = len(json.dumps(ALL_TOOLS,              ensure_ascii=False)) // 4
        week_tok = len(json.dumps(_TOOLS_WEEKLY_REPORT,   ensure_ascii=False)) // 4
        savings_pct = (all_tok - week_tok) / all_tok
        assert savings_pct >= 0.60, (
            f"Экономия {savings_pct:.0%} — ожидалась ≥60%. "
            f"all={all_tok} tok, weekly_report={week_tok} tok"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RA-5 … RA-8 — generate_scheduled_agent_message принимает tools
# ═══════════════════════════════════════════════════════════════════════════════

class TestScheduledAgentMessageTools:
    def test_function_has_tools_parameter(self):
        """RA-5: generate_scheduled_agent_message имеет параметр tools."""
        from ai.client import generate_scheduled_agent_message
        sig = inspect.signature(generate_scheduled_agent_message)
        assert "tools" in sig.parameters, "Параметр tools не найден в сигнатуре"

    def test_tools_parameter_is_optional_with_none_default(self):
        """RA-6: tools по умолчанию None (backward-compatible)."""
        from ai.client import generate_scheduled_agent_message
        sig = inspect.signature(generate_scheduled_agent_message)
        default = sig.parameters["tools"].default
        assert default is None, f"Ожидался default=None, получили {default!r}"

    @pytest.mark.asyncio
    async def test_explicit_tools_passed_to_agent_loop(self):
        """RA-7: явно переданные tools пробрасываются в _run_agent_iterations."""
        from ai.tools import _TOOLS_WEEKLY_REPORT
        context = {"system": "test system", "prompt": "тест"}
        captured = {}

        async def mock_iterations(*args, tools, **kwargs):
            captured["tools"] = tools
            return ("Отчёт готов.", {"input_tokens": 10, "output_tokens": 5,
                                     "cache_read": 0, "cache_write": 0})

        mock_bot = MagicMock()
        with patch("ai.client._run_agent_iterations", side_effect=mock_iterations), \
             patch("ai.client.get_async_client"):
            from ai.client import generate_scheduled_agent_message
            await generate_scheduled_agent_message(
                bot=mock_bot, chat_id=123, context=context,
                tg_id=999, tools=_TOOLS_WEEKLY_REPORT,
            )

        assert captured.get("tools") is _TOOLS_WEEKLY_REPORT, (
            "tools не дошли до _run_agent_iterations"
        )

    @pytest.mark.asyncio
    async def test_default_uses_all_tools_when_not_specified(self):
        """RA-8: если tools не передан — используются ALL_TOOLS."""
        from ai.tools import ALL_TOOLS
        context = {"system": "test", "prompt": "тест"}
        captured = {}

        async def mock_iterations(*args, tools, **kwargs):
            captured["tools"] = tools
            return ("OK", {"input_tokens": 5, "output_tokens": 3,
                           "cache_read": 0, "cache_write": 0})

        mock_bot = MagicMock()
        with patch("ai.client._run_agent_iterations", side_effect=mock_iterations), \
             patch("ai.client.get_async_client"):
            from ai.client import generate_scheduled_agent_message
            await generate_scheduled_agent_message(
                bot=mock_bot, chat_id=123, context=context, tg_id=999,
                # tools НЕ передаём
            )

        assert captured.get("tools") is ALL_TOOLS, (
            "Без явных tools должны использоваться ALL_TOOLS"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RA-9 … RA-11 — scheduler/logic.py использует MODEL_SCHEDULED
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedulerUsesHaiku:
    """
    Проверяем через inspect.getsource — что в теле функций импортируется
    MODEL_SCHEDULED (а не MODEL) для прямых calls к API.
    """

    def _get_source(self, func_name: str) -> str:
        import scheduler.logic as logic
        fn = getattr(logic, func_name)
        return inspect.getsource(fn)

    def test_update_l4_uses_model_scheduled(self):
        """RA-9: update_l4_for_user использует MODEL_SCHEDULED, не MODEL напрямую."""
        src = self._get_source("update_l4_for_user")
        assert "MODEL_SCHEDULED" in src, (
            "update_l4_for_user должен импортировать MODEL_SCHEDULED"
        )
        # Убеждаемся что нет 'from config import MODEL' без алиаса
        assert "import MODEL_SCHEDULED" in src or "MODEL_SCHEDULED as MODEL" in src

    def test_generate_daily_summary_uses_model_scheduled(self):
        """RA-10: generate_daily_summary_for_user использует MODEL_SCHEDULED."""
        src = self._get_source("generate_daily_summary_for_user")
        assert "MODEL_SCHEDULED" in src, (
            "generate_daily_summary_for_user должен импортировать MODEL_SCHEDULED"
        )

    def test_generate_monthly_summary_uses_model_scheduled(self):
        """RA-11: generate_monthly_summary_for_user использует MODEL_SCHEDULED."""
        src = self._get_source("generate_monthly_summary_for_user")
        assert "MODEL_SCHEDULED" in src, (
            "generate_monthly_summary_for_user должен импортировать MODEL_SCHEDULED"
        )

    def test_model_scheduled_is_haiku(self):
        """RA-11b: MODEL_SCHEDULED это Haiku (в 4× дешевле Sonnet)."""
        from config import MODEL_SCHEDULED, MODEL
        assert "haiku" in MODEL_SCHEDULED.lower(), (
            f"MODEL_SCHEDULED должна быть Haiku, получили: {MODEL_SCHEDULED}"
        )
        assert "haiku" not in MODEL.lower(), (
            f"MODEL (основная) не должна быть Haiku, получили: {MODEL}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RA-12 — Мёртвый код удалён из context_builder
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeadCodeRemoved:
    def test_build_morning_context_removed(self):
        """RA-12a: build_morning_context удалён из context_builder."""
        import ai.context_builder as cb
        assert not hasattr(cb, "build_morning_context"), (
            "build_morning_context не был удалён — мёртвый код"
        )

    def test_build_afternoon_context_removed(self):
        """RA-12b: build_afternoon_context удалён."""
        import ai.context_builder as cb
        assert not hasattr(cb, "build_afternoon_context"), (
            "build_afternoon_context не был удалён — мёртвый код"
        )

    def test_build_evening_context_removed(self):
        """RA-12c: build_evening_context удалён."""
        import ai.context_builder as cb
        assert not hasattr(cb, "build_evening_context"), (
            "build_evening_context не был удалён — мёртвый код"
        )

    def test_unused_imports_removed(self):
        """RA-12d: удалённые функции не тянули за собой висячие импорты."""
        import ai.context_builder as cb
        # get_workouts_range и get_today_checkins использовались только мёртвыми функциями
        src = inspect.getsource(cb)
        assert "get_workouts_range" not in src, (
            "get_workouts_range остался в импортах — unused import"
        )
        assert "get_today_checkins" not in src, (
            "get_today_checkins остался в импортах — unused import"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RA-13 — Оставшиеся функции context_builder работают после чистки
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextBuilderStillWorks:
    def test_build_weekly_report_context_importable(self):
        """RA-13a: build_weekly_report_context по-прежнему существует."""
        from ai.context_builder import build_weekly_report_context
        assert callable(build_weekly_report_context)

    def test_build_layered_context_importable(self):
        """RA-13b: build_layered_context не сломан удалением."""
        from ai.context_builder import build_layered_context
        assert callable(build_layered_context)

    def test_get_system_prompt_still_works(self):
        """RA-13c: get_system_prompt возвращает непустую строку."""
        from ai.context_builder import get_system_prompt
        for mode in ("MAX", "LIGHT"):
            prompt = get_system_prompt(mode)
            assert isinstance(prompt, str) and len(prompt) > 100, (
                f"get_system_prompt({mode!r}) вернул пустую строку"
            )

    def test_get_metrics_range_still_imported(self):
        """RA-13d: get_metrics_range нужен в build_layered_context — должен оставаться."""
        import ai.context_builder as cb
        src = inspect.getsource(cb)
        assert "get_metrics_range" in src, (
            "get_metrics_range пропал — нужен для build_layered_context"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RA-14 — send_weekly_report передаёт _TOOLS_WEEKLY_REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def test_send_weekly_report_uses_weekly_report_tools():
    """RA-14: send_weekly_report импортирует и передаёт _TOOLS_WEEKLY_REPORT."""
    import scheduler.logic as logic
    src = inspect.getsource(logic.send_weekly_report)
    assert "_TOOLS_WEEKLY_REPORT" in src, (
        "send_weekly_report должна передавать _TOOLS_WEEKLY_REPORT"
    )
    assert "tools=_TOOLS_WEEKLY_REPORT" in src, (
        "send_weekly_report должна явно передавать tools= в generate_scheduled_agent_message"
    )
