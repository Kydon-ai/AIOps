"""列出受控 Skill 的名称和简略描述。"""

import re
from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

from app.config import config


_FRONTMATTER_FIELD = re.compile(r"^(name|description):\s*(.*)$")


def _read_frontmatter_summary(path: Path) -> tuple[str, str]:
    """读取 Skill frontmatter 中的名称和描述，不加载正文。"""
    name = path.parent.name
    description = "暂无描述"
    lines = path.read_text(encoding="utf-8", errors="replace")[: config.skill_max_bytes].splitlines()

    if not lines or lines[0].strip() != "---":
        return name, description

    in_description_block = False
    description_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break

        if in_description_block:
            if line.startswith((" ", "\t")):
                description_lines.append(line.strip())
                continue
            in_description_block = False

        match = _FRONTMATTER_FIELD.match(line.strip())
        if not match:
            continue

        field, value = match.groups()
        value = value.strip().strip('"\'')
        if field == "name" and value:
            name = value
        elif field == "description":
            if value in {"|", ">", "|-", ">-", "|+", ">+"}:
                in_description_block = True
            elif value:
                description = value

    if description_lines:
        description = " ".join(description_lines)
    return name, description


@tool
def list_skills() -> str:
    """列出配置目录下所有 Skill 的精确名称、简略描述和文件路径。

    当用户要求读取某个 Skill，但没有提供精确名称时，应先调用此工具，
    再将返回的 name 原样传给 read_skill。
    """
    try:
        root = Path(config.skills_dir).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return f"Skill 目录不存在: {root}"

        entries: list[tuple[str, str, str]] = []
        for path in sorted(root.rglob("SKILL.md")):
            resolved = path.resolve()
            if root not in resolved.parents or not resolved.is_file():
                continue
            if resolved.stat().st_size > config.skill_max_bytes:
                name = resolved.parent.name
                description = "文件过大，需使用 read_skill 读取（或先缩小文件）"
            else:
                name, description = _read_frontmatter_summary(resolved)
            relative_path = resolved.relative_to(root).as_posix()
            entries.append((name, description, relative_path))

        if not entries:
            return f"未找到 Skill（查找目录: {root}）"

        lines = [f"Skill 列表（查找目录: {root}）:"]
        for index, (name, description, relative_path) in enumerate(entries, start=1):
            lines.extend(
                [
                    f"{index}. name: {name}",
                    f"   描述: {description}",
                    f"   文件: {relative_path}",
                ]
            )
        logger.info("列出 Skill: {} 个，目录: {}", len(entries), root)
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("列出 Skill 失败")
        return f"列出 Skill 失败: {exc}"
