# code-flow 仓库审计报告

本报告分析当前工作区的代码与命令契约，包括已有未提交的 `cf_spec_session.py` 空引用修复。审计覆盖 Node CLI、23 个 Python 脚本、Claude 侧 16 条命令、其他平台对应适配，以及现有测试。没有修改仓库文件；复现产生的数据位于隔离临时目录。

结论：当前实现已经有较好的 Spec 元数据、Context、迁移事务和测试基础，但还不能认定为“流程无缝、验收可靠、架构最优”。最需要修复的是验收范围、状态迁移和安装内容保护。小项目脚本延迟本身尚可，命令之间重复工作与状态不一致带来的返工更值得优先处理。

| 评估维度 | 判断 | 主要依据 |
|---|---|---|
| 执行速度与流畅度 | 小规模脚本可接受，完整流程存在明显摩擦 | 进程级 Hook 约 54–69ms；范围过宽、重复注入、重复运行验收、超时预算不统一 |
| 命令衔接 | 尚未闭合 | 任务切换丢上下文；E2E 与 done/verified 冲突；block/note/start 未统一操作运行状态 |
| 产出质量 | 模板要求较完整，机器保证不足 | 未配置验收命令仍 pass；Git 提交后漏检；验收证据残留 planned；新规范缺 schema 校验 |
| 架构 | 方向合理，职责和事实源需要收敛 | Markdown、Context、manifest、active marker 分别维护状态；适配器靠复制和不完整清单保持一致 |

## 验证范围和限制

本机环境为 macOS、Node v24.17.0、Python 3.9.6。执行结果：

- `python3 -m pytest -q tests --durations=20`：311 passed，9.81 秒。
- `node tests/test_cli_merge_helpers.js`：13 个检查通过。
- `node tests/test_spec_workflow_migrate.js`：6 个测试通过。
- `cf_sync.py check --verbose`：定义在 PAIRS 内的副本检查通过。
- 在临时 Git 仓库中复现下述安装、提交、验收、任务切换与路径问题。

上述测试成功只能证明现有断言通过。本次额外复现的缺陷没有被这些断言覆盖。没有实际驱动四种 AI 客户端完成一整轮 PRD → Archive，因而不把 Python 耗时当成 AI 命令的端到端耗时，也不据此保证 Windows 或客户端协议兼容性。

## 已确认的关键问题

### 1. P0：普通 init 会删除用户自有的 Claude skills

`removeLegacyClaudeSkills()` 对 `.claude/skills` 整个目录执行递归删除，`runInit()` 无条件调用它。既没有逐文件区分 code-flow 管理内容，也没有备份；它还会在其他平台的 init 中运行。

复现：临时项目预置 `.claude/skills/my-custom-skill/SKILL.md`，执行普通 `code-flow init --platform=claude`，退出码为 0，文件已不存在。这是实际的数据丢失风险，应在发布其他体验优化前修复。

建议使用受管理文件清单，只处理能够证明归属的旧文件；删除前提供迁移或备份机制。至少补“用户自建 skill 在 fresh/current/upgrade、跨平台 init 后均保留”的回归测试。

证据：[删除函数](/Users/jahan/workspace/code_flow/src/cli.js:370)、[无条件调用](/Users/jahan/workspace/code_flow/src/cli.js:692)。本次被删除的只是审计生成的临时测试文件，没有删除实际仓库的用户文件。

### 2. P1：任务中途 Git commit 后，Done Gate 会漏掉已提交代码

`current_owned_paths()` 只取启动前显式认领的路径与当前 `git status` 变更，并没有把启动时 HEAD 到当前 HEAD 的提交差异并入检查范围。对从干净工作区启动的任务，修改并提交后，这个集合可以变空。

复现同一份代码：

```text
src/app.py 包含禁止的 print
提交前：decision=block，files=[src/app.py]
git commit 后：decision=pass，files=[]，checked_files=0
```

这意味着“允许任务中途提交”的优化破坏了验收范围。建议把任务范围定义为启动基线之后的已提交、已暂存、未暂存和未跟踪变更的并集；不应在提交时丢失原始基线。测试需要覆盖多次提交、重命名、删除和任务间隔离。

