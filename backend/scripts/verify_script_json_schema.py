"""验证播客脚本 JSON 结构校验与对话提取逻辑。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from services.llm import validate_json_schema
from services.script_generator import SCRIPT_JSON_SCHEMA, ScriptGenerationService


def main() -> None:
    valid_payload = {
        "turns": [
            {
                "role": "Host",
                "content": "今天我们聊聊 RAG。",
                "emotion": "好奇地开场",
                "audio_tag": "语速加快",
            },
            {
                "role": "Guest",
                "content": "RAG 的核心是检索增强生成。",
                "emotion": "清晰地解释",
            },
        ]
    }
    errors = validate_json_schema(valid_payload, SCRIPT_JSON_SCHEMA)
    assert errors == []
    assert ScriptGenerationService._extract_turns(valid_payload) == valid_payload["turns"]

    invalid_payload = {
        "turns": [
            {
                "role": "Narrator",
                "content": "非法角色。",
                "emotion": "平静",
            }
        ]
    }
    errors = validate_json_schema(invalid_payload, SCRIPT_JSON_SCHEMA)
    assert errors
    assert "expected one of" in "; ".join(errors)

    legacy_payload = {"script": valid_payload["turns"]}
    assert ScriptGenerationService._extract_turns(legacy_payload) == valid_payload["turns"]

    sys.stdout.write("✅ 播客脚本 JSON 结构校验通过\n")


if __name__ == "__main__":
    main()
