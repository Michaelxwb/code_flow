# Tasks: cf-task 对齐阶段

- **Source**: (plan mode 设计方案)
- **Created**: 2026-04-06
- **Updated**: 2026-04-06

## Proposal

为 cf-task 工作流增加对齐阶段，解决"用户直接丢设计文档生成任务，跳过目标/范围/约束对齐"的问题。
双通道设计：新增 cf-task:align 命令处理一句话需求（产出 .design.md），扩展 cf-task:plan 内置缺口分析处理不完整的设计文档。

---

## TASK-001: 创建 cf-task:align 命令 (Claude adapter)

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: (plan 文件 Part 1 全部)

### Description
创建 align.md 命令指令文件，实现从一句话需求到设计简报的结构化对话流程。
输出为 .design.md 文件，包含 Goal、Non-goals、Database Design、API Design、Technical Decisions、Constraints、Acceptance Criteria。

### Checklist
- [x] 创建 src/adapters/claude/commands/cf-task/align.md
- [x] 实现 Step 1 模式判断（新建 vs 恢复草稿）
- [x] 实现 Step 2 代码库上下文扫描（读 _map.md、检测技术栈、扫描现有模式）
- [x] 实现 Step 3 交互式细化（5 个维度递进，每轮 2-3 问题）
- [x] 定义 .design.md 输出格式（含 DB 表结构和 API 契约）
- [x] 实现 Step 4-5 展示草稿 + 写入文件
- [x] 实现中断恢复机制（早期写入草稿）
- [x] 参照 note.md 的交互模式确保风格一致

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-002: 创建 cf-task:align skill (Codex adapter)

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: (plan 文件 Part 1 + TASK-001 产出)

### Description
将 TASK-001 的 align.md 镜像为 Codex SKILL.md 格式，包含 YAML frontmatter，
保持行为逻辑和文案与 Claude 版本一致。

### Checklist
- [x] 创建 src/adapters/codex/skills/cf-task-align/SKILL.md
- [x] 添加 YAML frontmatter（name, description）
- [x] 镜像 Claude 版本的全部执行步骤
- [x] 调整命令语法（cf-task-align 替代 /cf-task:align）
- [x] 验证与 Claude 版本行为一致

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-003: 增强 cf-task:plan — 输入类型判断 + .design.md 处理 (Claude)

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: (plan 文件 Part 2 步骤 2 + 写入逻辑)

### Description
修改 plan.md，在步骤 1 后增加输入类型判断：
- .design.md 文件 → 跳过章节索引和缺口分析，直接拆解
- 普通设计文档 → 走原有流程

处理 .design.md 输入时：
- 从 Goal/Scope/Technical Approach 推导任务
- Source 字段引用 design 文件章节名
- Proposal 简要概述，指向 design 文件
- 任务文件与 .design.md 同目录

### Checklist
- [x] 在步骤 1 后增加"步骤 2: 判断输入类型"
- [x] 实现 .design.md 识别逻辑（路径后缀 + 文件内容格式）
- [x] 增加 .design.md 输入时的拆解逻辑（跳过章节索引）
- [x] 更新 Source 字段引用格式（design 文件章节名而非行号）
- [x] 更新 Proposal 格式（引用 design 文件）
- [x] 更新输入说明部分，增加 .design.md 路径用例

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-004: 增强 cf-task:plan — 缺口分析 + --quick (Claude)

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: (plan 文件 Part 2 步骤 2.7)

### Description
修改 plan.md，在章节索引后、拆解前增加缺口分析对话步骤。
AI 从设计文档中识别目标/非目标、范围、未确认决策、风险、验收标准，
输出结构化分析并交互讨论。--quick 跳过此步骤。
对齐结论写入 Proposal 的 Alignment 子节。

### Checklist
- [x] 在步骤 2.5 后增加"步骤 2.7: 缺口分析对话"
- [x] 定义缺口分析输出格式（5 个维度）
- [x] 实现交互方式（ok / 编号 / 自由文本 / skip）
- [x] 增加 --quick flag 说明和处理
- [x] 定义 Proposal 中 Alignment 子节格式
- [x] 更新输入说明，增加 --quick 用例

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-005: 同步 plan 变更到 Codex adapter

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-004
- **Source**: (TASK-003 + TASK-004 产出)

### Description
将 TASK-003 和 TASK-004 对 plan.md 的全部变更镜像到 Codex 的 cf-task-plan/SKILL.md。

### Checklist
- [x] 修改 src/adapters/codex/skills/cf-task-plan/SKILL.md
- [x] 镜像输入类型判断逻辑
- [x] 镜像缺口分析步骤
- [x] 镜像 --quick flag
- [x] 调整命令语法（cf-task-plan 替代 /cf-task:plan）
- [x] 验证与 Claude 版本行为一致

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-006: 修改 cf-task:archive 支持 .design.md 联动归档

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: (plan 文件 归档部分)

### Description
修改 archive.md，在归档步骤中检查同名 .design.md 文件是否存在，
若存在则一并移动到 archived 目录。

### Checklist
- [x] 修改 src/adapters/claude/commands/cf-task/archive.md
- [x] 在执行归档步骤中增加同名 .design.md 检测逻辑
- [x] 增加 .design.md 联动移动命令
- [x] 更新归档摘要输出（列出 .design.md）

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-007: 同步 archive 变更到 Codex adapter

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-006
- **Source**: (TASK-006 产出)

### Description
将 TASK-006 对 archive.md 的变更镜像到 Codex 的 cf-task-archive/SKILL.md。

### Checklist
- [x] 修改 src/adapters/codex/skills/cf-task-archive/SKILL.md
- [x] 镜像 .design.md 联动归档逻辑
- [x] 验证与 Claude 版本行为一致

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)

---

## TASK-008: 更新 USAGE.md 文档

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-004, TASK-006
- **Source**: (全部变更)

### Description
更新 docs/USAGE.md，新增 cf-task:align 章节，更新 cf-task:plan 和 cf-task:archive 章节。

### Checklist
- [x] 新增 cf-task:align 命令说明（用途、用法、示例）
- [x] 更新 cf-task:plan 说明（--quick flag、缺口分析、.design.md 输入）
- [x] 更新 cf-task:archive 说明（.design.md 联动归档）
- [x] 更新工作流示意图（如有）

### Log
- [2026-04-06] created (draft)
- [2026-04-06] completed (done)