证据：[范围计算](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_context.py:523)、[基线更新](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_context.py:493)、[空文件正则验收](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_verify.py:201)。

### 3. P1：验收清单没有命令也能通过，Plan 的产物未直接接上 Runner

`extract_manifest()` 从覆盖表提取 ID、来源、层级、边界、负责人和状态，不生成可执行 `command`。命令文档要求 AI 在 Acceptance Contract 填命令，但没有明确、统一的转换入口把这些命令同步进 manifest。

Runner 在所有场景都没有 command 时，把 `not_configured` 计入允许通过的状态；Done Gate 则在 `has_commands` 为假时完全跳过场景执行。

复现：包含两个 integration 场景的任务经 `write_manifest()` 生成清单，立即执行 Runner，得到两个 `not_configured` 和整体 `decision=pass`。这不能作为自动验收通过的依据。

建议将“草稿完整性检查”和“执行验收”分开。未配置自动场景必须阻断执行验收；Plan/Start 应有明确的命令注册步骤与 schema 检查，不能依赖 AI 在两份文件之间自行补齐。

证据：[清单生成](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_manifest.py:37)、[放行条件](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_runner.py:59)、[Done 跳过分支](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_task_runtime.py:189)。

### 4. P1：单个 TASK 的 Done 执行了整个需求的验收

`run_done_gate()` 没有按 active task ID 过滤 manifest；人工场景检查同样扫描整个需求。Spec verifier 也遍历整个 Context，`validate_stage()` 接收 `task_id` 却直接丢弃。

复现：TASK-001 的 S-01 已配置且执行成功，TASK-002 的 S-02 尚未配置；验收会因为后一个任务而 block。人工场景属于后续任务时也会提前阻断当前任务。

这同时影响速度和流程：早期任务需要等待后续任务，反复执行已完成场景；如果同一命令绑定多个场景，还会被重复运行。建议区分当前 TASK 验收与整个需求的最终验收，按唯一 owner 及必要依赖计算执行集合，并将同一命令的执行结果映射给多个场景。

证据：[Done Gate](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_task_runtime.py:179)、[忽略 task_id](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_gate.py:109)、[逐场景执行](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_runner.py:66)。

### 5. P1：切换 TASK 后，新的验收上下文会被去重掉

Prompt 和 PreTool 的去重键只有 Context hash。同一需求下两个 TASK 可以共享同一个 Context，但引用不同的验收场景。Router 的投影缓存知道 task_id，后续注入去重却不知道。

复现：同一会话先注入 TASK-001，完成并激活 TASK-002，保持 Context 不变。第二次 Prompt Hook 输出为空，没有 TASK-002 的 S-99 验收要求。

建议以 session、task_dir、task_id、Context identity 和当前 TASK 契约摘要共同决定注入版本。需要独立覆盖任务切换、同任务契约修改、会话切换及压缩恢复。

证据：[Prompt 去重](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_user_prompt_hook.py:135)、[PreTool 去重](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_pre_tool_hook.py:71)。

### 6. P1：Start 的硬门禁与命令文档承诺不一致

高层命令承诺拦截 blocked、未解决 Notes、依赖不满足、stale/pending/conflict。但 `_start_command()` 实际执行 refresh、manifest 检查、投影和 activation，没有验证任务状态、依赖、Notes，也没有在此处执行 Design/Plan Stage Gate。

复现：任务状态为 blocked，依赖不存在的 TASK-999，同时含未解决 `#NOTES`，调用 `cf_spec_context.py start` 仍返回 `ok=true`，marker 为 active。AI 层可能主动拦截，但这不构成脚本层的硬保证。

此外，start 文档的自动完成步骤只改 Markdown 状态，没有明确要求调用 `active complete`；block/note 也主要修改 Markdown。严格按这些步骤执行时，Markdown 与 marker 可能不同步，下一任务会遇到 `active_exists`。

建议让 start/block/resume/complete 全部调用统一状态迁移接口，并由该接口验证前置条件、同步产物和输出可执行的下一步。

