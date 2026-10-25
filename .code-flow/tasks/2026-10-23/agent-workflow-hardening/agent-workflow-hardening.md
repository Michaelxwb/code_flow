# Agent 工作流硬化（Backlog）

- **Status**: draft
- **Created**: 2026-10-23
- **Updated**: 2026-10-25
- **Priority**: P1
- **Source**: code-flow 0.8 per-check / 多 check / review 事故复盘

## 目标

减少 agent 在跨模块变更和阶段交接中的遗漏。工具负责校验已声明契约、执行证据和状态的一致性；验收范围是否完整，仍需通过独立审查和真实需求试点验证。

## 本轮实施：跨消费者契约与回归场景

2026-10-24 讨论后，优先加固现有 acceptance 数据流。下方命令契约、`task next`、通用 Impact Scan 和强制 review 保留为候选，不作为本轮必交付项。

- audit 按场景的全部 `checks` 读取证据；保留单 `check` 兼容，报告包含每个失败 check。
- 每个 check 保留自己的执行结果；场景的失败或 `accepted_risk` 不覆盖其他成员的通过证据。runner 与 CI import 使用相同的 per-check 结果表示。
- merge 失效检查与需求级 verify 共用逐 check 指纹解释；collect 共用场景到 check 的关系解析。
- 缺少部分 central evidence 时阻断 audit；完全没有 central evidence 的旧记录允许使用 manifest，但每个 check 必须有明确证据。
- audit 检查历史记录的一致性，不用当前工作树强行否定已归档需求；当前输入是否需要重跑，由 verify / merge / collect 校验。

### 如何造场景验证

测试入口：`tests/test_cf_acceptance_consumers.py`。每个用例在临时目录建立真实 Git 项目，A/B 各执行一个 Python 子进程、检查独立输入文件并记录执行次数；runner、指纹、checkpoint、证据存储、audit 和 collect 均不 mock。

| 场景 | 故障或操作 | 预期 |
|---|---|---|
| 正常与复用 | A/B 都通过，再次运行 | 各执行一次；audit/collect 通过；同时覆盖仅 `checks` 和兼容 `check` |
| 第二个 check 失败 | 首次全部通过，修改 B 输入并单独运行 B | audit 定位 B，collect 拒绝 B；verify/merge 识别 B 的旧指纹 |
| 部分证据丢失 | 删除临时项目 B 的证据目录 | 不借用 A 或场景的汇总 pass |
| 输入变化未重跑 | 修改 B 输入后执行需求级 verify | 旧证据失效，真实执行 B 的断言并失败；A 不重跑 |
| 部分失败后恢复 | A 通过、B 失败，再修复 B | A 保持 passed，B 从 failed 变 passed；普通复用和 checkpoint resume 均只补跑 B |
| 局部风险接受 | 仅对 B 写入测试夹具的用户确认 | A 仍为 passed；B 单独为 accepted_risk；A 后续失败仍阻断 |
| 多个失败 | A/B 分别产生真实失败证据 | audit 保留两个 finding，不按场景吞掉其中一个 |
| 旧记录兼容 | 移除全部 central evidence；再分别移除 B 的 hash / outcome 或清空 outcome | 完整 manifest 证据可读，缺少成员证明则阻断，不继承场景汇总 pass |
| CI 回传 | 真实执行 A/B，把退出码转成 JUnit 再导入 | 分别保留每个 check 的结果，不把场景失败复制给通过的 A |

运行：`python3 -m pytest -q tests/test_cf_acceptance_consumers.py`。

先观察旧实现失败，再修改生产代码使其通过；同时回归已有 audit、runner、CI、parallel、verify 和协议测试。这些场景验证工具数据流，不替代后续 2～3 个真实需求对审查收益和额外耗时的评估。

## 命令修复（2026-10-25）

