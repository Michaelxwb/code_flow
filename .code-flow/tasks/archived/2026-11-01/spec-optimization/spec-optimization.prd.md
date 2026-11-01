# PRD: Spec 优化方法论工具化（spec optimization）

> **文档编号**: PRD-2026-10-29-001
> **文档版本**: v1.0
> **创建日期**: 2026-10-29
> **产品负责人**: code-flow maintainer
> **状态**: 草稿

**评审边界说明**:
- **需求基线**: 第 2–8 章（背景/用户/功能/非功能/范围/依赖/规范约束）→ 通过后锁定
- **设计输入**: 第 3–8 章 → 为 `cf-task:align` 提供 US / FEAT / NFR / 范围 / Spec refs

**ID 体系**: US（用户故事）、FEAT（功能）、NFR（非功能指标）、S/E（验收场景）

**背景来源**: 2026-10-29 在 fluxion-harness（22 份 Tier 1 spec、38k tokens）上完成的一次全量 spec 对账与拆分实践。本文只固化其中**可复现、与具体项目无关**的部分。

---

## 1. 文档控制

### 1.1 责任人

| 角色 | 负责人 | 职责 |
|---|---|---|
| 产品 | code-flow maintainer | 需求范围与优先级 |
| 设计/实现 | code-flow maintainer | 命令面、配置 schema、测试 |
| 验收 | 使用方项目维护者 | 在真实仓库上复跑 |

### 1.2 修订历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-29 | 初稿：基于 fluxion-harness spec 优化实践提炼 |

---

## 2. 背景与目标

### 2.1 问题陈述 [必填]

在大仓（20+ 份 Tier 1 spec）上做规范治理时，`code-flow stats --audit`、`spec catalog` 与 `path_mapping` 的现有行为会稳定地产生误导，导致每个项目都要重新踩一遍同样的坑：

1. **路径审计假阳性**：`find_missing_paths` 只按「项目根 + spec 所在目录」解析。spec 中大量使用模块内简写（`application/run_admission.py`、`worker/claimer.py`），真实路径在 `apps/*/src/*` 或 `packages/*/src/*` 下，于是必然报「过时」。fluxion-harness 一次审计 141 条未命中，绝大多数属于这一类。
2. **冗余审计噪音**：`find_redundant_lines` 把 `stages:`、`- design`、`verifiers:`、`type: command` 这类 frontmatter/YAML 结构行计入跨文件重复；22 份 spec 全部命中，用户无法从报告里看出真正的重复规则。
3. **冗长阈值不可配**：硬编码 `tokens > 500`，对本来就承载机检约束的 spec 没有区分度；用户要么忽略整列，要么为了消警告做无意义删减。
4. **预算语义分裂**：router 用 `min(total, l1_max)` 限制**一次编辑命中规范的总和**；`stats` 的 `L1 超出预算` 却按全部 spec 求和判断。按后者调参会把 `l1_max` 设到低于真实编辑组合（fluxion-harness 前端最坏组合 ≈5.2k），直接导致 `spec_budget_exceeded`。
5. **domain 布局静默错位**：domain 由 spec **所在目录**决定。把新 spec 放进 `test/` 却在 `path_mapping` 里声明 `e2e` 域时，旧 spec 被并入 `test` 域，`e2e/**` 反而不命中；没有任何报错。
6. **catalog 静默截断**：`catalog_max` 超限时只截断条目，不报告丢了哪些域；fluxion-harness 22 个域只列出 11 个，看起来"完整"。
7. **结构性改动缺少护栏**：拆分/移动 spec 会改变 `RULE` id、`spec-context.yml` 绑定与在途任务状态；现有工具没有"改动前影响面"与"rule id 不变"的检查，容易把任务 Gate 打红。

这些问题的共同点是：**它们是确定性的工具行为缺陷，不依赖具体项目的语义判断**，适合在 code-flow 内修复；而"某条规范是否还成立""是否拆域"仍应由 `cf-learn` 的证据对账 + 用户确认完成。

### 2.2 目标与价值 [必填]

- **减少误报**：让 `stats --audit` 的"过时/冗余"只在真问题时出现，恢复报告的可用性。
- **统一预算口径**：用户能直接看到"一次编辑会注入多少 tokens"，并据此设计 `path_mapping` / spec 拆分，而不是猜。
- **结构改动可预期**：拆分/移动前能列出受影响的 Context/任务与规则，且工具保证 `RULE` id 不被悄悄改掉。
- **形成 SOP**：把这次实践写成可执行的标准流程，后续项目按同一套检查与阈值执行。
- **保持向后兼容**：所有新增配置有默认值；不改变既有命令的成功输出结构，只增补字段/报告。

---

## 3. 用户与场景

### 3.1 目标用户 [必填]