证据：[Start 实现](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_context.py:1368)、[Start 契约](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/start.md:63)、[自动完成](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/start.md:104)、[Block 步骤](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/block.md:15)。

### 7. P1：E2E 延迟机制尚未贯通 start、verify 和 archive

目前存在四处明确冲突：

- Plan/Runner 允许 E2E 延迟，但 start 的自动完成条件仍要求每个场景全部 verified，不允许 pending。按 start 契约完成任务与“所有任务 done 后统一 E2E”互相制约。
- `verify-e2e` 将任务从 done 改成 verified；archive 和依赖检查只接受 done。
- `verify-e2e` 示例用 `rg '^Status:'` 读取状态，实际格式是 `- **Status**:`，该命令匹配不到任务状态。
- Claude、Costrict、OpenCode 有该命令，Codex skill 源缺少它。现有 parity 测试的固定列表也没有列入它。

另外，`--include-e2e` 表示“包含 E2E”，不是“仅运行 E2E”，因此复验时会重跑 functional 场景。

建议分开记录实现状态与验收状态，例如 task 的 done、场景的 pending/passed、需求的 verified。E2E 延迟必须显式反映在所有阶段的通过条件里，最终 archive 才要求完整验收。

证据：[Plan 延迟定义](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/plan.md:328)、[Start 条件](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/start.md:108)、[E2E 状态更新](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/verify-e2e.md:82)、[归档条件](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/archive.md:19)、[适配测试清单](/Users/jahan/workspace/code_flow/tests/test_adapter_parity.py:16)。

### 8. P1：验收基线的内容校验不足，证据更新不幂等

`validate_manifest()` 比较存储的 task_sha256 与重新提取的任务 hash，并核对场景 ID 集合，但不对 manifest 自己的 kind、level、boundary、owner 等实际字段重新计算并比较。保留原 hash 和 IDs，修改执行类型或边界仍可以通过校验。

复现：把 integration 场景的 kind 改成 manual、boundary 改成 mock，`validate_manifest()` 仍返回 true。这个保护无法发现误编辑或错误同步。

证据同步另有三个问题：Coverage 状态不更新；Contract 使用追加 `— verified` 而保留 `planned`；每次成功都重复追加 Evidence。复现两次通过后任务文件从 426 增至 493 字符，Contract 为 `planned — verified`，Evidence 有两条相同成功记录。失败不会清除已存在的 verified 证据，而且 Runner 没有保存失败 stdout/stderr，后续排障信息不足。

建议清单使用严格 schema，校验实际不可变字段；每个场景的结果按 revision/执行标识更新，关联命令、代码快照、时间和日志。Markdown 状态由结构化事实生成，避免追加字符串充当状态迁移。

证据：[Manifest 校验](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_manifest.py:77)、[同步证据](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_manifest.py:129)、[Runner 结果与落盘](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_runner.py:14)。

### 9. P1：多平台安装只使用一个全局版本号

`runInit()` 根据 `.code-flow/.version` 决定是否升级全部文件，但一次只部署选定的平台适配器。升级 Claude 后全局版本已经最新，再升级已有 Codex 时进入 current 模式，旧 Codex 命令不会更新。

复现：项目同时安装 Claude/Codex，模拟旧版 Codex 命令与 0.6.1 版本，先 init Claude，再 init Codex；全局版本为 0.6.2，但 Codex skill 仍保留旧内容。

建议分别记录 core 和各已安装 adapter 的版本或受管理文件摘要。增加双平台连续升级、同版本修复缺失文件、旧 CLI 面对新版本项目的测试。

证据：[版本与模式判定](/Users/jahan/workspace/code_flow/src/cli.js:473)、[全局版本写入](/Users/jahan/workspace/code_flow/src/cli.js:704)。

### 10. P1：Stop 的总超时预算不能约束整条执行链

Stop 先给 Done 25 秒，之后 validators 又获得独立 30 秒，而外层 Hook 超时只有 35 秒。Acceptance Runner 不接收 Done 的剩余预算，单个场景默认可运行 60 秒。

复现：Done budget 设为 10ms，验收命令只 sleep 150ms，实际 Done 耗时约 182ms，超时后才轮到 Spec verifier 检测预算耗尽。因此较长测试可能被宿主中断，而没有完整结论。

