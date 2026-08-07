"""受控 Skill 读取工具。"""

from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

from app.config import config


def _skill_candidates(root: Path, skill_name: str) -> list[Path]:
    """返回允许查找的 Skill 文件候选路径。"""
    name = skill_name.strip().replace("\\", "/")
    return [
        root / name / "SKILL.md",
        root / f"{name}.md",
        root / name,
    ]


@tool
def read_skill(skill_name: str) -> str:
    """读取一个自动运维 Skill 的操作说明。

    Skill 文件只能从配置的 skills_dir 中读取，推荐结构为：
    skills/<skill_name>/SKILL.md。
    自动修复前应先读取对应 Skill，确认检查步骤、允许的服务和回滚方式。
    """
    try:
        root = Path(config.skills_dir).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return f"Skill 目录不存在: {root}"

        for candidate in _skill_candidates(root, skill_name):
            resolved = candidate.resolve()
            if root not in resolved.parents and resolved != root:
                continue
            if resolved.is_file():
                if resolved.stat().st_size > config.skill_max_bytes:
                    return f"Skill 文件过大，拒绝读取: {resolved.name}"
                content = resolved.read_text(encoding="utf-8")
                logger.info("读取 Skill: {}", resolved)
                return f"Skill: {skill_name}\n路径: {resolved}\n\n{content}"

        return f"未找到 Skill: {skill_name}（查找目录: {root}）"
    except Exception as exc:
        logger.error("读取 Skill 失败: {}", exc)
        return f"读取 Skill 失败: {exc}"

