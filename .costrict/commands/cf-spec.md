# cf-spec

管理 schema v1 Spec Context 与一次性迁移。用法：

- `cf-spec migrate --plan <migration-plan.yml>`
- `cf-spec context [需求目录]`
- `cf-spec refresh [需求目录]`
- `cf-spec doctor [需求目录]`

## 通用硬门禁

1. 先读取 `.code-flow/config.yml`；`spec_workflow.schema_version` 不是 `1` 时，只有 `migrate --plan` 可继续。
2. 不存在有效 Context 时，不得伪造 binding、Rule 状态、Evidence 或用户确认。
3. stdout JSON 由 `cf_*.py` 产生；本命令不得手写成功结果。

## migrate --plan

只处理 `code-flow migrate --spec-workflow --prepare` 已产生的 prepared plan：

1. 校验 plan 位于当前项目 `.code-flow/migrations/<id>/`，状态为 `prepared_blocked` 或 `prepared`，source hashes 未漂移。
2. 逐条展示 `unresolved` 的来源、候选和影响；读取关联 Spec 与活跃需求文档后给出建议。
3. 每项必须由用户明确选择。写入 `confirmed_by`、`confirmed_at`、`source`、`reason`；Agent 不能代确认，不能批量 N/A。
4. 只修改 prepared plan，不修改项目目标、backup、staging、journal 或 `.version`。
5. unresolved 清零后提示执行：
   `code-flow migrate --spec-workflow --apply --plan <migration-plan.yml>`

## context

定位显式需求目录；省略时只可使用有效 `.active-task.json` 的 `task_dir`。

1. 读取并展示 `spec-context.yml` 的 bindings、Rule stage status、artifact refs、Evidence 与 drift。
2. 执行：
   `python3 .code-flow/scripts/cf_spec_context.py validate --task-dir <目录> --json`
3. Context 缺失、schema/hash 无效时 fail-closed，不回退 Catalog。

## refresh

执行：

`python3 .code-flow/scripts/cf_spec_context.py refresh --task-dir <目录> --root "$PWD" --json`

- changed required Rule 标为 stale，关联 stage Gate 必须阻断。
- missing/conflict 不自动降级；回 Align 或 Plan 更新承接后再继续。
- refresh 不替用户做 N/A/waiver 决策。

## doctor

1. 校验 config schema、active marker、lock、Context hash、task/status、migration journal 和 legacy residue。
2. active marker 存在时执行 `cf_spec_context.py active doctor`，传入可证明的 Context hash；无法证明时保持 `recovery_required`。
3. 输出明确修复命令。不得删除损坏 marker、越过 required Gate 或静默切换到无任务模式。