| 用户 | 场景 |
|---|---|
| 大仓维护者 | 20+ spec、几十万行代码，规范开始冗余/过时 |
| `cf-learn` 使用者 | 已完成语义对账，需要做结构治理（拆分/合并/移动） |
| CI 负责人 | 想在 PR 上检查"规范注入是否超预算""是否引用死路径" |
| code-flow 维护者 | 新增/调整命令、适配四平台、保证 canonical↔deployed 同步 |

### 3.2 用户故事 [必填]

- **US-01**：作为大仓维护者，我希望 `stats --audit` 只报告真正的死引用，而不是把模块内简写当成过时。
- **US-02**：作为大仓维护者，我希望冗余报告忽略 frontmatter/YAML 结构行，只指出重复的规则正文。
- **US-03**：作为大仓维护者，我希望为"长 spec"设置项目自己的阈值，而不是被固定 500 tokens 刷屏。
- **US-04**：作为 CI 负责人，我希望给定一组改动文件，工具能算出真实的规范注入总量，并明确区分单次注入与全量聚合。
- **US-05**：作为 code-flow 维护者，我希望 `spec doctor` 能发现"domain 没有对应目录""spec 放错域目录"这类静默错误。
- **US-06**：作为大仓维护者，我希望 catalog 截断时明确告诉我丢了哪些域。
- **US-07**：作为在途任务负责人，我希望在拆分/移动 spec 前知道哪些 Context/任务会被影响。
- **US-08**：作为在途任务负责人，我希望工具保证结构优化不会悄悄改变 `RULE` id 或 verifier 引用。
- **US-09**：作为新使用者，我希望有一份标准 SOP，按步骤做规范优化而不是凭经验。

---

## 4. 功能需求

### 4.1 功能清单 [必填]

#### FEAT-01 路径引用多根解析（P0）

- `find_missing_paths` 在项目根、spec 目录之外，增加可配置/自动发现的源码根：
  - 自动发现：`apps/*/src/*`、`packages/*/src/*`、`lib/*/src/*`（存在才加入）。
  - 配置覆盖：`audit.path_roots: ["apps/console-platform/backend/src", ...]`。
  - 解析顺序：项目根 → spec 目录 → 配置根 → 自动发现根；全部失败才算 missing。
- 报告保留"按哪个根解析成功"的信息（JSON 字段，不改变人类可读文本结构）。
- 路径仍按原样展示（模块简写），不要求 spec 改写成绝对路径。

验收：S-01 / S-02 / E-01。

#### FEAT-02 审计降噪与可配阈值（P0）

- `find_redundant_lines` 排除：
  - frontmatter 块（首尾 `---` 之间）；
  - 纯 YAML 结构行：`stages:`、`- design|plan|code|review`、`enforcement:`、`verifiers:`、`type: command|test`、`tags:`、`tier:`。
- 新增 `audit.long_spec_tokens`（默认 500，保持兼容）；报告可显示"距单次注入目标还有多少"。
- 模板（`tags: []`）继续完全排除。

验收：E-02 / S-03。

#### FEAT-03 预算模拟命令（P0）

- 新增 `code-flow spec budget --paths <file...> [--json]`：
  - 用与 router 相同的 `build_effective_mapping` 与匹配逻辑；
  - 输出每个命中 spec 的估算 tokens、命中总和、`min(total, l1_max)` 上限、是否超限；
  - 明确区分 `matched_total`（单次编辑）与 `aggregate_total`（全部 spec 求和）。
- `stats` 的 warnings 使用同一口径：`L1 超出预算` 改为 `单次注入上限` 相关措辞，聚合值单独命名。
- 支持 `--changed` 读取 `git diff --name-only`（可选）。

验收：S-04 / E-03。

#### FEAT-04 domain 布局校验（P0）

- `spec doctor` 增加：
  - `path_mapping.<domain>` 必须存在 `specs/<domain>/` 目录；
  - 每个 spec 路径必须位于自己的 domain 目录下；
  - 发现"配置域无目录""目录内 spec 未登记""spec 跨目录声明"时给出明确错误/警告。
- 不自动修改配置；只诊断并给出修复建议。

验收：E-04 / E-05。

#### FEAT-05 catalog 截断可见（P1）

- `catalog_max` 超限时：
  - JSON 增加 `dropped_domains`/`dropped_count`；
  - 人类可读输出明确写"因预算未列出 N 个域：a, b, c"；
  - 提供 `--show-dropped`（或默认显示）列出被丢弃项。
- 不改变截断策略本身（Tier 1 优先），只让结果可见。

验收：S-05。

#### FEAT-06 规范影响面查询（P1）

