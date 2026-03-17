# cf-task:start

激活子任务并开始编码。支持单任务模式和整文件模式。

## 输入

- `/cf-task:start <file> TASK-001` — 激活指定文件中的单个子任务
- `/cf-task:start <file>` — 激活文件内所有可执行的 draft 子任务

其中 `<file>` 为 `.code-flow/tasks/` 下的文件名，可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径，匹配第一个结果。

示例：
- `/cf-task:start auth-module TASK-002`
- `/cf-task:start auth-module`

## 单任务模式

### 1. 前置检查

用 Read 读取任务文件，定位 `## TASK-xxx` 段落：

**状态检查**：Status 必须为 `draft`。若为其他状态：
- `in-progress` → 提示"任务已在进行中，继续编码"（不阻塞，直接跳到步骤 2）
- `done` → 提示"任务已完成"，结束
- `blocked` → 提示"任务被阻塞"，列出 Notes 中的阻塞原因，结束

**#NOTES 检查**：扫描该子任务段落全文（Description、Checklist 等）
- 如果存在 `#NOTES` 标记，说明用户 review 时留下了未讨论的问题，拒绝启动
- 输出：`前置检查失败：以下 #NOTES 未解决\n- 密码加密存储  #NOTES 用 bcrypt 还是 argon2？\n- ...\n请先运行 /project:cf-task:note <file> TASK-xxx 讨论并解决`

**依赖检查**：读取 `Depends` 字段
- 对每个依赖的 TASK-ID，在同文件中查找其 Status
- 所有依赖必须为 `done`
- 未满足 → 输出：`前置检查失败：以下依赖未完成\n- TASK-001: in-progress\n- TASK-003: draft`

### 2. 加载详设上下文

前置检查通过后，**编码前先加载关联的详设文档章节**：

1. 读取子任务的 `Source` 字段，解析章节引用
   - 格式：`docs/xxx.md#§3.1 数据模型(L83-L110)`
   - 提取：文件路径 + 行号范围
2. 用 Read 按行号范围读取详设文档的对应章节（使用 offset/limit 参数）
3. 将读取的章节内容作为编码上下文，与 Checklist 一起指导实现

示例：Source 为 `docs/auth.md#§3.2 API 接口(L111-L155), docs/auth.md#§3.5 错误码(L201-L220)`
→ Read `docs/auth.md` offset=111 limit=45
→ Read `docs/auth.md` offset=201 limit=20

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

## 整文件模式

### 1. 扫描所有子任务

用 Read 读取整个 task 文件，提取所有 `## TASK-xxx` 段落的 ID、Status、Depends。

### 2. 加载详设文档

1. 读取文件头的 `Source` 字段，提取设计文档路径（文件头 Source 只有路径，无行号范围）
2. 用 Read 加载完整的详设文档作为全局上下文（不使用 offset/limit）

> 注：整文件模式加载完整详设（因为涉及所有子任务），单任务模式只加载子任务 Source 中引用的章节（节省 token）。

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
  - TASK-004: Notes 未解决 [NOTE-1]
  - TASK-005: 依赖 TASK-004 (blocked)

开始执行...
```

### 4. 按序执行

对每个可激活的子任务，执行单任务模式的步骤 3-4（详设已在步骤 2 加载，无需重复读取）。

完成一个子任务后，检查是否解锁了新的子任务（依赖已满足），如果是则继续执行。

### 5. 输出摘要

```
执行完成：
  - 完成: TASK-001, TASK-003, TASK-002
  - 跳过: TASK-004 (Notes 未解决)
  - 剩余 draft: 1 个
```
