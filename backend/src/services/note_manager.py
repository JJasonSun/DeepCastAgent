"""结构化笔记管理器。"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NoteManager:
    """轻量笔记管理器，提供与 NoteTool 相同的 create/read/update 接口。"""

    def __init__(self, workspace: str) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.index_file = self.workspace / "notes_index.json"
        self._load_index()

    # ------------------------------------------------------------------
    # 公共 API（与 NoteTool.run() 参数兼容）
    # ------------------------------------------------------------------

    def run(self, parameters: dict[str, Any]) -> str:
        """执行笔记操作，参数格式与 NoteTool.run() 一致。"""
        action = parameters.get("action")
        if action == "create":
            return self._create_note(parameters)
        if action == "read":
            return self._read_note(parameters)
        if action == "update":
            return self._update_note(parameters)
        if action == "delete":
            return self._delete_note(parameters)
        return f"不支持的操作: {action}"

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _load_index(self) -> None:
        if self.index_file.exists():
            with open(self.index_file, encoding="utf-8") as f:
                self.notes_index: dict[str, Any] = json.load(f)
        else:
            self.notes_index = {"notes": [], "metadata": {"total_notes": 0}}
            self._save_index()

    def _save_index(self) -> None:
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.notes_index, f, ensure_ascii=False, indent=2)

    def _generate_note_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        count = len(self.notes_index["notes"])
        return f"note_{timestamp}_{count}"

    def _get_note_path(self, note_id: str) -> Path:
        return self.workspace / f"{note_id}.md"

    def _create_note(self, params: dict[str, Any]) -> str:
        title = params.get("title", "")
        content = params.get("content", "")
        note_type = params.get("note_type", "general")
        tags = params.get("tags", [])

        if not title or not content:
            return "创建笔记需要提供 title 和 content"

        note_id = self._generate_note_id()
        now = datetime.now().isoformat()

        note = {
            "id": note_id,
            "title": title,
            "content": content,
            "type": note_type,
            "tags": tags if isinstance(tags, list) else [],
            "created_at": now,
            "updated_at": now,
        }

        note_path = self._get_note_path(note_id)
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(self._note_to_markdown(note))

        self.notes_index["notes"].append({
            "id": note_id,
            "title": title,
            "type": note_type,
            "tags": note["tags"],
            "created_at": now,
        })
        self.notes_index["metadata"]["total_notes"] = len(self.notes_index["notes"])
        self._save_index()

        return f"笔记创建成功\nID: {note_id}\n标题: {title}\n类型: {note_type}"

    def _read_note(self, params: dict[str, Any]) -> str:
        note_id = params.get("note_id", "")
        if not note_id:
            return "读取笔记需要提供 note_id"

        note_path = self._get_note_path(note_id)
        if not note_path.exists():
            return f"笔记不存在: {note_id}"

        with open(note_path, encoding="utf-8") as f:
            markdown_text = f.read()

        note = self._markdown_to_note(markdown_text)
        return self._format_note(note)

    def _update_note(self, params: dict[str, Any]) -> str:
        note_id = params.get("note_id", "")
        if not note_id:
            return "更新笔记需要提供 note_id"

        note_path = self._get_note_path(note_id)
        if not note_path.exists():
            return f"笔记不存在: {note_id}"

        with open(note_path, encoding="utf-8") as f:
            note = self._markdown_to_note(f.read())

        if "title" in params:
            note["title"] = params["title"]
        if "content" in params:
            note["content"] = params["content"]
        if "note_type" in params:
            note["type"] = params["note_type"]
        if "tags" in params:
            note["tags"] = params["tags"] if isinstance(params["tags"], list) else []
        note["updated_at"] = datetime.now().isoformat()

        with open(note_path, "w", encoding="utf-8") as f:
            f.write(self._note_to_markdown(note))

        for idx_note in self.notes_index["notes"]:
            if idx_note["id"] == note_id:
                idx_note["title"] = note["title"]
                idx_note["type"] = note["type"]
                idx_note["tags"] = note["tags"]
                break
        self._save_index()

        return f"笔记更新成功: {note_id}"

    def _delete_note(self, params: dict[str, Any]) -> str:
        note_id = params.get("note_id", "")
        if not note_id:
            return "删除笔记需要提供 note_id"

        note_path = self._get_note_path(note_id)
        if not note_path.exists():
            return f"笔记不存在: {note_id}"

        note_path.unlink()
        self.notes_index["notes"] = [
            n for n in self.notes_index["notes"] if n["id"] != note_id
        ]
        self.notes_index["metadata"]["total_notes"] = len(self.notes_index["notes"])
        self._save_index()

        return f"笔记已删除: {note_id}"

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    @staticmethod
    def _note_to_markdown(note: dict[str, Any]) -> str:
        frontmatter = (
            "---\n"
            f"id: {note['id']}\n"
            f"title: {note['title']}\n"
            f"type: {note['type']}\n"
        )
        if note.get("tags"):
            frontmatter += f"tags: {json.dumps(note['tags'])}\n"
        frontmatter += (
            f"created_at: {note['created_at']}\n"
            f"updated_at: {note['updated_at']}\n"
            "---\n\n"
        )
        return frontmatter + f"# {note['title']}\n\n{note['content']}"

    @staticmethod
    def _markdown_to_note(markdown_text: str) -> dict[str, Any]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", markdown_text, re.DOTALL)
        if not match:
            raise ValueError("无效的笔记格式：缺少 YAML 前置元数据")

        note: dict[str, Any] = {}
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key, value = key.strip(), value.strip()
                if key == "tags":
                    try:
                        note[key] = json.loads(value)
                    except json.JSONDecodeError:
                        note[key] = []
                else:
                    note[key] = value

        content_start = match.end()
        markdown_content = markdown_text[content_start:].strip()
        lines = markdown_content.split("\n")
        if lines and lines[0].startswith("# "):
            markdown_content = "\n".join(lines[1:]).strip()

        note["content"] = markdown_content
        return note

    @staticmethod
    def _format_note(note: dict[str, Any]) -> str:
        result = (
            f"笔记详情\n\n"
            f"ID: {note['id']}\n"
            f"标题: {note['title']}\n"
            f"类型: {note['type']}\n"
        )
        if note.get("tags"):
            result += f"标签: {', '.join(note['tags'])}\n"
        result += (
            f"创建时间: {note['created_at']}\n"
            f"更新时间: {note['updated_at']}\n"
            f"\n内容:\n{note['content']}\n"
        )
        return result
