# cf-task:archive

归档已完成的整个 task 文件。

## 输入

- `/cf-task:archive <file>` — 归档指定的 task 文件

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`（排除 `archived/`），匹配第一个结果。

## 执行步骤

### 1. 完成度检查

1. 用 Read 读取匹配到的 task 文件
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

### 2. 执行归档

所有子任务已完成：

1. 提取文件所在的日期目录名（如 `2026-03-15`）
2. 用 Bash 创建归档目录并移动文件：
   ```bash
   mkdir -p .code-flow/tasks/archived/<日期目录>
   mv .code-flow/tasks/<日期目录>/<file>.md .code-flow/tasks/archived/<日期目录>/
   ```
3. 如果原日期目录为空，删除空目录

### 3. 归档摘要

```
已归档: <file>.md → .code-flow/tasks/archived/<日期目录>/<file>.md

摘要:
  - 来源: docs/xxx设计说明书.md
  - 子任务数: N 个
  - 创建日期: 2026-03-15
  - 归档日期: 2026-03-20
  - 历时: 5 天
```
