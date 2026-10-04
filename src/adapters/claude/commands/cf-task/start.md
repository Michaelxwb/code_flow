# cf-task:start

激活子任务并开始编码。支持单任务模式和整文件模式。

## 输入

- `/cf-task:start <file> TASK-001` — 激活指定文件中的单个子任务
- `/cf-task:start <file>` — 激活文件内所有可执行的 draft 子任务；批次内独立任务默认并行派发子 agent
- `/cf-task:start <file> --serial` — 整文件模式强制串行执行，不建 worktree

其中 `<file>` 为 `.code-flow/tasks/` 下的文件名，可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

示例：
- `/cf-task:start auth-module TASK-002`
- `/cf-task:start auth-module`

## 单任务模式

### 1. 前置检查

用 Read 读取任务文件，定位 `## TASK-xxx` 段落：

**状态检查**：Status 必须为 `draft`。若为其他状态：
- `in-progress` → 校验现有 marker 的需求目录、TASK-ID 与 Context；匹配且为 active 才继续步骤 2，跳过重复 Start。paused/blocked 先解除原因并调用 resume；marker 缺失或不匹配先 doctor，不能仅改 Markdown。
- `done` / `verified` → 实现已完成；done 的 E2E 可为 e2e_deferred，转 verify-e2e 终验。发现缺口时报告并显式重新规划修复任务，不直接把终态改成 in-progress。
- `blocked` → 提示"任务被阻塞"，列出 Notes 中的阻塞原因，结束

**#NOTES 检查**：扫描该子任务段落全文（Description、Checklist 等）
- 如果存在 `#NOTES` 标记，说明用户 review 时留下了未讨论的问题，拒绝启动
- 输出：`前置检查失败：以下 #NOTES 未解决\n- 密码加密存储  #NOTES 用 bcrypt 还是 argon2？\n- ...\n请先运行 /project:cf-task:note <file> TASK-xxx 讨论并解决`

**依赖检查**：读取 `Depends` 字段
- 对每个依赖的 TASK-ID，在同文件中查找其 Status
- 所有依赖必须为 `done` 或 `verified`
- 未满足 → 输出：`前置检查失败：以下依赖未完成\n- TASK-001: in-progress\n- TASK-003: draft`

**验收契约检查**：
- 如果 task 含 `## Acceptance Coverage`，当前子任务必须有 `Acceptance-Refs`、`Acceptance Contract` 和 `Acceptance Evidence`
- `Acceptance-Refs` 中每个 S-/E-/B- 都必须出现在全局覆盖表和当前契约中，测试层级与关键真实边界必须和 design 一致
- 旧 task 没有覆盖表但来源 design 含结构化验收场景时，先从 design 回填覆盖表与契约；回填完成前不得修改生产代码
- 非行为类任务可显式写 `Acceptance-Refs: N/A`；不得用 N/A 跳过已有设计场景

### 2. 加载详设上下文

前置检查通过后，**编码前先加载关联的详设文档章节**：

1. 读取子任务的 `Source` 字段，解析章节引用
   - 格式：`docs/xxx.md#§3.1 数据模型(L83-L110)`
   - 提取：文件路径 + 行号范围
2. 用 Read 按行号范围读取详设文档的对应章节（使用 offset/limit 参数）
3. 将读取的章节内容作为编码上下文，与 Checklist 一起指导实现
4. 按 `Acceptance-Refs` 精确读取验收场景及其关联 RULE/RISK；不得只依赖摘要，也不得遗漏场景的测试层级、关键真实边界和预期结果

示例：Source 为 `docs/auth.md#§3.2 API 接口(L111-L155), docs/auth.md#§3.5 错误码(L201-L220)`
→ Read `docs/auth.md` offset=111 limit=45
→ Read `docs/auth.md` offset=201 limit=20

### 3. 激活并准备验收测试

在改状态或生产代码前，顺序固定且不得跳步：

