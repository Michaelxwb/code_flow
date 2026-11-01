---
design_template: full
---
# Spec 优化方法论工具化：需求与设计

> 版本 v0.1，2026-10-31；状态：设计草稿。来源：[PRD](spec-optimization.prd.md)。场景唯一源为 `spec-optimization.scenarios.md`。

## 1. 文档控制

产品、设计与实现负责人：code-flow maintainer；真实项目复跑由使用方维护者负责。PRD 的需求基线仍为草稿，本设计不推定产品评审已完成。

## 2. 需求分析

### 2.1 需求概述

将规范治理中确定性、可复查的审计、预算模拟、影响查询和结构优化流程工具化。目标用户是大仓维护者、cf-learn 使用者、CI 与 code-flow 维护者。真实项目观测的 141 条路径未命中和 22 份规范只是背景样本，不作为测试预期或普适阈值。

### 2.2 痛点与价值

模块相对路径和 YAML 被误报；聚合预算与一次编辑注入口径混淆；目录错位、catalog 省略和结构变更的影响不透明。以真实解析路径、可解释结果和安全事务减少误操作。US-01 至 US-09 沿用 PRD §3.2。

### 2.3 功能方案

| 功能ID | 功能名称 | 优先级 | 来源 |
|---|---|---|---|
| FEAT-01 | 审计路径多根解析 | P0 | US-01 |
| FEAT-02 | 过滤结构噪音与阈值配置 | P0 | US-02, US-03 |
| FEAT-03 | 真实路由预算模拟 | P0 | US-04 |
| FEAT-04 | domain 布局诊断 | P0 | US-05 |
| FEAT-05 | catalog 截断可见 | P1 | US-06 |
| FEAT-06 | 只读影响面查询 | P1 | US-07 |
| FEAT-07 | 结构优化提案与受保护应用 | P1 | US-08 |
| FEAT-08 | SOP 与四平台文档 | P1 | US-09 |
| FEAT-09 | 测试、同步与发布 | P0 | US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09 |

### 2.4 范围与边界

范围覆盖 PRD 九项功能；不自动判断语义真伪、删除或修改 RULE 文本/ID、自动迁移任务 Context，也不代替 cf-learn 的语义审查。优化 apply 首发包含在内，经用户确认；domain 诊断默认 warning，`strict_domain_layout: true` 时阻断。对现有数据只增量添加 JSON 字段；行为改变须明示。PRD 对默认兼容的要求与新默认路径发现、YAML 降噪存在张力：维持字段与退出码兼容，但诊断结果按新规则改变，并在发布说明记录。

### 2.5 验收条件

#### 2.5.1 业务规则与约束

| ID | 内容 | 验证场景 |
|---|---|---|
| RULE-01 | 每个路径按固定根顺序检查，仅实际存在的根可命中；缺失与无效根独立报告。 | S-01, S-02, E-01 |
| RULE-02 | 只排除 frontmatter 与确定的结构行；正文规则保持可查，模板排除。 | E-02, S-03 |
| RULE-03 | 单次预算必须复用 router 的候选、内容处理和完整组装后的 token 估算；聚合另列。 | S-04, E-03, B-01 |
| RULE-04 | 布局错位默认诊断，严格模式阻断，不改配置。 | E-04, E-05 |
| RULE-05 | catalog 保持原排序及预算约束，明确缺失域和不可容纳错误。 | S-05, B-02 |
| RULE-06 | impact 只读、有界且不得把截断误报为完整。 | S-06, B-03 |
| RULE-07 | apply 使用绑定快照的提案，验证边界、在途 Context、RULE 文本/ID 和 verifier 等价；任一失败不留半成品。 | S-07, E-06, E-07, E-09, E-10 |
| RULE-08 | CLI / 文档四平台一致，保留原 JSON 字段，运行时双副本同步，不新增依赖。 | S-08, S-09, E-08 |

#### 2.5.2 功能验收场景

S-01、S-02、E-01 验证路径根；E-02、S-03 验证审计；S-04、E-03、B-01 验证预算；E-04、E-05 验证布局；S-05、B-02 验证 catalog；S-06、B-03 验证影响范围；S-10 验证只读预览；S-07、E-06、E-07、E-09、E-10 验证提案与安全应用；S-08、S-09、E-08 验证 SOP、同步和兼容；B-04 测容量。具体层级、输入、真实边界及预期仅以场景源为准。

