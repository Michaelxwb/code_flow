---
description: Execute deferred E2E scenarios after all functional tests pass
globs: []
---

# cf-task:verify-e2e

执行需求目录下被延迟的 E2E 验收场景。

## 使用场景

E2E 测试依赖外部环境（数据库、API、浏览器等），在编码阶段默认跳过（状态 `e2e_deferred`）。当所有子任务的 functional 测试通过后，使用此命令统一执行 E2E 验收。

## 调用方式

```
/cf-task:verify-e2e <需求目录>
```

## 执行步骤

### 1. 检查前置条件

确认需求目录下所有子任务状态为 `done` 或 `verified`：

```bash
rg "^Status:" <需求目录>/*.md
```

如有 `in-progress` 或 `blocked` 任务，提示用户先完成。

### 2. 检查环境依赖

读取 `.acceptance-manifest.json` 中的 E2E 场景，提取所需的外部依赖（从 `boundary` 字段推断）：

- `HTTP API` → 提示确认 API 服务运行中
- `Browser` → 提示确认浏览器驱动已安装
- `Database` → 提示确认测试数据库可访问

显示清单并询问：

```
E2E 场景需要以下环境：
  - 本地 API 服务 (http://localhost:3000)
  - PostgreSQL 测试数据库
  - Chrome WebDriver

环境已就绪？(y/N)
```

### 3. 执行 E2E 场景

用户确认后，执行：

```bash
python3 .code-flow/scripts/cf_acceptance_runner.py \
  --manifest <需求目录>/.acceptance-manifest.json \
  --root . \
  --include-e2e \
  --write-evidence
```

### 4. 报告结果

解析执行结果：

```json
{
  "decision": "pass",
  "results": [
    {"id": "E-01", "kind": "e2e", "status": "passed"},
    {"id": "E-02", "kind": "e2e", "status": "failed", "exit_code": 1}
  ]
}
```

- `decision=pass`：所有 E2E 场景通过，提示"E2E 验收完成"
- `decision=block`：有失败场景，列出失败的场景 ID 和错误信息

### 5. 更新任务状态

所有 E2E 通过后，将需求目录下的任务状态更新为 `verified`（如果当前是 `done`）。

## 失败处理

E2E 失败时：

1. 显示失败场景的完整命令和退出码
2. 提示查看 `.acceptance-manifest.json` 中的 `evidence` 字段
3. 不自动修改任务状态，等待用户修复后重新执行

## 示例

```
/cf-task:verify-e2e .code-flow/tasks/2026-03-15/auth-module

> 检查子任务状态... 所有任务已完成
> 
> E2E 场景需要以下环境：
>   - 本地 API 服务 (http://localhost:3000)
>   - PostgreSQL 测试数据库 (postgresql://localhost:5432/test)
> 
> 环境已就绪？(y/N) y
> 
> 执行 E2E 场景...
>   ✓ E-01: 用户登录流程 (1.2s)
>   ✓ E-02: 权限验证链路 (0.8s)
> 
> E2E 验收完成！2/2 场景通过
> 已更新任务状态为 verified
```
