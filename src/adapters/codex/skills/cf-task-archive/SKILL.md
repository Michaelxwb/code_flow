---
name: cf-task-archive
description: Archive a completed task file after three-dimensional validation (completeness, correctness, consistency). Use when all subtasks are done and you want to archive the task file and check for spec updates.
---

## 输入

- `cf-task-archive <file>` — 归档指定的 task 文件

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 执行步骤

### 1. 完成度检查

1. 用 Read 读取匹配到的 task 文件
2. 提取所有 `## TASK-xxx` 段落的 Status
3. 检查是否所有子任务均为 `done`

若有未完成子任务，拒绝归档并输出原因。

### 2. 归档前校验（Verify）

所有子任务 done 后，执行三维校验：

**完整性**：
- 所有 Checklist 项已勾选
- 全文无残留的 `#NOTES` 标记

**正确性**：
- 如果 `.code-flow/validation.yml` 存在，Read 读取验证规则，用 Bash 执行其中匹配的 `command`（如 `npx tsc --noEmit`、`python3 -m pytest` 等）
- 检查本次变更涉及的文件是否通过 lint/type check

**一致性**：
- 读取 task 文件的 `## Proposal`，对照实际代码变更，检查意图是否已实现

校验结果：PASS → 继续。WARN → 提示用户确认。FAIL → 阻塞归档，列出失败原因。

### 3. 执行归档

校验通过后：

1. 提取文件所在的日期目录名（如 `2026-03-15`）
2. 用 Bash 创建归档目录并移动文件：
   ```bash
   mkdir -p .code-flow/tasks/archived/<日期目录>
   mv .code-flow/tasks/<日期目录>/<file>.md .code-flow/tasks/archived/<日期目录>/
   ```
3. 检查同目录下是否存在同名的 `.design.md` 文件（如 `<file>.design.md`），若存在则一并移动：
   ```bash
   # 仅当文件存在时执行
   mv .code-flow/tasks/<日期目录>/<file>.design.md .code-flow/tasks/archived/<日期目录>/
   ```
4. 如果原日期目录为空，删除空目录

### 4. Spec 更新提示

归档完成后，检查本次变更是否引入了新的规范约束需要同步到 specs：

1. 读取 task 文件中所有子任务的 Description 和 Checklist
2. 对照 `.code-flow/specs/` 下的现有规范
3. 如果发现新增的模式或约束未被 specs 覆盖，提示用户更新对应 spec 文件

如果无新规范需同步，跳过此步骤。

### 5. 归档摘要

```
已归档: <file>.md → .code-flow/tasks/archived/<日期目录>/<file>.md
（如有关联设计简报）: <file>.design.md → .code-flow/tasks/archived/<日期目录>/<file>.design.md

摘要:
  - 来源: docs/xxx设计说明书.md
  - 子任务数: N 个
  - 创建日期: 2026-03-15
  - 归档日期: 2026-03-20
  - 历时: 5 天
  - 校验: 3/3 PASS
```