场景计划登记为 `auto`；计划阶段仅收集 strict xfail 测试骨架，验收统一使用 `--runxfail`，直到实现并验证真实断言之前必须失败。收集结果不等同执行证据。

#### 2.5.3 非功能指标

| ID | 要求 | 验证 |
|---|---|---|
| NFR-01 | 原字段不删不改名，缺省配置可解析；诊断改善允许改变问题数量。 | E-08 |
| NFR-02 | 100 份 spec、1000 任务文件的合成仓中 budget 与 impact 各 <2 秒；分别记录环境、三次原始时间与最大值。 | B-04 |
| NFR-03 | apply 写入仅限 `.code-flow/specs/**` 与 `.code-flow/config.yml`，事务可回滚，不写任务文件。 | E-06, E-09, E-10 |
| NFR-04 | 新结果结构与错误码稳定。 | S-04, S-06, E-10 |
| NFR-05 | 四平台归一化正文及 canonical/deploy 对应一致。 | S-09 |
| NFR-06 | 无新增 npm 运行时或 Python 第三方依赖。 | E-08 |

#### 2.5.4 验证环境假设

容量 fixture 使用真实临时 Git 仓库、100 份合规 spec 与 1000 个任务文档，不模拟文件系统；记录 CPU、系统、Python、文件系统、命令、样本和计时。硬件和负载不预设为已有实测：环境缺失时记录 env_blocked，不伪造达标。其他场景采用隔离临时目录和本项目实际 CLI/runner，无数据库或浏览器依赖。

## 3. 技术设计

### 3.1 方案选型

复用 resolver、router 的实际组装、token 估算与有效 mapping；新增 feature-scoped Python 服务承载审计增强、影响索引与事务提案，命令分发复用运行时注册表。相对平行维护一套匹配算法，共用核心可避免预算判断漂移；影响查询单次遍历并建立倒排索引，避免每个 spec 重复扫描所有任务。跨运行缓存仅在有可证明输入身份时启用，初版优先进程内复用。Python 使用项目已有依赖与标准库；Node CLI 不增加 npm 依赖。

### 3.2 架构设计

#### 3.2.1 审计与预算（FEAT-01–03）

audit 从项目根、spec 文件所在目录、配置根、自动发现根按此顺序解析，路径原文不变；以规范化真实路径去重，报出命中根，根不存在/越界/不可读时给出可区分诊断，不能判成已解析。自动发现暂按 PRD 功能清单采用 `apps/*/src/*`、`packages/*/src/*`、`lib/*/src/*`，glob 展开仅一次并排序；跳过 URL 与 glob 模式；不可解析的路径保持 missing。frontmatter 只识别文件开头配对界定符，正文只排除明确的 YAML 结构行，避免丢失重复规则；模板仍排除。`audit.long_spec_tokens` 为正整数，默认 500，坏配置显式错误。

`budget` 调用同一路由候选选择、压缩与 assemble 逻辑，输出每份正文估算和组装后 `matched_total`；不得假设单份 token 之和等于组装文本 token。`limit=min(total,l1_max)`，保留全部 required 规则，不裁剪；`aggregate_total` 单独报告不参与单次通过判断。`--paths` 是一次整体编辑集合；可选 `--changed` 合并 Git 已暂存、未暂存与未跟踪路径，失败显式返回，不能伪装空集合。

#### 3.2.2 doctor 与 catalog（FEAT-04–05）

按配置显式 domain 与 `specs/<domain>` 比对，区分配置域目录缺失、跨域声明和目录中未登记文件；`_map.md`、`shared/`、`_session/` 与 `tags: []` 使用现有约定处理，自动发现项不能误判为未登记。默认 warn、严格模式 fail；不得把配置错误静默改写。catalog 的被丢弃条目必须由实际排序和预算结果计算，域以路径首段归并；JSON 追加 `dropped_count`、`dropped_domains`，可读报告保留必要提示。极小预算暂按现有行为返回明确错误并报告最小可用预算，不突破预算强行列出一项。

#### 3.2.3 影响与结构事务（FEAT-06–07）