- 新增 `code-flow spec impact <spec_id|path> [--json]`：
  - 扫描 `.code-flow/tasks/**/spec-context.yml` 与任务文档中的 `spec#rule` / spec 路径引用；
  - 输出受影响的 Context、任务、required rule、当前状态（verified/stale/unverified）；
  - 提示"改动后需要 `spec refresh`"。
- 只读，不修改任何任务文件。

验收：S-06。

#### FEAT-07 结构优化提案（P1）

- 新增 `code-flow spec optimize --dry-run [--paths ...] [--json]`：
  - 输入：当前 specs、path_mapping、可选的目标路径；
  - 输出：每份 spec 的 tokens、Rules/Conventions 占比、命中组合、拆分/合并建议（按大小与路径重叠）；
  - 若执行 `--apply`（仍需交互确认）：
    - 允许移动 Conventions 到新 spec 文件；
    - **禁止改变 `RULE` id**；守卫在应用前后对比 rule id 与 verifier 引用；
    - 输出 path_mapping diff 与预算前后对比；
    - 移动 spec 时强制检查目标 `specs/<domain>/` 目录与影响的 Context。
  - 默认不修改规则正文，不删除内容。

验收：S-07 / E-06 / E-07。

#### FEAT-08 文档与 SOP（P1）

- 新增 `docs/spec-optimization.md`：
  - 体检 → 修过期事实 → 去跨 spec 重复 → 单次注入超目标才拆 → 拆只动 Conventions → 跑 `spec refresh`；
  - 预算字段语义（L0/L1/total/catalog）；
  - 已知假阳性（模块简写、frontmatter）；
  - RULE id 稳定、domain=目录、Context 影响面三条硬约束。
- 更新 `cf-stats`、`cf-spec` 命令文档与四平台适配（内容归一化后一致）。

验收：S-08。

#### FEAT-09 测试与发布（P0）

- 单测：路径多根、frontmatter 排除、阈值配置、预算模拟、domain 布局、impact、optimize 的 rule-id 守卫。
- 适配：claude/codex/costrict/opencode 命令正文按既有归一化规则保持一致；`cf-sync check` 全绿。
- 版本：`CHANGELOG.md` 记录新增命令与配置；`src/core/code-flow/.version` 按发布策略更新。
- 不新增 npm 运行时依赖；Python 仅标准库。

验收：S-09 / E-08。

### 4.2 边缘情况 [可选]

- 仓库没有 `apps/*/src` / `packages/*/src`：自动发现为空，行为退回现状。
- spec 中路径含 glob（`*`/`{}`）：不参与存在性判断（沿用现状）。
- `catalog_max` 极小（< 单条）：仍输出至少 1 条并告警。
- `optimize --apply` 遇到 rule id 变化、verifier 引用丢失、目标目录不存在、在途 Context 受影响：默认拒绝并列出原因。
- 同一 spec 同时被多个 domain 引用：doctor 报"跨域声明"，不自动拆分。
- `spec impact` 在超大 `.code-flow/tasks` 上：限制扫描深度/文件数并报告截断。

---

## 5. 非功能需求 [可选]

- **NFR-01 兼容性**：新增配置缺省时行为与 0.8 一致；现有命令的 JSON 只增字段，不删/改名。
- **NFR-02 性能**：`spec budget` / `impact` 在 100 份 spec、1000 个任务文件的合成仓上 < 2s（不含 pytest）。
- **NFR-03 安全**：`optimize --apply` 只写 `.code-flow/specs/**` 与 `config.yml`，不碰任务文档、不删规则；写前备份可用 git status 证明。
- **NFR-04 可观测**：所有新检查在 `--json` 下给出稳定字段，便于 CI 消费。
- **NFR-05 四平台一致**：命令正文归一化 token 后逐字相同；不依赖平台特有能力。
- **NFR-06 零依赖**：CLI 不新增 npm 依赖；Python 不新增第三方依赖。

---

## 6. 范围与边界 [必填]

**范围内**：
- 上述 9 个 FEAT 的工具实现、测试、文档、四平台同步与发布记录。

**范围外**：
- 自动判断"规范与代码矛盾"或自动删除规则（留在 `cf-learn` 的证据对账 + 用户确认）。
- 自动决定拆分粒度/域命名/预算数值。
- 为具体项目（如 fluxion-harness）写死阈值或路径。
- 修改既有 `RULE` 文本、重编号或迁移历史任务 Context。
- 替代 `cf-learn` 全量扫描/`--review`/`--map`。

---

## 7. 依赖与风险 [可选]

### 7.1 项目依赖

- `codeflow.spec.cf_scan`（audit）、`codeflow.spec.cf_spec_router`（预算/匹配）、`codeflow.core.cf_core.build_effective_mapping`（domain 发现）。
- `codeflow.spec.cf_spec_context`（catalog/doctor/context）。
- 任务 Context 格式（`spec-context.yml`）与四平台适配器。

### 7.2 风险识别