- `task verify --checks` / `--layers validators` 支持进行中的任务，验证范围包含 active 基线以来已提交与未提交文件；不写 done/verified。marker 损坏、Context hash 漂移或需求身份不匹配仍阻断。
- `task verify-e2e --checks` 使用相同的 layers 解析；不再静默执行 review/e2e。各 action 使用独立参数解析器，不适用的选项明确报错。
- 多 check 的预检失败和断言输出保存在逐 check 结果中；`acceptance run` 与 `task verify` 的环境错误摘要均给出正确 check ID、owner、命令、退出码和输出。
- 四平台归档说明统一由 `task archive` 移动目录，目标以 `archived_to` 为准；保留 Spec Gate，删除手工移动和额外 validate/acceptance run。旧扁平布局缺少独立需求边界时明确报告迁移要求，不宣称运行时已经支持逐文件归档。
- 环境准备优先消费 checks 声明的 `preflight`；移除固定的环境确认问答，保留真实外部依赖阻塞和人工验收确认。

命令级回归入口：`tests/test_workflow_command_hardening.py`。通过真实安装、Git 提交、公开 CLI 与子进程验证开发中检查、别名参数、错误参数、Context 防护、状态不推进及诊断信息。原实现中对应的 10 个用例已观察到失败，再修改运行时使其通过；新增需求级诊断用例覆盖 acceptance → verify 的反馈传递。

## DeepSeek 反馈修复（2026-10-25）

- 场景质量统一由 `cf_scenario_quality` 校验：浏览器 E2E 与 system/capacity 分层、具体预期、有效 expected_refs、延后原因/owner/阶段、环境枚举与稳定组件标识。
- `verify-plan` 始终校验 manifest 基线，聚合场景语义、测试登记与真实收集、设计 ID 闭环及 Spec Gate，不再依赖可选参数才运行质量检查。
- 浏览器/capacity/smoke 的声明与测试收集结果对齐，并检查实际 command 是否选择登记用例；收集错误保留命令、退出码与输出。登记配置纳入输入指纹，修改后不能复用旧证明。
- 新增公开入口 `code-flow design lint`，检查 FEAT/API/NFR 定义与引用、功能场景覆盖、同 ID NFR 冲突、场景功能错配和已声明模板的必填章节。
- required code/review 的 applied 不能代替执行证据；document verifier 定位正确章节内的条目并拒绝未解决占位。doctor 增加各阶段 readiness、未完成引用报告及 convention_review_required 提示。
- CLI/runtime 不一致时区分升级 CLI 与迁移 runtime；旧命令族不会被通用 --help 伪装为可用。当前机器的全局入口已从 0.7.0 升级为经过验证的本地 0.8.0 包，并确认 scenarios/design/acceptance 命令可用。
- 四平台的 align/plan/start/spec 说明同步更新；可执行数据格式与收集器配置见 `docs/acceptance-contract.md`。数量报告区分声明分类与经过真实收集的可运行数量；未检查的 runnable 值为 null。

新增回归入口：`tests/test_acceptance_contract_hardening.py`、`tests/test_design_and_registration_gates.py`。使用真实 Git、公开命令入口、临时设计文件和原生 pytest 收集验证；Playwright JSON 适配以官方报告结构为依据。测试登记证明可选用例与套件关系，真实边界与业务断言仍需实际执行证据。

本轮新增 40 个回归用例。`node src/cli.js validate --root "$PWD" --json` 全量校验通过（decision=pass，failures=[]，incomplete=false，未复用检查结果）；全局 `code-flow sync check` 确认源码与五组部署副本一致，`git diff --check` 通过。

## 待优化项

### 1. 命令契约化

- [ ] 所有 `cf-task:*` 命令统一包含：进入条件、必须读取、必须执行、必须产出、退出验证、失败处理、下一步、禁止项。
- [ ] MUST 规则必须对应 CLI 命令或测试，不用“建议 / 尽量 / 认真”等不可验证措辞。
- [ ] 命令正文收敛为短契约；长模板、示例移到引用文档，避免 agent 跳读。
- [ ] 增加 `code-flow command audit`：检查每个命令是否有退出验证和可执行产物。

### 2. 阶段状态机与 `task next`

- [ ] 新增 `code-flow task next --json`：返回当前阶段、blockers、唯一可执行命令、是否可完成。
- [ ] 所有阶段结束时调用 `task next`，agent 不靠记忆决定下一步。
- [ ] 阶段顺序固定：prd → design → plan → impact → implement → review → verify → done → archive。
- [ ] 禁止手工改状态或跳过阶段；状态只能由运行时门禁推进。