1. 调用 `code-flow task start --task-dir ... --root ... --task ... --task-file ... --json`，由单个进程按 refresh → active start → session 顺序执行 Start Gate；stdin JSON 的 `owned_paths` 只填启动前已存在的未提交改动（逐路径确认归属），不是计划要改的文件；干净工作区传空数组（提交后的改动由基线并集自动纳入）。stale/conflict、依赖未闭合、已有/损坏 marker、未归属 diff 或 hash 不一致立即阻断。禁止先 start 再 refresh，避免 active marker 在编码前自行漂移。前置硬门禁（blocked / #NOTES / 依赖）由 workflow service 在改状态前强制执行。用户已确认内容时，Design/Plan 的 pending 不单独阻止激活；不新增阶段状态门禁。
2. 从命令返回值读取 refresh 后的 Context hash、active 状态和 session 输出路径；该命令只根据当前 TASK 的 `Spec-Refs`、Source 与 Acceptance Contract 覆盖写入 `.code-flow/specs/_session/task-<name>.md`，禁止重新 catalog 或猜测规则。
3. Start 返回成功时，workflow service 已通过可恢复事务同步 Status、started log 和 active marker；不要再手动改状态。失败保留原状态，按返回原因恢复。
4. 在修改任何生产代码前，为每个 Acceptance-Ref 填写测试文件、包含场景 ID 的测试用例名和可单独执行的命令（E2E 只登记，不在本阶段执行）
5. 先编写验收测试（E2E 只编写并登记）。E2E 测试必须经过契约声明的真实边界，不得用 mock 绕过 Store、Resolver、Builder、Renderer、Browser 等指定组件
6. 新功能或缺陷修复先执行一次测试并记录 RED：失败命令、失败用例和与预期缺陷对应的失败原因。纯重构或已有行为补测无法 RED 时，记录原因，不得伪造失败。E2E 场景不执行 RED，登记为 e2e_deferred 留给 verify-e2e

RED 证据写入 `Acceptance Evidence`：

```markdown
| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: generation 未递增 | pending | pending | real Store + Renderer fixture | test-written |
```

### 3.1 实现与逐项更新

1. RED 证据就绪后，结合详设上下文、Acceptance Contract 与 Checklist 修改生产代码
2. 每完成一个 checklist 项，用 Edit 将 `- [ ]` 改为 `- [x]`
3. 如果实现中发现必须改变测试层级或真实边界，停止编码并记录 `#NOTES`，经用户确认并同步 design 后才能继续；agent 不得自行降级

### 3.2 GREEN 与验收证据

1. 执行 functional 验收和受影响范围的回归测试；E2E 只登记场景、断言、真实边界和命令，RED/GREEN 都不在编码阶段执行，统一留给 verify-e2e；manual 场景只登记 `manual_pending`（原因、边界、验收方式），人工确认统一留给 verify-e2e。
2. 对每个预期结果记录断言位置与 fixture/构造路径；环境未就绪的错误不得冒充有效 RED，明确记录尚未验证。
3. 由 runner 写入最新状态和运行历史；不要覆盖原契约、RED 证据或历史失败。functional 必须 verified，已登记的 E2E 在实现阶段允许 e2e_deferred。
4. 测试未收集、命令未实际执行或缺少关键断言，都不算验证完成。失败重跑必须使旧 verified 失效。

### 3.5 TASK-bound Spec Session

激活后，若任务文件头 Source 指向的 design 文档含验收条件章节（如 §2.5 验收条件 / 验收标准）：

1. 只提取当前任务 `Spec-Refs` 与 `Acceptance-Refs` 对应的 Rule hash、verifier、artifact refs、场景、测试层级和真实边界，生成 `.code-flow/specs/_session/task-<name>.md`：
   - frontmatter：`description: 当前任务 <name> 的验收约束（cf-task:start 生成，archive 清理）`
   - 正文：验收场景与约束的精简列表（≤300 token）；必须保留全部引用 ID、层级、边界和预期结果，不能为压缩而删除场景
2. 任务模式直接读取这个投影，禁止经 Spec Catalog 二次选择；同名文件已存在则原子覆盖。
3. 50 Rule 等超预算任务按 required/当前阶段优先输出受控摘要，完整 Context 保留不丢失，并明确提示拆 TASK；不得用截断隐藏 required 缺口。

> `_session/` 不入库（.gitignore 模板已覆盖）、不参与规范审计与预算。

### 4. 自动完成