建议从入口创建唯一 deadline，传递给场景、verifier、validator 和子进程；没有执行的检查必须返回明确 incomplete 状态。避免一次 Stop 重复执行相同的测试命令。

证据：[两个预算](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_stop_hook.py:34)、[验收调用](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_task_runtime.py:203)、[场景默认超时](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_acceptance_runner.py:24)、[Hook 配置](/Users/jahan/workspace/code_flow/src/adapters/claude/settings.local.json)。

## 速度与流畅度分析

### 本机实测

以下子进程测试使用临时项目。小项目复用当前仓库 config/specs；active 测试使用一个 required Spec 的隔离项目。各行 12 次，init-current 为 8 次，扩展规模为 6 次。操作系统文件缓存是热的，但每次 Python 都重新启动；不包含宿主应用、模型推理、网络或用户等待。

| 路径 | 中位耗时 | 解释 |
|---|---:|---|
| Node fresh init | 90.3ms（单次） | 已安装 PyYAML，无安装网络开销 |
| Node current init | 65.1ms | 仍探测 Python/PyYAML、遍历文件并写版本 |
| Prompt：Catalog 路径 | 64.7ms | 含去重周期，有些调用无输出 |
| Prompt：显式文件路径 | 68.8ms | 每次输出相同的约 6.8K 字符 JSON |
| PreTool：编辑、无 active | 66.3ms | 每次继续注入对应规范，无路径分支去重 |
| Prompt：已有 active TASK | 54.1ms | 正常未换任务时具备注入去重 |
| PostTool：Read/no-op 输入 | 26.0ms | 只代表 no-op，不代表真正编辑后的检查 |
| Stop：无 active、无编辑 | 63.3ms | 不包括任何业务测试 |
| cf-stats，无会话历史 | 41.2ms | 小型规范目录 |
| 显式路径，100 个合成 Spec | 97.0ms | 有效 required Spec，每个一个短规则 |
| 显式路径，500 个合成 Spec | 284.8ms | 输出约 34.6K 字符 JSON；真实长规范还会增加体积 |

相同进程内 resolver 首次约 8.7ms、第二次约 0.44ms，但这种内存缓存不能跨独立 Hook 进程复用。已有报告把 0.3ms 缓存命中当成整体延迟，从而得出“无需优化”，这个结论依据不成立。[已有性能报告](/Users/jahan/workspace/code_flow/.code-flow/docs/performance-large-projects.md)、[现有性能测试](/Users/jahan/workspace/code_flow/tests/test_spec_workflow_repository_e2e.py:117)。

### 主要性能和体验来源

1. **路径路由范围过宽。** resolver 将没有匹配当前路径的域标为 global，path router 又全部消费。当前仓库只指定 `src/cli.js`，仍注入 CLI 和 Python 两份规范，共 6,596 字符。候选发现可以保留全量，但实际注入和 scope expansion 必须区分真正的 global 与未命中的 path 规则。[resolver](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_resolver.py:173)、[router](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_router.py:158)。

2. **工作流每层重复做检查。** Start 文档要求运行场景和回归；Stop 再运行 manifest、全部 Spec verifier、validation；Archive 再跑唯一验收命令。当前缺少统一执行计划和同版本执行证据的复用规则。任务越多，重复成本越明显。

3. **依赖安装没有有界等待。** init 的三个 pip fallback 同步执行、隐藏输出且未设超时。PyYAML 已存在时很快，缺依赖且网络差时可能长时间没有反馈。建议探测后给出安装进度、单次与总超时、明确失败状态。[ensurePyYaml](/Users/jahan/workspace/code_flow/src/cli.js:397)。

4. **状态/依赖查询仍由 AI 全文解析。** status/graph 搜索所有活跃 Markdown 后逐个读取，没有任务索引或统一 parser；PRD/design 也被 glob 纳入候选。指定文件模式也应尽早缩小读取范围。数据增加时，主要成本会变成工具调用轮次和模型上下文，而非文件系统本身。[status](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/status.md:12)、[graph](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-task/graph.md:17)。

