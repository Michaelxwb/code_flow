---
name: cf-task-start
description: Activate a subtask and begin coding. Runs pre-checks (status, #NOTES, dependencies), loads design doc context by source reference, executes checklist items, and marks done when all items complete. Use when starting or continuing implementation work on a task.
---

## 输入

- `cf-task-start <file> TASK-001` — 激活指定文件中的单个子任务
- `cf-task-start <file>` — 激活文件内所有可执行的 draft 子任务

其中 `<file>` 为 `.code-flow/tasks/` 下的文件名，可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 单任务模式

### 1. 前置检查

用 Read 读取任务文件，定位 `## TASK-xxx` 段落：

**状态检查**：Status 必须为 `draft`。若为其他状态：
- `in-progress` → 提示"任务已在进行中，继续编码"（不阻塞，直接跳到步骤 2）
- `done` → 提示"任务已完成"，结束
- `blocked` → 提示"任务被阻塞"，列出 Notes 中的阻塞原因，结束

**#NOTES 检查**：扫描该子任务段落全文（Description、Checklist 等）
- 如果存在 `#NOTES` 标记，说明用户 review 时留下了未讨论的问题，拒绝启动
- 输出：`前置检查失败：以下 #NOTES 未解决\n请先运行 cf-task-note <file> TASK-xxx 讨论并解决`

**依赖检查**：读取 `Depends` 字段
- 对每个依赖的 TASK-ID，在同文件中查找其 Status
- 所有依赖必须为 `done`
- 未满足 → 输出：`前置检查失败：以下依赖未完成`

### 2. 加载详设上下文

前置检查通过后，**编码前先加载关联的详设文档章节**：

1. 读取子任务的 `Source` 字段，解析章节引用
   - 格式：`docs/xxx.md#§3.1 数据模型(L83-L110)`
   - 提取：文件路径 + 行号范围
2. 用 Read 按行号范围读取详设文档的对应章节（使用 offset/limit 参数）
3. 将读取的章节内容作为编码上下文，与 Checklist 一起指导实现

### 3. 激活并编码

1. 用 Edit 更新子任务 Status 为 `in-progress`
2. 在 `### Log` 追加：`- [<当前日期>] started (in-progress)`
3. 更新文件头 `Updated` 日期
4. 结合详设上下文 + Checklist，逐项执行编码工作
5. 每完成一个 checklist 项 → 用 Edit 将 `- [ ]` 改为 `- [x]`

### 4. 自动完成

当所有 checklist 项都勾选为 `[x]` 后：
1. 用 Edit 更新 Status 为 `done`
2. 在 `### Log` 追加：`- [<当前日期>] completed (done)`
3. 更新文件头 `Updated` 日期
4. 输出：`TASK-xxx 已完成`

### 5. 文档同步检查

子任务完成后，轻量检查本次编码是否引入了需要同步到 specs 或导航地图的内容：

1. 回顾本次编码的变更（新增/修改了哪些文件和模式）
2. 快速对照 `.code-flow/specs/` 下对应领域的规范文件和 `<map-file>.md`
3. 如果发现新增了 specs 未记录的模式或新增了目录，输出同步提示

如果无需同步，跳过此步骤，不输出任何提示。

## 整文件模式

### 1. 扫描所有子任务

用 Read 读取整个 task 文件，提取所有 `## TASK-xxx` 段落的 ID、Status、Depends。

### 2. 加载详设文档

1. 读取文件头的 `Source` 字段，提取设计文档路径
2. 用 Read 加载详设文档作为全局上下文
   - 如果文档 ≤ 500 行：全文加载
   - 如果文档 > 500 行：仅加载各子任务 Source 中引用的章节（合并行号范围，去重后按 offset/limit 加载）

### 3. 构建执行计划

按依赖关系拓扑排序：
1. 筛选所有 `draft` 状态的子任务
2. 按依赖关系排序：先无依赖的，再逐层解锁
3. 逐个检查 Notes 前置条件

输出执行计划供用户确认。

### 4. 按序执行

对每个可激活的子任务，执行单任务模式的步骤 3-4（详设已在步骤 2 加载，无需重复读取）。

完成一个子任务后，检查是否解锁了新的子任务（依赖已满足），如果是则继续执行。

### 5. 输出摘要与文档同步检查

所有子任务执行完毕后，输出执行摘要，并对本轮所有完成的子任务统一执行一次文档同步检查。
