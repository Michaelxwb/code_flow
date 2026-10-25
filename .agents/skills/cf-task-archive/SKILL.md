---
name: cf-task-archive
description: Archive a completed task file after completeness, correctness, traceability, and consistency validation. Use when all subtasks are done and you want to archive the task file and check for spec updates.
---

## 输入

- `cf-task-archive <需求目录或任务文件>` — 定位需求，通过运行时归档整个需求目录

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 `rg --files` 或 `find` 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 执行步骤

### 1. 完成度检查

1. 读取匹配到的 task 文件
2. 提取所有 `## TASK-xxx` 段落的 Status
3. 若 active marker 指向本需求，读取其中真实 TASK ID；满足 finish 条件后先执行 `code-flow task finish --root "$PWD" --task-dir "<需求目录>" --task <实际TASK-ID> --json`。失败按原因修复，禁止手动改状态。
4. 检查所有子任务均为 `done` 或 `verified`。`done` 由下一步需求级终验提升为 `verified`；其他状态不能归档。

若有未完成子任务，拒绝归档并输出：

```
无法归档: 以下子任务未完成

  - TASK-002: in-progress (进度 1/4)
  - TASK-004: blocked ([BLOCKED] 等待 SDK)

请先完成所有子任务后再归档。
当前完成度: 2/4 (50%)
```

### 2. 归档前校验（Verify）

**Spec Context / 终验与 Gate（先于四维校验）**：

- 需求目录必须存在 `spec-context.yml`；执行 `code-flow spec refresh --task-dir <需求目录> --root "$PWD" --json`
- 执行 review 终验：`code-flow task verify-e2e --task-dir <需求目录> --root "$PWD" --json`（全量聚合需求目录全部 task context 的 required verifier——code 延后项 + `stage: review` 层——与 acceptance E2E，按 spec/rule 去重执行一次并写回证据）；`decision=pass` 才继续，失败保持阻断。返回 `manual_confirmation_required` 时，先按 verify-e2e 的「人工验收确认」流程取得用户确认并执行 `confirm-manual`，再重跑
- 执行 `code-flow spec gate --task-dir <需求目录> --stage code --json`；required Rule 的 stale/pending/conflict/unverified 任一存在即 FAIL。**必须在 verify-e2e 之后**：任务层延后（deferred_to_review）与 refresh 转 stale 的规则由终验全量补跑翻牌
- 执行 `code-flow spec gate --task-dir <需求目录> --stage review --json`；required Rule 存在 unverified review 证据即 FAIL（先完成 review 终验）
- Context 与 Evidence 随需求目录一并归档，`_session` 仅是可重建投影，不是事实源

所有子任务 verified 后，执行四维校验：

**完整性**：
- 所有 Checklist 项已勾选
- 全文无残留的 `#NOTES` 标记

**正确性**：
- 核对终验返回的 `layers.validators`：全量 validation（含 heavy）必须通过。终验已计算验证范围，不能把工作区干净误认为无需验证，也无需额外重复调用 validate。
- 失败时按具体 validator 的命令、输出和修复建议处理，再重跑终验；通过记录按内容指纹复用。

**验收追溯**：
- 来源 design 含结构化 S-/E-/B- 场景时，逐项对照 `## Acceptance Coverage`，P0/P1 场景以及 RULE/高影响 RISK 映射场景必须全部存在且状态为 `verified`
- 每个负责任务的 `Acceptance-Refs`、`Acceptance Contract`、`Acceptance Evidence` 必须闭合，不得残留 `planned` / `pending` / `TBD`
- 测试层级不得低于 design；E2E 的真实边界和关键断言必须有文件/用例位置与 fixture/构造证据
- 核对终验返回的 `layers.e2e`：运行时已校验锁定 manifest 并复验 acceptance。逐项查看 `checks` 与 `check_results`，多 check 场景必须全部有有效结果；测试未收集、未执行或失败均为 FAIL。不要再额外编排 acceptance run。若返回 manifest 基线错误，使用 `code-flow acceptance manifest --verify-plan --task-dir "<需求目录>" --task-file "<任务文件>"` 定位并修复后重跑终验。
- `manual` 场景必须有用户确认和可复核记录。旧 design 没有结构化场景时注明“不适用”，不得伪造覆盖

**一致性**：
- 读取 task 文件的 `## Proposal`，对照实际代码变更，检查意图是否已实现

校验结果输出：

```
归档前校验:
  [PASS] 完整性: 所有 Checklist 已完成，无未解决 Notes
  [PASS] 正确性: layers.validators 通过
  [PASS] 验收追溯: 6/6 场景 verified，2 条 E2E 命令通过
  [FAIL] 一致性: Proposal 要求"支持 OAuth 登录"，但缺少对应实现与验收证据
```

全部 PASS → 继续。FAIL → 列出具体缺口，修复后重新验证。只有涉及需求取舍或人工验收时请求用户确认。

### 3. 执行归档

**A. 需求目录布局**（任务文件位于 `.code-flow/tasks/<日期>/<需求>/<需求>.md`）——**整个需求目录一并归档**。先完成临时约束清理，再调用唯一移动入口：

```bash
code-flow task cleanup-session --task-dir "<需求目录>" --root "$PWD" --json
code-flow task archive --task-dir "<需求目录>" --root "$PWD" --json
```

cleanup-session 逐任务删除 `specs/_session/task-<任务文件stem>.md` 投影，必须在源目录仍存在时执行。archive 内置 full verify；内容未变时复用有效证据，失败返回 `archive_verify_failed` 与具体 `verify` 结果，源目录保留。只有 `decision=pass` 才完成移动，目标路径使用返回的 `archived_to`，不得自行推算日期或同名后缀，不得手工 `mv` 绕过门禁。

**B. 旧扁平布局**（任务文件直接位于 `.code-flow/tasks/<日期>/<file>.md`）——保留向后兼容的文件查找。当前归档运行时以独立需求目录为边界；旧文件缺少该边界时，报告“先完成需求目录迁移”，保留原文件。不得把包含其他需求的日期目录作为 `--task-dir`，也不得逐文件归档绕过 Context、manifest 和 full verify。

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
已归档需求目录: <需求>/ → <archived_to>
  含: <需求>.prd.md、<需求>.frontend.design.md / <需求>.backend.design.md（按实际）、<需求>.md
```

旧扁平布局（B）尚未迁移时，报告原路径与缺少的需求边界，不输出“已归档”。

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

<!-- code-flow:runtime-commands start -->

运行时命令示例（由命令契约生成；实际参数见各命令 --help）：

```bash
code-flow spec refresh --task-dir "<需求目录>" --root "$PWD" --json
code-flow task finish --task-dir "<需求目录>" --task TASK-001 --root "$PWD" --json
code-flow task verify --task-dir "<需求目录>" --layers validators,review,e2e --profile changed --root "$PWD" --json
code-flow task verify-e2e --task-dir "<需求目录>" --root "$PWD" --json
code-flow task cleanup-session --help
code-flow spec gate --help
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json"
code-flow task archive --task-dir "<需求目录>" --root "$PWD" --json
```

<!-- code-flow:runtime-commands end -->