5. **统计聚合存在二次复杂度。** 每个 violation 都遍历后续事件，且切片产生复制。用不同 session 的合成历史隔离测聚合，1,000 / 5,000 / 10,000 个事件约需 11 / 252 / 995ms，尚未计算日志读取。建议倒序一次扫描，按 session/file/check 保存状态。[统计实现](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_stats.py:20)。

6. **OpenCode 回调同步等待子进程。** `spawnSync()` 位于 async callback 中，Stop 最长设置 35 秒，会同步占用该插件执行线程。idle 结果只是排队到下一轮，并未实现与可阻断 Stop 相同的行为；下一次 chat.message 又可能覆盖队列里的旧反馈。建议采用异步子进程及分离的上下文/反馈队列，并明确平台能力差异。[插件](/Users/jahan/workspace/code_flow/src/adapters/opencode/plugins/code-flow/index.js:24)。

## 每条命令的产出与衔接评价

下表的“质量”评估命令契约和代码保障；未实测 AI 生成 PRD/design 的语义质量。

| 命令 | 速度与交互 | 产出与衔接问题 | 优先改进 |
|---|---|---|---|
| code-flow help/version | 轻量 | 只覆盖安装/迁移，AI 命令另有体系 | 帮助给出两层命令入口导航 |
| code-flow init/upgrade | 已有依赖时快；缺依赖时等待无上界 | 删除用户 skills；平台版本共用 | 管理文件清单、平台版本、安装超时 |
| code-flow migrate | 有备份与 journal，流程比 init 完整 | 大目录多轮遍历、读取和备份；prepare/apply 无统一进度/超时 | 保留事务设计，再增加规模测试和阶段进度 |
| cf-init | 多次配置扫描、可能重复依赖探测和确认 | 新 Spec 示例没有 schema v1 必需元数据；裁剪 config 未必清理已有无关 Spec | 复用一次扫描结果；新产物必须解析通过 |
| cf-learn / --review / --map | 全量深读较重；review 模式设计合理 | 只要求 checks 草稿，未保证 Rule verifier 和 Context refresh；缺机器完成条件 | 结构化候选、Rule ID/verifier 校验、变更影响预览 |
| cf-spec | Python 接口较齐全；doctor 的高层编排较散 | Context、marker、状态恢复由多步骤衔接；配置模式与项目规范不一致 | 统一诊断入口，返回确定的恢复步骤 |
| cf-stats / --audit | 小规模快，事件多时二次复杂度 | L0 固定读取 CLAUDE.md；字符数/4 是粗估；修正率不是代码复验结果 | 识别实际入口文件、线性聚合、指标注明口径 |
| cf-sync | 本仓库快 | 定义的副本相等不代表四平台功能齐全；source 缺失和 deploy-only 不计失败 | 生成受管理清单，校验平台命令集合 |
| cf-validate | 按规则筛选不错；自动修复后仍要求用户重跑 | `git diff HEAD` 不包含 untracked；只单引号包裹路径不足以处理内含引号 | 统一验证 runner，完整变更集合，修复后自动复验 |
| cf-task:prd | 已有信息不重复问、早存草稿是优点 | 完成依赖 AI 自检；轻需求虽有简化入口，仍可能有多轮确认成本 | 结构化最小必填项、复用已确认信息 |
| cf-task:align | 继承 PRD、按类型选模板较好 | 模板与正文读取较多；语义追溯和真实边界主要靠 AI 判断 | 一次读取适用材料，增加可验证的引用约束 |
| cf-task:plan | Source、owner、依赖和场景设计较完整 | manifest 不承接 executable command；verify-plan 主要检查 Spec owner，并未完整验证 design 场景覆盖 | 任务/场景统一 parser 与可执行清单 |
| cf-task:start | 单进程启动方向正确 | 硬门禁未落地；Done/marker 脱节；整文件执行状态不闭合 | 统一状态机与当前 TASK 验收 |
| cf-task:status | 小项目易用，全文读取会随项目增长 | 不支持新 verified 状态；不核对 marker | 从结构化任务数据输出，显示不一致状态 |
| cf-task:graph | 图能帮助计划 | DAG 由 AI 解析；宣称可并行但单 worktree 只允许一个 active | 程序计算 DAG，区分可独立开发与可同时激活 |
| cf-task:block | 动作简单但仍需多步编辑 | 仅改 Markdown，不同步 marker；解除阻塞说明与 start 的 blocked 拒绝逻辑不一致 | 一个 block/resume API |
| cf-task:note | 讨论本身应保留 AI 主导 | 改 design/状态后没有统一 refresh、重验收和 marker 恢复步骤 | 将讨论结论转成受控状态/Context 更新 |
| cf-task:verify-e2e | 重新执行 functional；环境检查以人工确认为主 | 状态正则错误、verified 冲突、Codex 缺命令、失败日志不足 | 独立最终验收状态、平台补全、环境自动探测 |
| cf-task:archive | 完整性、正确性、追溯、一致性四维较好 | 继承上游矛盾与重复执行成本；依赖人工确认的状态真实性 | 消费可信最终验收结果，原子归档并保留证据 |