只有同时满足以下条件才能自动完成：
- 所有 checklist 项均为 `[x]`
- functional 在契约、证据和覆盖表中均为 `verified`；E2E 可为 `e2e_deferred`，`manual` 场景与 review 层 manual 规则延后到需求级终验由用户确认，仍不得遗留未登记的 `planned` / `pending` / `TBD`
- 测试层级未低于 design，关键真实边界没有被 mock 绕过
- 每个预期结果都有具体断言位置，functional 验收命令和回归测试均已实际通过；E2E 留到终验执行
- 显式 `stage: code` 的 manual 规则已有用户确认和可复核记录；默认 review 层的 manual 规则与 manual 场景在 verify-e2e 一次性确认

满足后，执行唯一收尾入口：

```bash
code-flow task finish --root "$PWD" --task-dir "<需求目录>" --task TASK-001 --json
```

该命令先校验完整任务身份与锁定 manifest，再执行 Done Gate：本任务范围（`Spec-Refs` ∪ 改动路径命中）的 code verifier + 本任务 acceptance 场景 + 轻量 validation.yml（不含 heavy）；范围外/超预算的 verifier 标记 `deferred_to_review`、`heavy: true` validator 标记 `deferred_heavy`，都不阻塞本任务，统一在需求级 verify-e2e / 归档全量补跑；通过后以可恢复事务更新 done、Log、Updated 并清理 marker。只有 `decision=pass` 才输出完成并启动下一 TASK。禁止手动设置 done 或传入自报的 gate_passed 绕过验证。

Done Gate 只执行 code 层验证；review 层 manual 规则与 manual 场景不逐任务确认，延后到需求级 verify-e2e（返回 `manual_confirmation_required` 时按该命令的「人工验收确认」流程一次性确认）。

任一验收条件不满足时保持 `in-progress`，明确列出缺口，不能标记为 `done`。

### 5. 文档同步检查

子任务完成后，轻量检查本次编码是否引入了需要同步到 specs 或导航地图的内容：

1. 回顾本次编码的变更（新增/修改了哪些文件和模式）
2. 快速对照 `.code-flow/specs/` 下对应领域的规范文件和 `<map-file>.md`
3. 如果发现以下情况，输出同步提示：
   - 新增了 specs 未记录的编码模式（如新的错误处理方式、新的中间件）
   - 新增了目录或入口文件，但 `<map-file>.md` 中未体现
   - 修改了数据流或模块关系

```
Spec 同步提示:
  本次编码引入了以下变更，建议同步到规范:
  - 新增 <模式描述> → <spec-path>/
  - 新增 <文件路径> → <map-file>.md Key Files

  运行 /cf-learn --map 可自动更新导航地图。
```

如果无需同步，跳过此步骤，不输出任何提示。

> 注：此检查是轻量级的建议，不阻塞流程。完整的三维校验在 archive 阶段执行。

## 整文件模式

### 1. 扫描所有子任务

用 Read 读取整个 task 文件，提取所有 `## TASK-xxx` 段落的 ID、Status、Depends。

### 2. 加载详设文档

1. 读取文件头的 `Source` 字段，提取设计文档路径（文件头 Source 只有路径，无行号范围）
2. 用 Read 加载详设文档作为全局上下文
   - 如果文档 ≤ 500 行：全文加载（不使用 offset/limit）
   - 如果文档 > 500 行：仅加载各子任务 Source 中引用的章节（合并行号范围，去重后按 offset/limit 加载）
   - 这样避免大型详设文档一次性消耗过多 token

> 注：整文件模式尽量加载完整详设（给全局视角），但对超长文档降级为章节加载。单任务模式始终只加载引用章节。

### 3. 构建执行计划

按依赖关系拓扑排序：
1. 筛选所有 `draft` 状态的子任务
2. 按依赖关系排序：先无依赖的，再逐层解锁
3. 逐个检查 Notes 前置条件

输出执行计划：
```
执行计划（共 N 个可激活子任务）：

批次 1（可并行）：
  - TASK-001: xxx
  - TASK-003: xxx

批次 2（依赖批次 1）：
  - TASK-002: xxx (依赖 TASK-001)

跳过（前置条件未满足）：
  - TASK-004: #NOTES 未解决
  - TASK-005: 依赖 TASK-004 (blocked)

开始执行（批次内默认并行派发子 agent，预检失败自动回退串行）...
```

