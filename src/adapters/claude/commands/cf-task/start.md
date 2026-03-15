# cf-task:start

激活子任务并开始编码。支持单任务模式和整文件模式。

## 输入

- `/cf-task:start <file> TASK-001` — 激活指定文件中的单个子任务
- `/cf-task:start <file>` — 激活文件内所有可执行的 draft 子任务

其中 `<file>` 为 `.code-flow/tasks/` 下的文件名，可省略路径前缀和 `.md` 后缀。

示例：
- `/cf-task:start auth-module TASK-002`
- `/cf-task:start auth-module`

## 单任务模式

### 1. 前置检查

用 Read 读取 `.code-flow/tasks/<file>.md`，定位 `## TASK-xxx` 段落：

**状态检查**：Status 必须为 `draft`。若为其他状态：
- `in-progress` → 提示"任务已在进行中，继续编码"（不阻塞，直接跳到步骤 2）
- `done` → 提示"任务已完成"，结束
- `blocked` → 提示"任务被阻塞"，列出 Notes 中的阻塞原因，结束

**Notes 检查**：扫描 `### Notes` 区域
- 如果存在 `[NOTE-n]` 格式的批注且未标记 `[RESOLVED]`，则拒绝启动
- 输出：`前置检查失败：以下 Notes 未解决\n- [NOTE-1] xxx\n- [NOTE-2] xxx\n请先解决后重试，或用 /cf-task:note 标记为 [RESOLVED]`

**依赖检查**：读取 `Depends` 字段
- 对每个依赖的 TASK-ID，在同文件中查找其 Status
- 所有依赖必须为 `done`
- 未满足 → 输出：`前置检查失败：以下依赖未完成\n- TASK-001: in-progress\n- TASK-003: draft`

### 2. 激活并编码

前置检查通过后：
1. 用 Edit 更新子任务 Status 为 `in-progress`
2. 在 `### Log` 追加：`- [<当前日期>] started (in-progress)`
3. 更新文件头 `Updated` 日期
4. 读取 `### Checklist`，逐项执行编码工作
5. 每完成一个 checklist 项 → 用 Edit 将 `- [ ]` 改为 `- [x]`

### 3. 自动完成

当所有 checklist 项都勾选为 `[x]` 后：
1. 用 Edit 更新 Status 为 `done`
2. 在 `### Log` 追加：`- [<当前日期>] completed (done)`
3. 更新文件头 `Updated` 日期
4. 输出：`TASK-xxx 已完成 ✓`

## 整文件模式

### 1. 扫描所有子任务

用 Read 读取整个 task 文件，提取所有 `## TASK-xxx` 段落的 ID、Status、Depends。

### 2. 构建执行计划

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

### 3. 按序执行

对每个可激活的子任务，执行单任务模式的步骤 2-3。

完成一个子任务后，检查是否解锁了新的子任务（依赖已满足），如果是则继续执行。

### 4. 输出摘要

```
执行完成：
  - 完成: TASK-001, TASK-003, TASK-002
  - 跳过: TASK-004 (Notes 未解决)
  - 剩余 draft: 1 个
```