### 3. Impact Scan（改前影响分析）

- [ ] 新增 `impact scan`：从 git diff 提取改动字段/文件/消费者，输出 producer-consumer 矩阵。
- [ ] 自动列出未覆盖的跨功能组合：multi-check、cache/resume、CI import、parallel merge、archive。
- [ ] 高风险 consumer 未确认或缺少对应测试时，plan/start 拒绝继续。
- [ ] 产物是工具报告 + 缺失测试清单，不是让 agent 手写影响分析作文。

### 4. Change Review（改后独立审查）

- [ ] 新增 `cf-task:review`，由独立 subagent/session 执行，写代码的 agent 不能自审。
- [ ] review 必须产出可失败 repro 或新增回归测试；只有能复现的问题才算 finding。
- [ ] review 结果绑定 diff hash；diff 变化后自动 stale。
- [ ] P0/P1 finding 未关闭时 `task finish` 阻断；P2 必须登记 owner。
- [ ] 新增 `code-review` verify layer，archive 全量验证包含该层。
- [ ] 不接受只有 `verdict: pass` / “已 review” 的记录。

### 5. 避免形式主义

- [ ] 不新增必填的 impact.md / review.json 作文；优先使用工具报告和可执行 probe。
- [ ] 门禁只卡未关闭 P0/P1 repro、证据与 diff 不一致、必跑层未跑。
- [ ] 先做 2～3 个任务 pilot，统计：真实缺陷数、误报数、额外耗时、escaped defect。
- [ ] 没有效果的门禁删除，不因“流程完整性”保留。

### 6. 经验回流

- [ ] 每个 escaped bug 转成永久 probe / regression test。
- [ ] review findings 自动进入 `cf-learn` 候选规范或检查规则。
- [ ] 建立 bug pattern 库：部分覆盖、证据伪造、缓存掩盖未执行、filter 丢依赖、resume 缺口。
- [ ] `cf-stats` 增加 escaped defect rate / review finding recurrence。

### 7. E2E 精度（plan / start，已落地一部分）

- [x] 测试层级增加 `component` / `contract`，明确 E2E 只用于关键旅程。
- [x] E2E 必须有 P0/P1、`why_e2e`、`boundary`、`steps`、`expected`；非 smoke 必须有 `trigger_paths`。
- [x] `scenarios parse --quality` / `acceptance manifest --verify-plan` 失败关闭。
- [x] `task start` 返回 `e2e_plan`，只写 owned E2E，smoke 由需求级 verify 运行，deferred 不补。
- [x] `changed` profile 按 `trigger_paths` 过滤 E2E；`smoke` profile 只跑 smoke E2E。
- [ ] 根据真实大项目反馈校准 `trigger_paths` 粒度，避免过宽导致全量、过窄导致漏跑。
- [ ] 给 E2E 增加运行时长预算与 flaky 统计，接入 `cf-stats`。
- [ ] 用 2～3 个真实需求对比“改前 E2E 数量 / 运行时长 / escaped defect”，验证门禁有效。

### 8. 原剩余代码项（2026-10-24 代码核对）

- [x] 工具管理的 parallel merge/rebase 完成后 acceptance evidence 按 per-check 重新校验并标 stale；不代表监听任意外部 Git 操作。
- [x] `accepted_risk` owner 绑定到具体 task/scenario。
- [x] audit 多 design 的风险去重保留同名不同来源风险。
- [x] stats 区分 deferred rule、有效 accepted risk 与失效风险记录。
- [x] doctor 在普通用户项目比较 CLI 包版本。
- [x] scenarios 文件缺失时，reference-only design 明确阻断；仅完整旧设计可 fallback。
- [ ] CI import 多 check 的显式覆盖格式与文档。

## 验收

- 新任务 plan 时自动生成 impact 报告；
- 高风险任务 finish 前必须有有效 review probe；
- `task next --json` 能独立驱动完整流程；
- 用后续两个真实需求验证没有增加无效填表时间。