### 4. 执行批次

对每个批次执行；批次内仅 1 个 TASK、传入 `--serial`、或并行预检失败时，走 4.6 串行回退。

#### 4.1 并行预检与 worktree 准备

```bash
code-flow task parallel prepare --root "$PWD" \
  --task-file "<任务文件相对路径>" --tasks TASK-001,TASK-003 --json
```

- 返回 `{"ok": true, "run_id": ..., "worktrees": [...]}` 才可并行；`ok: false` 时打印 `code`/`message` 并回退串行，禁止手工建 worktree/分支。
- 预检内容：git 仓库、`.code-flow/.gitignore` 含 `worktrees/`、主 worktree 无 active marker、tracked 工作区干净。命令会自动提交仅位于当前需求目录内的流程产物（任务文件等）；需求目录以外存在未提交改动时拒绝并行，提示用户先提交或收起。

#### 4.2 派发子 agent（平台自适应）

若当前平台提供子 agent/Task 派发能力，为本批次每个 TASK 各派发一个子 agent（同一批并发不超过 3，超出时按 TASK 顺序拆成多轮）。子 agent prompt 必须包含 worktree 绝对路径、TASK-ID、任务文件相对路径，并声明以下硬性要求：

1. 进入 worktree：所有命令 `cd <worktree>` 执行，文件读写使用该 worktree 内路径。
2. 按本命令"单任务模式"步骤 1-4 完成该 TASK：`code-flow task start` → functional RED → 实现 → functional GREEN（E2E 只登记）→ `code-flow task finish --root "<worktree>"`。
3. 平台 hook 注入绑定主工作区；子 agent 必须显式读取 Spec Session（路径取 start 返回的 `session_output`，默认 `.code-flow/specs/_session/task-<任务文件stem>.md`）与详设章节，不得依赖自动注入。
4. 完成时在 worktree 内提交全部改动（含任务文件 Checklist/Evidence/Status 更新），提交信息 `cf-task(<TASK-ID>): <标题>`。
5. `finish` 返回 `decision: block` 时不得提交：保留现场，原样回报阻断原因（如 scope expansion 新增 required Spec、验收失败）与 `code-flow spec status --json` 输出，由主 agent 决定局部 Plan/Align、修复后重派或接管；不得自行 resume 绕过门禁。
6. 返回摘要：TASK-ID、Status、验收命令及结果、提交 SHA、遗留问题。

标准 worker prompt 模板（替换占位符后派发）：

```
你在隔离 worktree 中执行 <TASK-ID>：<worktree 绝对路径>。
1) cd 到 worktree；先读 Spec Session（start 返回的 session_output，默认 .code-flow/specs/_session/task-<任务文件stem>.md）、任务文件的当前 TASK 段落与 design 来源章节；
2) code-flow task start → 写验收测试记录 RED → 实现 → GREEN；
3) 运行 code-flow task finish --root "$PWD" --task <TASK-ID> --json；decision=pass 后【再】提交全部改动（含 finish 回写的 Evidence/状态）：git add -A && git commit -m "cf-task(<TASK-ID>): <标题>"；
4) 返回摘要：TASK-ID、Status、验收命令与结果、commit SHA、遗留问题。
```

> 提交必须在 finish 之后：finish 通过后会回写 Evidence/状态；collect 默认会自动提交这些回写，但显式提交更清晰。

子 agent 中断（取消/超时）时不要重新 prepare：检查该 worktree 的 `git status`、`git log <base>..HEAD` 与 marker——
- 无改动且无 marker：直接接管，按单任务模式继续；
- 有未提交改动或已有提交但未 done：在 worktree 内接管收尾（补实现/测试并 finish），再走 4.3 collect；
- 已 done 且 marker 已清理：直接进入 4.3。

平台不支持子 agent 时，不建 worktree，直接走 4.6 串行回退。

#### 4.3 收集与校验

```bash
code-flow task parallel collect --root "$PWD" --run-id <run_id> --json
```

