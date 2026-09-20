"""Exercise the real hook without requiring a running AstrBot installation."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import unittest


def hook():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SmartSegmentationPlugin")
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_llm_response")
    method.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])
    namespace = {"asyncio": asyncio, "logger": Mock()}
    exec(compile(ast.fix_missing_locations(module), "main.py", "exec"), namespace)
    return namespace["on_llm_response"], namespace["logger"]


def check_failure(failure):
    run_hook, logger = hook()
    response = SimpleNamespace(completion_text="原始回复，分段故障也应该完整保留。")
    event = SimpleNamespace(unified_msg_origin="test-session")
    plugin = SimpleNamespace(
        _get_settings=Mock(return_value=SimpleNamespace(timeout_seconds=1)),
        _extract_response_plain_text=lambda r: r.completion_text,
        _should_segment_text=Mock(return_value=True),
        _pop_prepared_segments=Mock(return_value=["旧的", "分段"]),
        _resolve_provider_id=AsyncMock(return_value="test-provider"),
        _segment_text=AsyncMock(side_effect=failure),
        _store_prepared_segments=Mock(),
    )
    original = response.completion_text
    asyncio.run(run_hook(plugin, event, response))
    assert response.completion_text == original
    plugin._pop_prepared_segments.assert_called_once_with("test-session", original)
    plugin._store_prepared_segments.assert_not_called()
    logger.warning.assert_called_once()
    assert "原文继续发送" in logger.warning.call_args.args[0]
    logger.error.assert_not_called()


class FallbackTests(unittest.TestCase):
    def test_overload(self):
        check_failure(RuntimeError("Our servers are currently overloaded."))

    def test_timeout(self):
        check_failure(TimeoutError())
