---
name: cf-task-verify-e2e
description: Execute deferred E2E scenarios after all functional tests pass
---

## 使用场景

本命令是**需求级终验**入口，在所有子任务的 functional 测试通过后统一执行：

1. **全量 verifier**：需求目录全部 task context 绑定的 required rules（code 层被任务延后的 `deferred_to_review` + `stage: review` 重型验证），按 spec/rule 去重全量执行一次，证据写回全部相关 context；输出 `executed` / `reused` / `failed` 计数。
2. **E2E 验收场景**：依赖外部环境（数据库、API、浏览器等）、编码阶段标记 `e2e_deferred` 的场景。
3. **全量 validation**：执行 `validation.yml` 全部 validator（含 `heavy: true` 全量套件/构建/E2E）；结果按工作树内容指纹缓存，归档复验命中即复用、不重复执行。

失败不写 verified、不反转已 done 的任务状态；归档前必须 `decision=pass`。未声明 review verifier 且无 E2E 场景时为空操作（`reason=nothing_to_verify`）。

## 调用方式

```
cf-task-verify-e2e <需求目录>
```

## 执行步骤

### 1. 检查前置条件

确认需求目录下所有子任务状态为 `done`（实现完成）或 `verified`（终验已闭环）：

```bash
rg "^- \*\*Status\*\*:" <需求目录>/*.md
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
python3 .code-flow/scripts/cf_task_workflow.py verify-e2e \
  --task-dir "<需求目录>" --root "$PWD" --json
```

该入口是需求级全量终验：重新检查所有 TASK，锁定 manifest 与 functional/manual 最新证据，执行全量 validation（含 heavy），全量补跑 code+review 两层 verifier（含任务层 deferred 项），并以 `--only-e2e` 调用 runner 跑 E2E；只有全通过才把任务提升为 verified。不得手动改状态。

### 4. 人工验收确认（manual_confirmation_required）

需求中的 manual 验收默认落 review 层，编码阶段不逐任务打断，统一在这里确认。`verify-e2e` 返回 `reason=manual_confirmation_required` 时：

1. 向用户完整展示 `manual_rules`（spec 规则、checklist、owner）与 `manual_scenarios`（场景 ID、真实边界），一次性请求确认；用户只确认部分时记录未确认的 ref/id。
2. 用户明确回复后执行（`--confirmed-by` 必须是用户身份，Agent 不得代确认；`--source` 填写用户回复原文）：

```bash
python3 .code-flow/scripts/cf_task_workflow.py confirm-manual \
  --task-dir "<需求目录>" --root "$PWD" \
  --confirmed-by "user:<用户>" --source "<用户回复原文>" --json
```

部分确认时追加 `--refs <spec#RULE,...>` 与/或 `--scenarios <S-01,...>`。
3. 重跑 `verify-e2e`；全部通过后任务才提升为 `verified`。

> 显式声明 `stage: code` 的 manual 规则仍在任务 Done Gate 逐个确认，属于有意保留的强门禁。

### 5. 报告结果

解析执行结果：

```json
{
  "decision": "block",
  "results": [
    {"id": "E-01", "kind": "e2e", "status": "passed"},
    {"id": "E-02", "kind": "e2e", "status": "failed", "exit_code": 1}
  ]
}
```

- `decision=pass`：所有 E2E 场景通过，提示"E2E 验收完成"
- `decision=block`：有失败场景，列出失败的场景 ID 和错误信息
- `reason=manual_confirmation_required`：先按「人工验收确认」章节取得用户确认并执行 `confirm-manual`，再重跑本命令

### 6. 更新任务状态

确认命令已将需求目录下所有任务 Status 更新为 `verified`，并保留原契约与运行历史。无需再次编辑状态。

## 失败处理

E2E 失败时：

1. 显示失败场景的完整命令和退出码
2. 提示查看 `.acceptance-manifest.json` 中的 `evidence` 字段
3. 不自动修改任务状态，等待用户修复后重新执行

## 示例

```
cf-task-verify-e2e .code-flow/tasks/2026-03-15/auth-module

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
