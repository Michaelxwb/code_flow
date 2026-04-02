---
name: cf-task-plan
description: Break down a design document into structured task files with atomic subtasks, priorities, dependencies, and source chapter references. Use when starting work on a new feature from a design doc, or when planning implementation tasks.
---

## 输入

- `cf-task-plan <设计文档路径>` — 指定文档路径
- `cf-task-plan` — 交互式选择（从 `docs/` 目录列出候选）
- `cf-task-plan <设计文档路径> --explore` — 仅输出分析报告，不生成文件

## 执行步骤

### 1. 获取设计文档

如果用户提供了路径，直接用 Read 读取。

如果未提供路径：
1. 用 Glob 搜索 `docs/**/*.md` 列出所有文档
2. 展示列表，让用户选择目标文档
3. Read 读取选中的文档

### 2. 建立章节索引

Read 设计文档后，**先扫描文档结构**，建立章节索引表：

```
章节索引:
  §1 概述 (L1-L25)
  §2 需求分析 (L26-L80)
    §2.1 用户故事 (L28-L55)
    §2.2 非功能需求 (L56-L80)
  §3 详细设计 (L81-L200)
    §3.1 数据模型 (L83-L110)
    §3.2 API 接口 (L111-L155)
    §3.3 业务逻辑 (L156-L200)
  ...
```

此索引用于后续步骤中精确记录每个子任务的来源章节。

### 2.5. Explore 模式（--explore）

如果用户传入 `--explore`，在建立章节索引后，输出以下分析报告，**不生成任务文件**：

```
探索分析报告
============

文档: docs/xxx设计说明书.md
章节数: N | 预估子任务数: M

功能域识别:
  - 用户认证 (§3.1-§3.3) — 核心功能，建议 P0
  - 支付集成 (§3.4-§3.6) — 依赖第三方 SDK，存在阻塞风险
  - 通知系统 (§3.7) — 独立模块，可并行

关键依赖:
  - §3.2 API 接口依赖 §3.1 数据模型
  - §3.5 支付回调依赖 §3.4 订单模型

风险点:
  - §3.4 中提到的第三方 SDK 版本未确定
  - §3.6 缺少错误码定义

建议: 确认风险点后，运行 cf-task-plan docs/xxx.md 生成任务文件
```

输出后结束，不进入后续步骤。

### 3. 分析文档，拆解子任务

阅读设计文档内容，按以下原则拆解：

**拆解粒度**：
- 每个子任务应是一个可独立编码和验证的原子单元
- 一个子任务对应 1-3 个文件的修改
- 预估编码时间 15-60 分钟

**提取内容**：
- 功能需求 → 子任务标题 + 描述（提炼重点，不必复制全文）
- 实现要点 → Checklist 条目
- 模块依赖 → Depends 字段
- 紧急程度 → Priority（P0 核心功能 / P1 重要功能 / P2 优化项）

**关键：精确记录章节引用**

每个子任务的 `Source` 字段必须记录该任务对应的详设文档**具体章节和行号范围**。

引用格式：`文件路径#章节标题(L起始-L结束)`，多个章节用逗号分隔。

验证方法：记录引用后，用 Read 工具按行号范围回读验证，确保引用内容与子任务描述一致。如不一致，修正行号。

### 4. 生成任务文件方案

将拆解结果按以下格式组织，展示给用户确认：

```markdown
# Tasks: <功能/模块名称>

- **Source**: <设计文档路径>
- **Created**: <当前日期>
- **Updated**: <当前日期>

## Proposal

<2-3 句话说明变更意图：为什么做这个变更？解决什么问题？期望达成什么效果？>

---

## TASK-001: <子任务标题>

- **Status**: draft
- **Priority**: P0
- **Depends**:
- **Source**: docs/xxx.md#§3.1 数据模型(L83-L110)

### Description
<从设计文档提取的需求重点，不必复制全文>

### Checklist
- [ ] <具体实现步骤1>
- [ ] <具体实现步骤2>
- [ ] <编写测试>

### Log
- [<当前日期>] created (draft)

---

## TASK-002: <子任务标题>

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: docs/xxx.md#§3.2 API 接口(L111-L155), docs/xxx.md#§3.3 业务逻辑(L156-L180)

### Description
...
```

等待用户确认或调整。

### 5. 写入文件

用户确认后：
1. 文件名取模块/功能名（kebab-case），如 `auth-module.md`
2. 按当前日期创建目录：`.code-flow/tasks/<YYYY-MM-DD>/`
3. 用 Write 写入 `.code-flow/tasks/<YYYY-MM-DD>/<name>.md`

### 6. 输出摘要

```
已生成任务文件: .code-flow/tasks/2026-03-15/auth-module.md
- 子任务数: N
- P0: x 个, P1: y 个, P2: z 个
- 依赖链深度: N 层
- 详设引用覆盖: §3.1, §3.2, §3.3, §3.5 (共 4 个章节)

建议执行顺序:
  1. TASK-001 (无依赖)
  2. TASK-003 (无依赖) ← 可与 TASK-001 并行
  3. TASK-002 (依赖: TASK-001)
  ...

下一步:
  - 审阅任务: 直接阅读 .code-flow/tasks/2026-03-15/auth-module.md
  - 添加批注: 在.code-flow/tasks/2026-03-15/auth-module.md中进行 #NOTES "批注内容"
  - 开始编码: cf-task-start auth-module
```