- 每个任务必须 `ok: true`（改动已提交、Status 为 done/verified、marker 已清理、有提交）。
- `collect` 在任务 done/verified 且 marker 已清理后，会自动提交 finish 回写的 Evidence/状态（`--no-commit` 关闭并回到严格模式）；finish 之外的未提交改动仍应人工确认。
- 任一任务失败：停止本批次，不合并；保留 worktree 并列出失败原因。修复后重跑 collect；确认放弃时执行 4.5 cleanup。

#### 4.4 回并主分支

按 TASK-ID 先后顺序回并。统一入口自动完成：worktree 内 rebase → 状态文件冲突按确定性并集规则解决 → 主工作区 `--no-ff` 合并 → `code-flow spec refresh` 收敛 hash：

```bash
code-flow task parallel merge --root "$PWD" --run-id <run_id> --json
```

- 返回 `ok: true` 才继续；`already_merged` 表示该任务已并入（幂等，可重跑）；任一任务失败即停止，修复后重跑 merge 续跑。
- `code_conflict`：代码文件冲突无法程序化合并（返回冲突文件列表，rebase 已中止、主工作区未受影响）。人工读取冲突现场 + 本任务详设章节与 Acceptance Contract，合并双方意图（不是二选一）；无法调和（设计要求互斥）→ 保留现场与分支，列出矛盾点叫停交用户决策，不得擅自删除一方实现。解决后重跑 merge。
- 状态文件冲突（任务 md 覆盖状态列 / `spec-context.yml` / `.acceptance-manifest.json`）由 merge 自动按确定性并集规则处理，无需手工编辑：覆盖状态列两边各自 verified 的行均保留；`spec-context.yml` 取证据并集、verified 优先；manifest 按 verified/revision 合并。
- merge 成功后自动执行 `refresh` 并在结果中返回 `pass` / `block: ...`；随后重跑合并双方的 functional 验收与 `cf_spec_gate --stage code --json`，失败则记录合并前 HEAD 并 `git reset --hard <合并前HEAD>`（分支与 worktree 原样保留），回到 4.2 让对应子 agent 修复后重新 collect / merge。
- E2E 验收留给 verify-e2e，不在本步骤执行。

全部任务合并完成后进入 4.5 清理。

#### 4.5 清理

```bash
code-flow task parallel cleanup --root "$PWD" --run-id <run_id> --json
```

清理 worktree；已合入的分支自动删除，未合入的保留供排查。worktree 存在未提交改动时 cleanup 会拒绝，先人工确认再决定处理方式。全部批次完成后进入步骤 5。

#### 4.6 串行回退

未启用并行、批次仅 1 个任务或预检失败时，对批次内可激活子任务执行单任务模式步骤 3-4（详设已在步骤 2 加载，无需重复读取），完成一个后再解锁下一个。

### 5. 输出摘要与文档同步检查

所有子任务执行完毕后：

1. 输出执行摘要：

```
执行完成：
  - 完成: TASK-001, TASK-003, TASK-002
  - 跳过: TASK-004 (Notes 未解决)
  - 剩余 draft: 1 个
```

2. 对本轮所有完成的子任务，统一执行一次文档同步检查（同单任务模式步骤 5），汇总输出建议：

```
Spec 同步提示:
  本轮编码引入了以下变更，建议同步到规范:
  - [<任务ID>] 新增 <模式描述> → <spec-path>/
  - [<任务ID>] 新增 <文件路径> → <map-file>.md Module Map

  运行 /cf-learn --map 可自动更新导航地图。
```

3. 若需求目录已无 `draft` / `in-progress` / `blocked` 子任务，提示：运行 `/cf-task:verify-e2e <需求目录>` 执行延迟的 E2E 终验。

<!-- code-flow:runtime-commands start -->

运行时命令示例（由命令契约生成；实际参数见各命令 --help）：

```bash
code-flow spec status --task-dir "<需求目录>" --root "$PWD" --json
code-flow spec refresh --task-dir "<需求目录>" --root "$PWD" --json
code-flow task start --task-dir "<需求目录>" --task-file "<任务文件>" --task TASK-001 --root "$PWD" --json
code-flow task finish --task-dir "<需求目录>" --task TASK-001 --root "$PWD" --json
code-flow task parallel --help
```

<!-- code-flow:runtime-commands end -->
