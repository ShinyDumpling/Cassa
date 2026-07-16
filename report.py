"""将结构化 JSON 保存为数据文件，并渲染为 Markdown 报告。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined


PROJECT_ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
RESULT_DIR = PROJECT_ROOT / "result"

TEMPLATE_MAP = {
    "thesis": "thesis.md.j2",
    "thises": "thesis.md.j2",
}


def build_template_environment() -> Environment:
    """创建 Jinja2 模板环境，返回用于渲染 Markdown 的环境对象。"""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def sanitize_filename_part(value: Any) -> str:
    """清理文件名片段中的非法字符，返回适合 Windows 文件名的文本。"""
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return text or "unknown"


def build_output_paths(
    data: dict[str, Any],
    report_type: str,
    timestamp: datetime,
) -> tuple[Path, Path]:
    """生成一组不覆盖旧文件的 JSON 和 Markdown 输出路径。"""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    code = sanitize_filename_part(data.get("code"))
    name = sanitize_filename_part(data.get("name"))
    base_name = (
        f"{report_type}-{code}-{name}-"
        f"{timestamp.strftime('%Y%m%d-%H%M%S')}"
    )

    candidate_suffixes = ["", f"-{timestamp.strftime('%f')}"]
    candidate_suffixes.extend(f"-{index}" for index in range(2, 1000))

    for suffix in candidate_suffixes:
        data_path = RESULT_DIR / f"{base_name}{suffix}-data.json"
        report_path = RESULT_DIR / f"{base_name}{suffix}-report.md"
        if not data_path.exists() and not report_path.exists():
            return data_path, report_path

    raise FileExistsError("无法生成不重复的报告文件名。")


def generate_report_bundle(
    data: dict[str, Any],
    report_type: str,
) -> dict[str, Path]:
    """保存原始 JSON 和 Markdown 报告，返回两个文件路径。"""
    if not isinstance(data, dict):
        raise TypeError("报告输入必须是解析后的 JSON 对象，即 Python dict。")

    normalized_report_type = str(report_type or "").strip().lower()
    template_name = TEMPLATE_MAP.get(normalized_report_type)
    if not template_name:
        supported_types = ", ".join(sorted(TEMPLATE_MAP))
        raise ValueError(
            f"不支持的报告类型：{report_type}。当前支持：{supported_types}"
        )

    template_path = TEMPLATES_DIR / template_name
    if not template_path.is_file():
        raise FileNotFoundError(f"报告模板不存在：{template_path}")

    template_environment = build_template_environment()
    template = template_environment.get_template(template_name)
    markdown_text = template.render(data=data)

    data_path, report_path = build_output_paths(
        data,
        normalized_report_type,
        datetime.now(),
    )

    try:
        with data_path.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")

        with report_path.open("x", encoding="utf-8", newline="\n") as file:
            file.write(markdown_text)
    except Exception:
        if data_path.exists() and not report_path.exists():
            data_path.unlink()
        raise

    return {
        "data_path": data_path,
        "report_path": report_path,
    }


__all__ = ["generate_report_bundle"]
