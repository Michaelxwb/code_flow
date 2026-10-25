---
description: Run layered verification or full requirement verification, including deferred E2E
globs: []
---

# cf-task:verify-e2e


## 验证子动作（0.8）

- `code-flow task verify --checks` — 等价于 `--layers validators`，是 `cf-validate` 的 0.8 入口。
- `code-flow task verify-e2e --checks` 同样只跑 validators；需要包含 heavy validator 时显式指定 `--profile full`。仅 validators 可在任务进行中运行，使用 active TASK 基线以来的变更，不推进任务状态。
- `cf-validate` 保留为兼容别名，0.9.0 移除。

执行需求目录下被延迟的 E2E 验收场景。

## 使用场景

本命令是**需求级终验**入口，在所有子任务的 functional 测试通过后统一执行：

1. **全量 verifier**：需求目录全部 task context 绑定的 required rules（code 层被任务延后的 `deferred_to_review` + `stage: review` 重型验证），按 spec/rule 去重全量执行一次，证据写回全部相关 context；输出 `executed` / `reused` / `failed` 计数。
2. **E2E 验收场景**：依赖外部环境（数据库、API、浏览器等）、编码阶段标记 `e2e_deferred` 的场景；已通过且工作树内容指纹未变的场景跨运行复用（不重复执行 E2E），内容变化/失败自动重跑，`code-flow acceptance run --no-cache` 可强制全量。
3. **全量 validation**：执行 `validation.yml` 全部 validator（含 `heavy: true` 全量套件/构建/E2E）；结果按工作树内容指纹缓存，归档复验命中即复用、不重复执行，`code-flow validate --no-cache` 强制重跑。

失败不写 verified、不反转已 done 的任务状态；归档前必须 `decision=pass`。未声明 review verifier 且无 E2E 场景时为空操作（`reason=nothing_to_verify`）。

> 0.8 分层入口：`code-flow task verify --layers validators,review,e2e --profile smoke|changed|full`。每层独立返回 `decision/executed/reused/failed/env_blocked/incomplete`，`profile` 默认 `changed`，`full` 必须显式；`task verify-e2e` 保留为兼容别名（全层 + full）。
>
> E2E 也按范围执行：`profile=changed` 只跑 `trigger_paths` 命中当前 diff 的 E2E，没有 `trigger_paths` 的 smoke E2E 不会在 changed 中顺跑；`profile=smoke` 只跑标记 `smoke` / `profile=smoke` 的 E2E（旧计划没有 smoke 标记时才回退全量 E2E）。不要把全量 E2E 当成每个小改动的默认门禁。

## 调用方式

```
/cf-task:verify-e2e <需求目录>
```

## 执行步骤

### 1. 检查前置条件

确认需求目录下所有子任务状态为 `done`（实现完成）或 `verified`（终验已闭环）：

```bash
rg "^- \*\*Status\*\*:" <需求目录>/*.md
```

本步骤只适用于包含 review/e2e 的需求验证。如有 `in-progress` 或 `blocked` 任务，先完成任务；仅 `--checks` / `--layers validators` 不要求任务 done，但仍校验 active Context 与需求身份。

### 2. 检查环境依赖

读取所选 checks 的 `env`、`env_scope`、`preflight` 声明。运行时在实际执行 check 前自动运行 preflight；已有有效证据时允许复用。不要从 `boundary` 猜测端口、数据库或驱动，也不要固定询问环境是否就绪。

收到 `env_blocked` 时，展示 `env_blocked_details` 中的 check ID、owner、失败的 preflight 命令、退出码和输出。根据真实失败修复可处理的本地问题；只有缺少外部配置、需要用户启动外部环境或涉及权限时请求用户输入。未声明 preflight 的检查仍按真实执行结果判断，不能自报环境已通过。

### 3. 执行 E2E 场景

用户请求需求级终验时，执行：

```bash
code-flow task verify \
  --task-dir "<需求目录>" --root "$PWD" \
  --layers validators,review,e2e --profile full --json
```

日常增量验证使用 `--profile changed`，明确只跑 smoke 时使用 `--profile smoke`；不要把增量请求升级成全量。`code-flow task verify-e2e` 保留为默认全层 full 的兼容入口。仅检查代码时使用 `code-flow task verify --checks --task-dir "<需求目录>" --root "$PWD" --json`。

全量终验重新检查所有 TASK、锁定 manifest 与 functional/manual 最新证据，执行全量 validation（含 heavy）和 code+review verifier（含 deferred 项）。runner 按范围执行 acceptance：仅 E2E 的路径使用 `--only-e2e`，full 或 functional 证据过期时同时复验所需 functional。只有全层 full 通过才将任务提升为 verified；单层、changed、smoke 通过均不推进状态。不得手动改状态。

### 4. 人工验收确认（manual_confirmation_required）

需求中的 manual 验收默认落 review 层，编码阶段不逐任务打断，统一在这里确认。`verify-e2e` 返回 `reason=manual_confirmation_required` 时：

1. 向用户完整展示 `manual_rules`（spec 规则、checklist、owner）与 `manual_scenarios`（场景 ID、真实边界），一次性请求确认；用户只确认部分时记录未确认的 ref/id。
2. 用户明确回复后执行（`--confirmed-by` 必须是用户身份，Agent 不得代确认；`--source` 填写用户回复原文）：

```bash
code-flow task confirm-manual \
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
  "layers": {
    "e2e": {
      "decision": "block",
      "checks": [{"id": "CHK-B", "status": "failed", "scenarios": ["E-02"]}]
    }
  }
}
```

- `decision=pass`：报告实际 `selected_layers`、`profile`、执行与复用计数，不将部分范围通过报告为全量终验完成
- `decision=block`：列出失败层、场景 ID 与 check ID，从 `check_results` 或 `env_blocked_details` 展示对应命令、退出码和错误输出
- `reason=manual_confirmation_required`：先按「人工验收确认」章节取得用户确认并执行 `confirm-manual`，再重跑本命令

### 6. 更新任务状态

全层 full 通过后确认运行时已将任务 Status 更新为 `verified`，并保留原契约与运行历史。其他验证范围保留原状态。无需再次编辑状态。

## 失败处理

E2E 失败时：

1. 显示失败场景的完整命令和退出码
2. 提示查看 `.acceptance-manifest.json` 中的 `evidence` 字段
3. 修复可处理的问题后重跑所选范围；缺少用户输入时报告具体阻塞，不自动修改任务状态

## 示例

```
/cf-task:verify-e2e .code-flow/tasks/2026-03-15/auth-module

> 检查子任务状态... 所有任务已完成
> 
> 按 checks 声明执行 preflight... 通过
> 
> 执行 E2E 场景...
>   ✓ E-01: 用户登录流程 (1.2s)
>   ✓ E-02: 权限验证链路 (0.8s)
> 
> E2E 验收完成！2/2 场景通过
> 已更新任务状态为 verified
```

<!-- code-flow:runtime-commands start -->

运行时命令示例（由命令契约生成；实际参数见各命令 --help）：

```bash
code-flow task verify --task-dir "<需求目录>" --layers validators,review,e2e --profile changed --root "$PWD" --json
code-flow task verify-e2e --task-dir "<需求目录>" --root "$PWD" --json
code-flow task confirm-manual --help
code-flow acceptance run --manifest "<需求目录>/.acceptance-manifest.json" --root "$PWD" --write-evidence
code-flow validate --root "$PWD" --json
```

<!-- code-flow:runtime-commands end -->