impact 扫描任务目录的 Context 和任务文档，解析绑定及结构化任务字段，结果包含路径、任务 ID、引用类型、Rule、状态和来源；稳定排序。遍历有界、返回 `truncated` 与已扫描数量，读失败显式告警，无法确认完整时禁止宣称无影响。任务文档用现有统一解析器；归档与在途分别标记。

optimize dry-run 输出只读提案（方案 ID、输入路径及摘要、配置摘要、前后 token、路径匹配组合与映射差异、影响 Context、候选操作和理由），建议是启发式，不自动决定域。首版 apply 仅允许显式提案中的 Conventions 移动和必要 mapping 更新；用户明确批准具体提案，绑定全部输入 SHA-256 并在写入前重校验，版本改变则拒绝。拒绝路径穿越、符号链接越界、目标目录不存在、在途 Context 受影响、RULE ID/正文或 verifier 关联变化；多个文件写入前构造全量新内容与映射，验证守卫后写临时文件、备份与 journal，再原子替换；失败恢复原字节，完成后清理临时文件。备份/journal 位于 `.code-flow/specs/` 下的受控事务目录，不覆盖既有用户文件，config 文件也只在允许清单内替换。中断后需显式检测 journal、恢复或拒绝下一次 apply。源路径、目标路径、map 与 Context 引用完整出现在预览；禁止根据假定用户身份自动确认。

#### 3.2.4 文档与发布（FEAT-08–09）

SOP 指导体检、证据核实、人工去重、仅超注入目标时拆分、影响查询、审核提案、受保护 apply、refresh 及 Gate；不得承诺所有简写都安全或使结构建议自动生效。更新 canonical 文档、四平台与部署副本、变更日志；版本按项目发布策略选择，不预设升版。`cf-sync check`、CLI 无新增依赖及现有安装/迁移测试作为发布门禁。

### 3.3 数据设计

无需数据库。配置扩展为 `audit.path_roots: list[str]`、`audit.long_spec_tokens: positive int`、`spec_workflow.strict_domain_layout: bool`；无配置分别为自动发现、500、false。budget JSON 包含 `matched_specs[{path,tokens}]`、`matched_total`、`aggregate_total`、`limit`、`over_limit` 和说明；保持既有 stats 字段并增补单次与聚合语义。impact JSON 含 `references[]`、`scanned_files`、`truncated`、`errors[]`。提案 JSON 包含 schema 版本、输入哈希、预期文件变更、保护对象快照及影响报告；绝不包含凭据。

### 3.4 接口设计

| 接口ID | 接口与契约 | 功能 |
|---|---|---|
| API-01 | `stats --audit` 添加解析根、阈值及诊断字段，原字段保留 | FEAT-01, FEAT-02, FEAT-03 |
| API-02 | `spec budget --paths <file...> [--changed] [--json]`；0 表示未超限，超限/配置或环境错误分别返回非零和稳定 reason | FEAT-03 |
| API-03 | `spec doctor` 追加布局 findings 与严格模式；不写配置 | FEAT-04 |
| API-04 | 现有 catalog JSON/文本追加省略条目及域；保留截断排序 | FEAT-05 |
| API-05 | `spec impact <spec_id|path> [--json]`；只读、报告截断和读取错误 | FEAT-06 |
| API-06 | `spec optimize --dry-run [--paths ...] [--target <规范路径>] --json` 输出提案，可由用户重定向保存；仅明确指定单一来源和新目标时生成可应用的 Conventions 移动。`spec optimize --apply --plan <提案文件> [--json]` 只读提案、交互展示变更并取得明确确认，无交互终端时拒绝应用；应用前重校验哈希 | FEAT-07 |
| API-07 | SOP、四平台文档及同步命令 | FEAT-08, FEAT-09 |

stdout 在 `--json` 下只输出一个 JSON；诊断写 stderr；参数不兼容或缺必要值不猜测默认。命令注册、Python 入口 shim 与四平台调用必须走运行时正式契约。

### 3.5 质量实现方案

