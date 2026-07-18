---
name: cf-task-start
description: Activate a subtask and begin coding. Runs pre-checks (status, #NOTES, dependencies), loads design doc context by source reference, executes checklist items, and marks done when all items complete. Use when starting or continuing implementation work on a task.
---

## 输入

- `cf-task-start <file> TASK-001` — 激活指定文件中的单个子任务
- `cf-task-start <file>` — 激活文件内所有可执行的 draft 子任务

其中 `<file>` 为 `.code-flow/tasks/` 下的文件名，可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 `rg --files` 或 `find` 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

示例：
- `cf-task-start auth-module TASK-002`
- `cf-task-start auth-module`

## 单任务模式

### 1. 前置检查

读取任务文件，定位 `## TASK-xxx` 段落：

**状态检查**：Status 必须为 `draft`。若为其他状态：
- `in-progress` → 提示"任务已在进行中，继续编码"（不阻塞，直接跳到步骤 2）
- `done` → 先执行验收契约检查；全部 verified 才提示"任务已完成"并结束，否则恢复为 `in-progress`，列出缺口并继续补齐测试与证据
- `blocked` → 提示"任务被阻塞"，列出 Notes 中的阻塞原因，结束

**#NOTES 检查**：扫描该子任务段落全文（Description、Checklist 等）
- 如果存在 `#NOTES` 标记，说明用户 review 时留下了未讨论的问题，拒绝启动
- 输出：`前置检查失败：以下 #NOTES 未解决\n- 密码加密存储  #NOTES 用 bcrypt 还是 argon2？\n- ...\n请先运行 cf-task-note <file> TASK-xxx 讨论并解决`

**依赖检查**：读取 `Depends` 字段
- 对每个依赖的 TASK-ID，在同文件中查找其 Status
- 所有依赖必须为 `done`
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
2. 按行号范围读取详设文档的对应章节（使用 offset/limit 参数）
3. 将读取的章节内容作为编码上下文，与 Checklist 一起指导实现
4. 按 `Acceptance-Refs` 精确读取验收场景及其关联 RULE/RISK；不得只依赖摘要，也不得遗漏场景的测试层级、关键真实边界和预期结果

示例：Source 为 `docs/auth.md#§3.2 API 接口(L111-L155), docs/auth.md#§3.5 错误码(L201-L220)`
→ 读取 `docs/auth.md` offset=111 limit=45
→ 读取 `docs/auth.md` offset=201 limit=20

### 3. 激活并准备验收测试

在改状态或生产代码前，顺序固定且不得跳步：

1. 调用 `cf_spec_context.py refresh --task-dir ...`，执行 Start Gate；stale/pending/conflict 或依赖未闭合均不得继续。
2. 重新读取 refresh 后的 Context hash，再调用 `cf_spec_context.py active start`，传 task/context hash 和逐路径确认的 pre-existing ownership；已有/损坏 marker、未归属 diff 或 hash 不一致立即阻断。禁止先 start 再 refresh，避免 active marker 在编码前自行漂移。
3. 调用 `cf_spec_session.py`，只根据当前 TASK 的 `Spec-Refs`、Source 与 Acceptance Contract 覆盖写入 `_session/task-<name>.md`。禁止重新 catalog 或猜测规则。
4. 只有前三步全部成功，才用 apply_patch 更新子任务 Status 为 `in-progress`、追加 started log 并更新文件头日期。
5. 在修改任何生产代码前，为每个 Acceptance-Ref 填写测试文件、包含场景 ID 的测试用例名和可单独执行的命令
6. 先编写验收测试。E2E 测试必须经过契约声明的真实边界，不得用 mock 绕过 Store、Resolver、Builder、Renderer、Browser 等指定组件
7. 新功能或缺陷修复先执行一次测试并记录 RED：失败命令、失败用例和与预期缺陷对应的失败原因。纯重构或已有行为补测无法 RED 时，记录原因，不得伪造失败

RED 证据写入 `Acceptance Evidence`：

```markdown
| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: generation 未递增 | pending | pending | real Store + Renderer fixture | test-written |
```

### 3.1 实现与逐项更新

1. RED 证据就绪后，结合详设上下文、Acceptance Contract 与 Checklist 修改生产代码
2. 每完成一个 checklist 项，用 apply_patch 将 `- [ ]` 改为 `- [x]`
3. 如果实现中发现必须改变测试层级或真实边界，停止编码并记录 `#NOTES`，经用户确认并同步 design 后才能继续；agent 不得自行降级

### 3.2 GREEN 与验收证据

1. 执行每个契约中的验收命令，再执行受影响范围的回归测试
2. 对每个预期结果记录对应的测试断言位置，并指出 fixture/构造路径如何证明关键边界使用真实组件
3. 将 `Acceptance Contract` 行状态改为 `verified`，将 `Acceptance Evidence` 补齐 GREEN、断言位置和边界证据
4. 负责该场景的任务验证完成后，将全局 `Acceptance Coverage` 对应行改为 `verified`
5. 测试文件存在但未被测试框架收集、命令未实际执行、只有场景 ID 没有关键断言，都视为未验证

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
- 每个 Acceptance-Ref 在契约、证据和全局覆盖表中均为 `verified`，不存在 `planned` / `pending` / `TBD`
- 测试层级未低于 design，关键真实边界没有被 mock 绕过
- 每个预期结果都有具体断言位置，验收命令和回归测试均已实际通过
- `manual` 场景已有用户确认和可复核记录

满足后：
1. 用 apply_patch 更新 Status 为 `done`
2. 在 `### Log` 追加：`- [<当前日期>] completed (done)`
3. 更新文件头 `Updated` 日期
4. 输出：`TASK-xxx 已完成`

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

  运行 cf-learn --map 可自动更新导航地图。
```

如果无需同步，跳过此步骤，不输出任何提示。

> 注：此检查是轻量级的建议，不阻塞流程。完整的三维校验在 archive 阶段执行。

## 整文件模式

### 1. 扫描所有子任务

读取整个 task 文件，提取所有 `## TASK-xxx` 段落的 ID、Status、Depends。

### 2. 加载详设文档

1. 读取文件头的 `Source` 字段，提取设计文档路径（文件头 Source 只有路径，无行号范围）
2. 读取详设文档作为全局上下文
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

开始执行...
```

### 4. 按序执行

对每个可激活的子任务，执行单任务模式的步骤 3-4，包括先写验收测试、RED、实现、GREEN 和证据核对（详设已在步骤 2 加载，无需重复读取）。

完成一个子任务后，检查是否解锁了新的子任务（依赖已满足），如果是则继续执行。

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

  运行 cf-learn --map 可自动更新导航地图。
```
