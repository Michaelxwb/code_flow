# Shared Specs Navigation Map

> 跨项目的共享模板和规范

## Purpose

共享模板供 `cf-task:align` 和 `cf-task:prd` 命令使用，为文档生成提供规范约束。

## Templates

### PRD Templates

| 文件 | 用途 | 适用场景 |
|------|------|---------|
| `prd-template.md` | 产品需求文档 | 需求早期阶段，在设计之前 |

### Design Templates

| 文件 | 用途 | 适用场景 |
|------|------|---------|
| `design/design-lite.md` | 轻量设计简报 | 功能开发/CLI/Bug修复/小型重构 |
| `design/design-full.md` | 完整设计文档 | 跨系统集成/性能优化/架构演进/中大型功能 |

## Workflow

```
需求 → cf-task:prd → PRD (.prd.md)
       ↓ （align 读取 .prd.md 派生）
       → cf-task:align → 设计 (.design.md)
       ↓ （plan 读取 .design.md 拆解）
       → cf-task:plan → 任务
```

## Selection Guide

```
需求阶段（还未明确用户与场景）：
  → cf-task:prd 生成 PRD

设计阶段（已有 PRD 或已明确做什么）：
  → cf-task:align 生成设计简报
    - 输入 .prd.md → 派生模式（继承目标/用户/功能/范围）
    - 输入文本 → 新建模式（从零对话）

复杂度判断：
  简单功能/脚本/Bugfix → design-lite.md
  复杂系统/跨模块/性能优化 → design-full.md
```

## Usage

1. `cf-task:prd` 命令引用 `prd-template.md` 生成 PRD
2. `cf-task:align` 命令引用 `design/design-lite.md` 或 `design/design-full.md` 生成设计文档
3. PRD 的 US/FEAT ID 被 design 的功能清单"来源"列引用，形成追溯链
