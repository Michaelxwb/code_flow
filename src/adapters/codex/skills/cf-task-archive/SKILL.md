---
name: cf-task-archive
description: Archive a completed task file after completeness, correctness, traceability, and consistency validation. Use when all subtasks are done and you want to archive the task file and check for spec updates.
---

## 输入

- `cf-task-archive <file>` — 归档指定的 task 文件

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 `rg --files` 或 `find` 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 执行步骤

### 1. 完成度检查

1. 读取匹配到的 task 文件
2. 提取所有 `## TASK-xxx` 段落的 Status
3. 检查是否所有子任务均为 `done`

若有未完成子任务，拒绝归档并输出：

```
无法归档: 以下子任务未完成

  - TASK-002: in-progress (进度 1/4)
  - TASK-004: blocked ([BLOCKED] 等待 SDK)

请先完成所有子任务后再归档。
当前完成度: 2/4 (50%)
```

### 2. 归档前校验（Verify）

**Spec Context / Code Gate（先于四维校验）**：

- 需求目录必须存在 `spec-context.yml`；执行 `python3 .code-flow/scripts/cf_spec_context.py refresh --task-dir <需求目录> --root "$PWD" --json`
- 执行 `python3 .code-flow/scripts/cf_spec_gate.py --task-dir <需求目录> --stage code --json`；required Rule 的 stale/pending/conflict/unverified 任一存在即 FAIL
- 若 `.code-flow/.active-task.json` 仍指向本需求，必须先完成对应 TASK 的 Done Gate，并以 `{"gate_passed": true}` 调用 `active complete`；不得通过归档绕过 active 状态
- Context 与 Evidence 随需求目录一并归档，`_session` 仅是可重建投影，不是事实源

所有子任务 done 后，执行四维校验：

**完整性**：
- 所有 Checklist 项已勾选
- 全文无残留的 `#NOTES` 标记

**正确性**：
- 如果 `.code-flow/validation.yml` 存在，读取验证规则，用 shell 命令执行其中匹配的 `command`（如 `npx tsc --noEmit`、`python3 -m pytest` 等）
- 检查本次变更涉及的文件是否通过 lint/type check

**验收追溯**：
- 来源 design 含结构化 S-/E-/B- 场景时，逐项对照 `## Acceptance Coverage`，P0/P1 场景以及 RULE/高影响 RISK 映射场景必须全部存在且状态为 `verified`
- 每个负责任务的 `Acceptance-Refs`、`Acceptance Contract`、`Acceptance Evidence` 必须闭合，不得残留 `planned` / `pending` / `TBD`
- 测试层级不得低于 design；E2E 的真实边界和关键断言必须有文件/用例位置与 fixture/构造证据
- 汇总并重新执行契约中所有唯一验收命令；测试未收集、未执行或失败均为 FAIL
- `manual` 场景必须有用户确认和可复核记录。旧 design 没有结构化场景时注明“不适用”，不得伪造覆盖

**一致性**：
- 读取 task 文件的 `## Proposal`，对照实际代码变更，检查意图是否已实现

校验结果输出：

```
归档前校验:
  [PASS] 完整性: 所有 Checklist 已完成，无未解决 Notes
  [PASS] 正确性: cf-validate 通过
  [PASS] 验收追溯: 6/6 场景 verified，2 条 E2E 命令通过
  [WARN] 一致性: Proposal 提到"支持 OAuth 登录"，但未发现相关实现

WARN 不阻塞归档，但建议确认后再继续。继续归档？
```

PASS → 继续。WARN → 提示用户确认。FAIL → 阻塞归档，列出失败原因。

### 3. 执行归档

校验通过后，先判断布局（任务文件路径形态）：