关于 cf-init/cf-learn 的具体质量风险：schema v1 parser 要求 `id`、`description`、`stages`、`enforcement`，且 required Rules 必须有对应 verifier；cf-init 的新 Spec 格式只给普通 Markdown，cf-learn 允许不可机检内容只写正文。按这些说明新增规则可能直接使后续 resolver 报 metadata error。不是所有已有模板都会出错，风险集中在缺失文件补建与规则增补路径。[初始化格式](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-init.md:87)、[learn 写入](/Users/jahan/workspace/code_flow/src/adapters/claude/commands/cf-learn.md:196)、[解析要求](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_spec_metadata.py:303)。

另一个已复现的验证问题：Stop 把 `{files}` 替换为未转义的字符串，再用 `shell=True` 执行。输入 `src/a b.py` 会变成两个参数；带 shell 特殊字符的路径也存在命令解释风险。当前 `.code-flow/validation.yml` 的 py_compile 就使用该占位符。应改为 argv 列表和显式文件参数。[validator 执行](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_stop_hook.py:192)。

## 测试和度量为什么没有暴露这些问题

现有测试有价值，尤其是迁移故障恢复、Hook JSON 协议、Context/hash 和模板部署检查。但有几类缺口：

- parity 使用手工维护的命令清单，漏掉 verify-e2e；Codex 还有正文行数比例断言，长度相近不能证明行为相同。
- 部分 workflow 测试检查命令文档包含特定语句，不能证明步骤间的数据形状与状态实际兼容。
- 性能测试主要是同一 Python 进程、一个 Spec 的循环；未覆盖真实启动、跨任务切换、多阶段共享预算。
- 验收测试保护了“混合配置时拒绝缺命令”，未保护“全都没有命令”的情况。
- Git 中途提交测试验证能够 complete，没有验证提交后的业务修改仍纳入 Done 检查。

`cf-stats --human --audit` 当前输出静态 token 估算 3,954 / 2,500（158%），压缩节省 0%。这是规范库存口径，不等于每次实际注入量。审计还把 `Stop/session.idle` 当作不存在的文件，说明路径检查仍会产生语义误报。固定使用 CLAUDE.md 会漏掉仅使用 AGENTS.md 的安装，修正率又依赖“后续编辑且没有再记录违规”的事件代理，需要避免把这些统计当成验收事实。

结构扫描发现 Python 的 354 个函数中，有 13 个超过 50 个物理行（含空行/注释）；`cf_stats.main` 为 221 行，`cf_post_hook.main` 为 95 行。另有 42 处 handler 只包含 pass/return，其中一部分是合理的缓存/no-op 降级，一部分缺乏诊断；应分类治理，不能笼统断言“没有静默异常”。`src/cli.js` 为 859 行，`cf_spec_context.py` 为 1,585 行，已经值得按职责拆分。

## 架构取舍与建议

现有架构值得保留的部分是：Node 负责安装和分发，Python 负责规则和工作流；Spec 元数据与 Evidence 有明确类型；Context 持久化；迁移具备备份、staging、journal 和版本最后写入。这些设计有实际价值，不需要整体改写为另一种语言。

