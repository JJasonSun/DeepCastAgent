"""验证报告正文前的模型交付说明会被清理。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from services.reporter import ReportingService


def main() -> None:
    sample = """# 研究报告：上海苏州河citywalk路线

好的，作为专业的分析报告撰写专家，我已将您提供的5项任务研究成果进行整合与深度分析，现基于“研究主题：上海苏州河citywalk路线”提交以下结构化深度报告。

---

## 深度研究报告：上海苏州河Citywalk路线全览

正文内容。
"""
    cleaned = ReportingService._strip_report_delivery_preamble(sample)
    assert "好的，作为专业的分析报告撰写专家" not in cleaned
    assert "提交以下结构化深度报告" not in cleaned
    assert "\n---\n" not in cleaned
    assert cleaned.startswith("# 研究报告：上海苏州河citywalk路线")
    assert "## 深度研究报告：上海苏州河Citywalk路线全览" in cleaned
    assert cleaned.endswith("正文内容。")

    direct_preamble = """以下是根据研究资料整理的完整报告：

## TL;DR / 核心结论

核心结论正文。
"""
    direct_cleaned = ReportingService._strip_report_delivery_preamble(direct_preamble)
    assert direct_cleaned.startswith("## TL;DR / 核心结论")
    assert "以下是根据研究资料整理的完整报告" not in direct_cleaned

    normal_report = """# 研究报告：测试主题

## TL;DR / 核心结论

这是正常正文，不应被清理。
"""
    assert ReportingService._strip_report_delivery_preamble(normal_report) == normal_report.strip()

    sys.stdout.write("✅ 报告多余开场清理验证通过\n")


if __name__ == "__main__":
    main()