热点为多根 stat、重复解析规范和遍历任务；每次运行一次发现、一次扫描、构建引用倒排，按内容而非路径重复计数。不可证明缓存安全时重算。RISK-01 路径假命中以根来源及真实缺失检查减缓（S-01、S-02、E-01）；RISK-02 规则或 verifier 损失以预后快照及故障注入防护（E-06、E-09、E-10）；RISK-03 布局误阻断默认 warn（E-04、E-05）；RISK-04 预算口径漂移与 CI 兼容由真实 router 对照和旧字段测试覆盖（S-04、E-08）；RISK-05 多文件中断以事务恢复验证（E-10）；RISK-06 扫描截断误认为完整由 B-03 防护。

## 4. 部署与运维

采用 canonical → deployed 同步与现有 runtime 安装完整性检查。先运行迁移 dry-run，安装由现有事务处理；失败回滚，不覆盖用户配置。任何新配置保留旧仓缺省可用。发布前运行单元、真实 CLI 集成、容量测试、四平台 parity 与 sync check；性能结论基于原始数据。

## 5. 风险与依赖

依赖 `cf_scan`、`cf_core`、`cf_spec_resolver`、`cf_spec_router`、`cf_spec_context`、task parser、runtime registry 与现有平台适配。路径根冲突、catalog 极小预算和旧 JSON 兼容应分别覆盖，不以合成数据推断真实大仓收益。受影响在途 Context 的 apply 禁止自动迁移；用户需先解除阻断或重新规划。

## 6. 需求追溯矩阵

以下为设计阶段的来源与场景映射；plan 生成 manifest 后必须由追溯工具生成含 check 和状态的正式矩阵，不以本表代替执行证据。

| 用户故事 | 功能 | 接口 | 验证场景 |
|---|---|---|---|
| US-01 | FEAT-01 | API-01 | S-01, S-02, E-01 |
| US-02, US-03 | FEAT-02 | API-01 | E-02, S-03 |
| US-04 | FEAT-03 | API-01, API-02 | S-04, E-03, B-01, B-04 |
| US-05 | FEAT-04 | API-03 | E-04, E-05 |
| US-06 | FEAT-05 | API-04 | S-05, B-02 |
| US-07 | FEAT-06 | API-05 | S-06, B-03, B-04 |
| US-08 | FEAT-07 | API-06 | S-10, S-07, E-06, E-07, E-09, E-10 |
| US-09 | FEAT-08 | API-07 | S-08 |
| US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09 | FEAT-09 | API-07 | S-09, E-08 |

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计影响 | 设计落点 | 验证场景 / verifier | 状态 |
|---|---|---|---|---|---|
| cli-code-standards#RULE-cli-dependency-allowlist-001 | required | 不增加依赖 | §3.2.4 | E-08 + 原 verifier | 已设计 |
| cli-code-standards#RULE-cli-user-content-preservation-001 | required | 配置事务保护用户数据 | §3.2.3 | E-09, E-10 + 原 verifier | 已设计 |
| cli-code-standards#RULE-cli-platform-parity-001 | required | 四平台与部署同步 | §3.2.4 | S-09 + 原 verifier | 已设计 |
| cli-code-standards#RULE-cli-hook-guard-001 | required | 保留 hook 项目边界 | §3.4 | E-08 + 原 verifier | 已设计 |
| cli-code-standards#RULE-cli-migration-transaction-001 | required | 迁移继续使用事务与版本最后写入 | §4 | E-10 + 原 verifier | 已设计 |
| cli-code-standards#RULE-cli-opencode-native-001 | required | 不破坏 OpenCode 原生事件 | §3.2.4 | S-09 + 原 verifier | 已设计 |
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | hook 不输出调试信息 | §3.4 | E-08 + 原 verifier | 已设计 |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | 错误显式报告 | §3.2.1 | E-01 + 原 verifier | 已设计 |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | 保留 hook JSON 协议及 no-op | §3.4 | E-08 + 原 verifier | 已设计 |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | Context 检查 fail-closed | §3.2.3 | E-09, E-10 + 原 verifier | 已设计 |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | 双副本与平台同步 | §3.2.4 | S-09 + 原 verifier | 已设计 |

## 评审待确认

- 自动发现暂含 `lib/*/src/*`（PRD §4 与 §10 不一致）。
- catalog 无法容纳首条及完整提示时暂保持明确报错并报告最小预算；与 PRD §4.2 的“至少一条”相冲突。