| 风险 | 影响 | 缓解 |
|---|---|---|
| 多根解析把真死引用"救活" | 漏报 | 只加入**已存在**的源码根；报告中保留解析根；测试覆盖真死路径 |
| `optimize --apply` 改动规则 id | 在途任务 Gate 全红 | 应用前对比 rule id/verifier；不满足直接拒绝 |
| 预算口径变更影响 CI | 既有 CI 误判 | 旧字段保留，新字段增量；warning 措辞变更记录在 CHANGELOG |
| domain 校验过严 | 旧仓升级报错 | 默认 `warn`，配置 `spec_workflow.strict_domain_layout: true` 才 fail |
| 四平台文档漂移 | live 行为与源不一致 | 按 `cf-sync check` 作为发布门禁 |

---

## 8. Existing Spec Constraints

- `cli/code-standards.md#RULE-cli-dependency-allowlist-001`：不得新增未登记的运行时依赖。
- `cli/code-standards.md#RULE-cli-platform-parity-001`：四平台命令正文归一化后必须一致。
- `cli/code-standards.md#RULE-cli-hook-guard-001`：hook 在项目外必须 no-op。
- `cli/code-standards.md#RULE-cli-migration-transaction-001`：涉及运行时布局/迁移时必须保留 dry-run/journal/rollback 语义。
- `scripts/code-standards.md`：Python 脚本的异常处理、stdout JSON 协议与双副本同步约束。
- 项目 `CLAUDE.md`：`src/core/code-flow/` ↔ `.code-flow/`、`src/adapters/<p>/` ↔ `.<platform>/` 必须同步提交。

---

## 9. 验收场景

> 场景 ID 采用 `S-`（正常）/`E-`（异常/边界）；本轮只登记语义，具体命令在 design 阶段绑定。

| ID | 层级 | 场景 | 预期 |
|---|---|---|---|
| S-01 | unit | spec 引用 `application/x.py`，真实路径在 `apps/a/src/pkg/application/x.py` | 不报过时；报告解析根为 `apps/a/src/pkg` |
| S-02 | unit | spec 引用不存在的 `ghost/y.py` | 仍报过时 |
| E-01 | unit | 配置了错误的 `audit.path_roots` | 该根被忽略/告警；不回退成假绿 |
| E-02 | unit | 三个 spec 的 frontmatter 都有 `stages:`/`- design` | 冗余报告为空 |
| S-03 | unit | `audit.long_spec_tokens: 2500` | 2.4k spec 不报冗长，2.6k 报 |
| S-04 | integration | `spec budget --paths` 一个命中 ui+frontend+ui-detail 的前端文件 | 输出 matched_total≈5.2k，与 router 一致 |
| E-03 | integration | matched_total > min(total,l1_max) | 明确报超限并给出上限与命中明细 |
| E-04 | integration | `path_mapping.e2e` 存在但无 `specs/e2e/` | doctor 报错/警告并给出修复建议 |
| E-05 | integration | spec 放在 `test/` 却声明在 `e2e` 域 | doctor 报"spec 跨目录声明" |
| S-05 | integration | catalog 预算只够 11 条、共 22 域 | 输出列出 11 个被丢弃的域 |
| S-06 | integration | `spec impact harness-test` | 列出引用它的 Context/任务/required rule 与状态 |
| S-07 | integration | `spec optimize --dry-run` 对 6k spec 给拆分建议 | 输出前后 tokens、path_mapping diff、受影响 Context，且 rule id 集合不变 |
| E-06 | integration | `--apply` 会改变任一 rule id | 拒绝应用并列出差异 |
| E-07 | integration | 目标 `specs/<domain>/` 不存在 | 拒绝应用 |
| S-08 | docs | 按 `docs/spec-optimization.md` 在 fixture 仓执行 | 所有命令可复现，报告与预期一致 |
| S-09 | integration | `cf-sync check` + 四平台适配测试 | 全绿 |
| E-08 | integration | 新增配置缺省 | 0.8 行为不变，JSON 只增字段 |

---

## 10. 待确认

1. **命令归属**：`budget/impact/optimize` 放在 `code-flow spec` 下，还是 `cf-learn --structure`？建议 `spec`（确定性）与 `cf-learn`（语义候选）分工，本文按 `spec` 写。
2. **默认严格度**：domain 布局默认 `warn` 还是 `error`？建议先 `warn` 一个版本，再在下一 minor 开启。
3. **`optimize --apply` 是否首发**：建议先只发 `--dry-run`，`--apply` 在影响面/规则守卫测试完备后再开。
4. **路径根自动发现**：是否只认 `apps/*/src/*`、`packages/*/src/*`，还是允许项目自定义约定（如 `services/*/`）？建议自动发现上述两类 + `audit.path_roots` 覆盖。