当前的主要问题是：程序能够确定的业务规则分散在 Markdown 指令、Python parser、Gate、Hook 和平台适配器里。它们各自正确时，组合起来仍可能相互矛盾。继续单独增加提示词和分支会扩大维护面。

| 关注点 | 当前情况 | 建议收敛方式 |
|---|---|---|
| 任务状态 | Markdown 与 active marker 分别修改 | Python workflow service 统一 start/block/resume/complete/archive 迁移 |
| 验收事实 | Coverage、Contract、Evidence、manifest 分别更新 | 按 task/scenario 标识存储结构化事实，Markdown 为可读视图 |
| Spec Context | 既承载规则绑定，又被多处用于流程判断 | 保留规则事实；显式提供当前 TASK 的投影与 Gate scope |
| 验证执行 | acceptance、Spec verifier、validation 各有 runner | 共享执行基础层、deadline、argv、日志、结果协议与命令去重 |
| 平台适配 | 多份正文加手工清单 | 一份 canonical 命令定义生成适配产物，测试集合完整性和语义绑定 |
| 性能缓存 | 多种进程内缓存和分散状态文件 | 优先减少重复解析/注入；需要时增加跨进程索引，并定义正确失效条件 |
| 展示与交互 | AI 同时处理讨论、表格解析和状态更新 | AI 负责需求/设计判断；程序负责事实提取、验证与事务写入 |

不建议当前就为几十毫秒启动成本引入常驻 daemon；那会增加进程生命周期、失效和平台维护成本。先修复范围与状态，再做批处理、持久化索引和去重，收益更直接。OpenCode 等常驻宿主中的子进程调用应独立改为异步，这不要求重写整个 CLI。

仓库规范与实现也需要对齐：项目规范要求 required workflow 不允许项目级降级，`resolve_enforcement()` 实际支持 required/warn/inject；规范强调无静默异常，但现有部分加载失败直接返回空值；CLI 本身使用内置模块，npm 包仍声明 `@ccusage/codex` 外部依赖，src 中没有对应使用。应明确哪些是产品能力、哪些是遗留约定，避免规范本身成为冲突来源。[enforcement](/Users/jahan/workspace/code_flow/src/core/code-flow/scripts/cf_core.py:492)、[包依赖](/Users/jahan/workspace/code_flow/package.json:15)。

## 建议实施顺序与通过条件

第一批先恢复可信行为：用户 skills 保留、提交后仍检查完整 TASK 变更、无命令不允许验收通过、Manifest 真实字段校验、TASK 切换必须注入新契约。每项都可以用本次复现转成正式回归测试。

第二批打通主线：程序化 Start Gate；统一 complete/block/resume；按 TASK owner 执行场景；明确 E2E 与需求最终验收状态；补齐 Codex 命令；证据写入幂等并保留失败日志。核心通过条件是一条实际跨两个 TASK 的 Plan → Start → 提交 → Complete → 下一个 Start → E2E → Archive 自动化测试，完整验证所有中间产物。

第三批改善速度与维护：同版本重复测试去重、唯一 deadline、路径路由收敛、状态/DAG 程序解析、统计线性聚合、适配器自动生成、按平台升级。性能检查至少覆盖新进程启动、100/500 Spec、长事件日志、相同 Context 的任务切换，分别统计脚本耗时、注入字符量和命令调用数。目标值应在修复后的实际工作负载上确定，不能直接套用进程内缓存的数字。

## 复现材料

以下脚本仅在临时目录创建测试项目；读取仓库的实际实现和既有 fixture。

- [核心复现与小项目 benchmark](/tmp/code-flow-audit.MC5FB1/audit.py)
- [安装、规模、统计与路径复现](/tmp/code-flow-audit.MC5FB1/extra.py)
- [同 Context 切换 TASK 的注入复现](/tmp/code-flow-audit.MC5FB1/transitions.py)

复现时从仓库当前环境运行 `PYTHONDONTWRITEBYTECODE=1 python3 <上述脚本路径>`。报告中的合成性能数据用于定位趋势，不代表大型真实项目的延迟保证。
