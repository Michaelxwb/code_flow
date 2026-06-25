#!/usr/bin/env python3
"""技术栈检测信号一致性守门。

cf-init 与 cf-learn 各自内嵌项目类型检测信号（命令文件必须自包含——LLM 运行某命令时
只加载该命令，无法引用另一命令）。两份清单允许各有侧重，但核心框架信号必须同时存在，
否则"改一处漏一处"会让 init 与 learn 的项目类型判定分叉。

这是项目既有平台对等性守门（test_adapter_parity）思路的延伸：用测试锁住刻意的重复，
而非强行去重破坏自包含。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 核心框架/语言信号：init 与 learn 的项目类型判定都依赖，必须同时出现
CORE_STACK_SIGNALS = [
    "react", "vue", "svelte", "next",            # 前端框架
    "express", "fastify", "@nestjs",             # Node 后端
    "fastapi", "django", "flask",                # Python 后端
    "go.mod", "Cargo.toml",                       # Go / Rust
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_init_and_learn_share_core_stack_signals() -> None:
    init = _read("src/adapters/claude/commands/cf-init.md")
    learn = _read("src/adapters/claude/commands/cf-learn.md")
    for sig in CORE_STACK_SIGNALS:
        assert sig in init, f"cf-init 缺核心技术栈信号 {sig!r}"
        assert sig in learn, (
            f"cf-learn 缺核心技术栈信号 {sig!r}（与 cf-init 分叉，检测会不一致）"
        )
