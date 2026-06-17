"""验证 LLM 空 content 和坏 JSON 会触发应用层重试。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from services.llm import call_llm, call_llm_json


class FakeCompletions:
    """模拟 OpenAI chat.completions 接口。"""

    def __init__(self, contents: list[str]) -> None:
        self._contents = contents
        self.calls = 0

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        content = self._contents.pop(0) if self._contents else ""
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ]
        )


class FakeClient:
    """只提供本测试需要的 chat.completions.create。"""

    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(contents))


def main() -> None:
    text_client = FakeClient(["", "报告正文"])
    text = call_llm(
        text_client,
        system_prompt="system",
        user_prompt="user",
        model="fake-model",
        max_retries=1,
        retry_base_delay=0.1,
    )
    assert text == "报告正文"
    assert text_client.chat.completions.calls == 2

    empty_client = FakeClient(["", ""])
    empty_text = call_llm(
        empty_client,
        system_prompt="system",
        user_prompt="user",
        model="fake-model",
        max_retries=1,
        retry_base_delay=0.1,
    )
    assert empty_text == ""
    assert empty_client.chat.completions.calls == 2

    json_client = FakeClient(["", '{"ok": true}'])
    parsed = call_llm_json(
        json_client,
        system_prompt="system",
        user_prompt="user",
        model="fake-model",
        json_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        max_retries=1,
        retry_base_delay=0.1,
    )
    assert parsed == {"ok": True}
    assert json_client.chat.completions.calls == 2

    invalid_json_client = FakeClient(['{"turns": [', '{"ok": true}'])
    parsed_after_invalid_json = call_llm_json(
        invalid_json_client,
        system_prompt="system",
        user_prompt="user",
        model="fake-model",
        json_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        max_retries=1,
        retry_base_delay=0.1,
    )
    assert parsed_after_invalid_json == {"ok": True}
    assert invalid_json_client.chat.completions.calls == 2

    sys.stdout.write("✅ LLM 空 content 与坏 JSON 重试逻辑通过\n")


if __name__ == "__main__":
    main()