**A. 需求目录布局**（任务文件位于 `.code-flow/tasks/<日期>/<需求>/<需求>.md`）——**整个需求目录一并归档**：
```bash
mkdir -p .code-flow/tasks/archived/<日期>
mv .code-flow/tasks/<日期>/<需求>/ .code-flow/tasks/archived/<日期>/<需求>/
```
目录内的 `.prd.md` / `.frontend.design.md` / `.backend.design.md` / `.design.md` / `.md` 随目录一并归档，无需逐个 mv。

**B. 旧扁平布局**（任务文件直接位于 `.code-flow/tasks/<日期>/<file>.md`，无需求目录，向后兼容）——逐文件归档：
1. 提取文件所在的日期目录名（如 `2026-03-15`）
2. 用 shell 命令创建归档目录并移动任务文件：
   ```bash
   mkdir -p .code-flow/tasks/archived/<日期目录>
   mv .code-flow/tasks/<日期目录>/<file>.md .code-flow/tasks/archived/<日期目录>/
   ```
3. 同名 `.design.md` 存在则一并移动：`mv .code-flow/tasks/<日期目录>/<file>.design.md .code-flow/tasks/archived/<日期目录>/`
4. 同名 `.prd.md` 存在则一并移动：`mv .code-flow/tasks/<日期目录>/<file>.prd.md .code-flow/tasks/archived/<日期目录>/`

**归档后统一收尾（布局 A/B 都必须执行）**：

1. 保存源日期目录为 `.code-flow/tasks/<日期>/`，完成移动后检查该目录是否还有其他需求或任务。
2. 如果目录为空，必须执行安全删除；非空则保留并在摘要中列出剩余条目：
   ```bash
   source_date_dir=".code-flow/tasks/<日期>"
   if [ -d "$source_date_dir" ] && [ -z "$(find "$source_date_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
     rmdir "$source_date_dir"
   fi
   ```
3. 复查归档目标存在、原任务/需求路径不存在；如果源日期目录仍存在但为空，视为归档未完成，立即删除后再继续。
4. 源日期目录包含其他条目时不得删除，摘要明确写“保留（仍有 N 个条目）”。

**临时约束清理（FEAT-08）**：删除 `.code-flow/specs/_session/task-<name>.md`（存在时）。该文件由 cf-task-start 生成，归档后不得残留。

### 4. Spec 更新提示

归档完成后，检查本次变更是否引入了新的规范约束需要同步到 specs：

1. 读取 task 文件中所有子任务的 Description 和 Checklist
2. 对照 `.code-flow/specs/` 下的现有规范
3. 如果发现新增的模式或约束未被 specs 覆盖，提示用户：

```
Spec 同步建议:
  本次变更引入了以下尚未记录的规范:
  - 所有 API handler 增加了 rate limiting 中间件
  - 新增 AppError 统一错误处理模式

  建议更新:
  - .code-flow/specs/backend/platform-rules.md — 补充 rate limiting 规则
  - .code-flow/specs/backend/code-quality-performance.md — 补充错误处理模式

  运行 cf-learn 可自动扫描并补充。
```

如果无新规范需同步，跳过此步骤。

### 5. 归档摘要

需求目录布局（A）：
```
已归档需求目录: <需求>/ → .code-flow/tasks/archived/<日期>/<需求>/
  含: <需求>.prd.md、<需求>.frontend.design.md / <需求>.backend.design.md（按实际）、<需求>.md
```

旧扁平布局（B）：
```
已归档: <file>.md → .code-flow/tasks/archived/<日期目录>/<file>.md
（如有关联设计简报）: <file>.design.md → .code-flow/tasks/archived/<日期目录>/<file>.design.md
（如有关联 PRD）: <file>.prd.md → .code-flow/tasks/archived/<日期目录>/<file>.prd.md
```

```
摘要:
  - 来源: docs/xxx设计说明书.md
  - 子任务数: N 个
  - 创建日期: 2026-03-15
  - 归档日期: 2026-03-20
  - 历时: 5 天
  - 校验: 4/4 PASS
  - 源日期目录: 已删除（为空）/ 已保留（仍有 N 个条目）
```
