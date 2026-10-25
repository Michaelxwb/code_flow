# 0.8.0 运行时与命令面迁移

0.8.0 把用户命令面从 16 条收敛到 11 条，并把执行、证据与状态机升级为 manifest v3 + evidence sidecar。旧命令文件不删除，保留一个 minor 的兼容别名（0.9.0 移除）。

本文包括仓库 0.8.0 的验收契约硬化；npm 发布状态独立，先核对实际安装版本。完整字段、可复制示例与错误处理见[可执行验收契约](../acceptance-contract.md)。

## 1. 升级前置

- CLI 与项目内运行时版本必须可比较：安装版本高于 CLI 时迁移会拒绝降级，先更新全局包。
- 迁移前确认工作区干净（至少 `.code-flow/` 之外无未提交改动）；迁移会备份 `.code-flow/`。
- 需要 Python 3.9+ 与 pyyaml；0.8 没有新增 npm 运行时依赖，`package.json` 仍只有 `@ccusage/codex`。

```bash
code-flow --version
npm view @michaelxwb/code-flow dist-tags --json
```

确认注册表已有所需版本后再安装。需要尚未发布的仓库修复时，按 [README](../../README.md#升级)构建并安装本地 tarball；不要用较旧的 latest 覆盖本地版本。CLI 更新后进入目标项目：

```bash
cd your-project
code-flow migrate --runtime --dry-run
```

`--dry-run` 在 `.code-flow/migrations/runtime-<id>/` 构建并校验产物，只写预览 journal，不改目标文件。确认 `status=previewed` 与 `files` 清单后再执行：

```bash
code-flow migrate --runtime --apply
```

apply 使用同一事务：备份 → staging → 校验 → journal → 写目标 → `.version` 最后写。返回 `committed` 后再在 Codex `/hooks` 中信任变更定义。

## 2. 命令面变化（16 → 11）

| 0.7 命令 | 0.8 状态 | 0.8 用法 |
|----------|----------|----------|
| `cf-init` | 用户命令 | `/cf-init` |
| `cf-learn` | 用户命令 | `/cf-learn` |
| `cf-spec` | 用户命令 | 新增 `code-flow spec doctor` 运行时入口 |
| `cf-stats` | 用户命令 | `/cf-stats --audit` |
| `cf-task:prd` | 用户命令 | `/cf-task:prd` |
| `cf-task:align` | 用户命令 | `/cf-task:align` |
| `cf-task:plan` | 用户命令 | 默认能力级拆解与预算门禁 |
| `cf-task:start` | 用户命令 | `/cf-task:start` |
| `cf-task:status` | 用户命令 | 吸收 `--notes` / `--block` / `--graph` 子动作 |
| `cf-task:archive` | 用户命令 | `/cf-task:archive` |
| `cf-task:verify-e2e` | 用户命令 | `code-flow task verify` 的兼容别名 |
| `cf-task:note` | 别名 | `/cf-task:status --notes` |
| `cf-task:block` | 别名 | `/cf-task:status --block` |
| `cf-task:graph` | 别名 | `/cf-task:status --graph` |
| `cf-validate` | 别名 | `code-flow task verify --checks`（等价 `--layers validators`） |
| `cf-sync` | internal | 开发/发布维护专用，不属于用户安装面 |

命令清单的唯一权威源是 `src/adapters/commands.json`：每个条目声明 `kind=user|alias|internal`、平台文件路径与别名参数。四平台（Claude Code / Codex / Costrict / OpenCode）的命令文件集必须与该目录一致；内容 canonical 源仍是 Claude 命令，其余平台只允许绑定 token 差异。`tests/test_adapter_parity.py` 与 `tests/test_command_surface.py` 守住这条约束。

兼容窗口：0.8.x 期间旧别名文件保留且行为不变；0.9.0 删除别名文件，调用方需提前迁移到新入口。

## 3. 状态机（0.7 → 0.8）

0.8 的 TASK 状态由证据推导，不再接受手写 terminal 状态：

| 状态 | 含义 |
|------|------|
| `done` | 本任务 required code check 全部 verified |
| `provisional` | 任一 required code check 为 deferred / env_blocked / incomplete；真实 failed 必须 block |
| `verified` | 需求级 Gate 通过，且证据 input_hash 与当前工作区匹配 |
| `deferred` | 仅允许 review-stage / heavy 检查延后；预算导致的延后不是合法 deferral |

规则：

- required code check 未全部 verified 时，手写 `done`/`verified` 会被拒绝并报告冲突。
- `env_blocked` 是环境失败，不是产品失败：不写 verified，也不计产品 failed。
- 只有 `--profile full` 且全部层通过才把需求提升为 `verified`；`smoke`/`changed` 不会伪造终态。
- `task finish --batch TASK-001,TASK-002` 与 `task finish --capability <名称>` 在一次执行内复用共享 check，失败任务不会污染已通过任务。

## 4. Manifest v3

`.acceptance-manifest.json` 从 schema 2 迁移到 schema 3：

- `checks[]`：可执行命令、cwd、timeout、env/env_scope/preflight/parallel_safe、inputs，以及 suite/test_ids/markers/collect 登记；按 `CHK-*` 去重。
- `scenarios[]`：保留 ID / owner / assertions 和场景语义，通过 `checks` 绑定全部成员；兼容旧 `check`，同一 check 可被多个 scenario 引用。
- schema 2 输入按 `command + cwd + timeout` 自动归并为 checks，读取时返回 `schema2_compat`；旧证据仍可读。
- check 或 scenario 映射冲突 fail closed，列出冲突字段，不静默覆盖。

运行时迁移更新受管理脚本和平台入口，不代写需求场景与测试登记。已有需求按下方步骤检查并重新锁定 manifest；一个场景的全部 checks 都必须绑定并各自保留证据。

## 5. Evidence sidecar

- 证据集中到 git common dir：`.git/code-flow/evidence/`（非 git 项目回落到 `.code-flow/evidence/`）。
- 文件按 `run_id` 唯一，原子写（临时文件 + `os.replace`），同一 run_id 幂等去重。
- `spec-context.yml` 只保留每个 rule 的最新状态；历史压缩进 sidecar（上限 200 条），不再把全部 evidence 塞进 Context。
- 重锁 plan 不清证据；旧 verified 在 input_hash 变化后降为 stale，而不是删除。
- CI 证据通过 `code-flow evidence import --format junit|playwright` 导入，校验 commit / run_url / exit_code / source=ci；无法映射的用例拒绝导入。
- 并行 worktree 共享 central evidence，worker 分支不提交证据文件；collect 只接受 done/verified，拒绝 provisional/blocked。

## 6. 验证与诊断

```bash
code-flow spec doctor --task-dir ".code-flow/tasks/<日期>/<需求>" --root "$PWD" --json
code-flow audit --task-dir ".code-flow/tasks/<日期>/<需求>" --json
code-flow task verify --task-dir ".code-flow/tasks/<日期>/<需求>" --checks --profile full --root "$PWD" --json
code-flow task verify --task-dir ".code-flow/tasks/<日期>/<需求>" --layers validators,review,e2e --profile full --root "$PWD" --json
```

`spec doctor` 只读诊断 config schema、active marker、Context hash、迁移 journal/lock、运行时 manifest 与 legacy residue，并检查未解决的 applied 引用、提示 Conventions 审查。顶层 decision 表示诊断健康，`readiness.plan/code/review` 分别表示阶段准备情况；应同时查看。阻断项按 `next` 修复，不能把健康通过当作阶段通过。

code/review 的 applied 引用不能替代执行证据。自动 verifier 能证明符合时无需另造用户 decision；规则确实不适用才用 not_applicable 与用户确认。`audit` 按每个 check 对账，A 的成功不能覆盖 B 的失败；缺部分 central evidence 时不借用场景汇总 pass。

### 重新锁定现有需求

1. 找到 canonical 场景源；没有时按 [Scenario-First 迁移说明](runtime-0.9.0.md)从完整旧定义生成草稿。只有引用的旧 design 不能回退为完整场景。
2. API/CLI/后台全链路改为 system/integration，同时移除 why_e2e；保留为 e2e 的场景必须有浏览器 env/组件和匹配 boundary。
3. 补齐具体 expected 与逐条 expected_refs；有条件预期声明前置条件。deferred 补 defer_reason、owner、target_phase。
4. 使用合法 env；数据库放在 components。设计声明实际 design_template，统一 FEAT/API/NFR 定义及功能到场景关系。
5. 生成 manifest，在对应 check 上登记 browser 套件、具体 test_ids、smoke/capacity markers 与 collect；执行 command 必须选中这些用例。延期执行不免除计划登记。
6. 执行以下门禁。更改登记配置或命令会使旧输入证明失效，按实际需要重跑受影响检查。

```bash
code-flow scenarios parse --file "<需求>.scenarios.md" --quality --json
code-flow design lint --file "<需求>.design.md" --scenarios-file "<需求>.scenarios.md" --json
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json" --scenarios-file "<需求>.scenarios.md"
# 补齐对应 check 登记后再运行
code-flow acceptance manifest --verify-plan --require-scenarios --task-dir "<需求目录>" --task-file "<任务文件>"
```

`--verify-plan` 始终执行完整检查，不能通过不传 `--require-scenarios` 绕过。旧文档可读与旧 evidence 可追溯不代表新计划自动通过。`--checks` 只跑开发期 validators、不推进终态；需求级 full 终验才证明完整范围。浏览器可运行数量来自实际收集，已执行结果仍来自有效运行证据。

## 7. 回滚

迁移 journal 保留在 `.code-flow/migrations/runtime-<id>/`，apply 返回的 `migration_id` 可直接回滚：

```bash
code-flow migrate --runtime --rollback runtime-<timestamp>-<pid>
```

- 回滚只恢复该事务写过的文件；迁移完成后再手工修改的文件会被检测并阻断，不会覆盖后续工作。
- `--dry-run` 产生的 `previewed` journal 也可回滚，用于清理预览目录。
- 进程中断后不要直接再次 apply：先按错误提示回滚未完成事务（`staging`/`applying`），`spec doctor` 会列出待恢复的 journal。
- 回滚后 `.version` 回到迁移前版本；如 CLI 已是 0.8.0，再次 `--apply` 即可重新升级。

## 8. 发布验收

0.8.0 发布前必须全绿：

```bash
python3 -m pytest -q tests/test_adapter_parity.py
python3 -m pytest -q tests/test_command_surface.py
node tests/test_cli_merge_helpers.js
node tests/test_spec_workflow_migrate.js
node src/cli.js sync check --root .
```
