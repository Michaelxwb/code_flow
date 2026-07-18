# Tasks: code-flow 前端支持与任务文档需求目录化

- **Source**: frontend-support-and-task-restructure.design.md
- **Created**: 2026-06-25
- **Updated**: 2026-07-18

## Proposal

让 code-flow 由 AI 命令动态识别项目组成并适配前端全链路（cf-init 检测配置、cf-learn 证据特化、align 扫描选型），不在静态模板硬编码框架清单；同时将任务文档重构为"需求目录"组织，支持前后端 design 分离、plan 多 design 合并与整目录归档。所有命令改动按 8 副本传播并受 parity 守门。

---

## Acceptance Coverage

| 场景ID | 责任 TASK | 测试层级 | 关键真实边界 | 状态 |
|--------|-----------|----------|--------------|------|
| S-01 | TASK-002 | integration | PRD 指令模板 + 需求目录路径契约 | verified |
| S-02 | TASK-003 | integration | align 域识别与双 design 输出契约 | verified |
| S-03 | TASK-004 | integration | plan 目录发现与多 design 合并契约 | verified |
| S-04 | TASK-005 | integration | archive 整需求目录分支 | verified |
| S-05 | TASK-010 | E2E | 真实 Codex Agent + Vue fixture + 安装后的 cf-init | verified |
| S-06 | TASK-010 | E2E | 真实 Codex Agent + 前端 PRD + 安装后的 align | verified |
| S-07 | TASK-010 | E2E | 真实 Codex Agent + components/services fixture + 安装后的 learn | verified |
| E-01 | TASK-010 | E2E | 真实 Codex Agent + React fixture + 安装后的 cf-init | verified |
| E-02 | TASK-007 | integration | checks 路径作用域排除 services | verified |
| E-03 | TASK-005 | integration | archive 旧扁平回退分支 | verified |
| B-01 | TASK-003 | integration | align 单域输出契约 | verified |

---

## TASK-001: design-frontend.md 中立模板 + 注册

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: frontend-support-and-task-restructure.design.md#2.3 功能方案, frontend-support-and-task-restructure.design.md#3.4 接口设计

### Description
新增框架中立的前端设计模板，作为 align 产出前端设计文档的脚手架；并注册到 shared 模板体系（非注入）。

### Checklist
- [x] 新增 `src/core/code-flow/specs/shared/design/design-frontend.md`：页面/路由、组件树与层级（容器/展示分离）、Props/Events 契约、状态设计与数据流、数据获取层(services)、UI 状态(loading/empty/error/success)、样式方案(tokens/响应式/样式与逻辑分离)、可访问性、交互验收场景；框架中立（React/Vue/Svelte 并列）
- [x] 同步部署副本 `.code-flow/specs/shared/design/design-frontend.md`
- [x] `config.yml`（src/core + .code-flow 两副本）`path_mapping.shared.specs` 追加该文件，`tags: []`、`tier: 1`
- [x] `cf-stats --audit` 验证其计入 TEMPLATES（不计预算、无质量告警）

### Log
- [2026-06-25] created (draft)
- [2026-06-25] started (in-progress)
- [2026-06-25] completed (done)

---

## TASK-002: cf-task:prd → 需求目录写入

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计
- **Acceptance-Refs**: S-01

### Description
prd 写路径由扁平 `tasks/<日期>/<name>.prd.md` 改为需求目录 `tasks/<日期>/<需求>/<需求>.prd.md`（首建需求目录）。

### Checklist
- [x] 改 `prd.md` Step 5 与"文件位置说明"：创建并写入 `tasks/<日期>/<需求>/<需求>.prd.md`
- [x] 更新 Step 6"下一步"提示路径
- [x] 传播 8 副本（claude→costrict 逐字 / opencode / codex skill + 4 deployed）
- [x] `test_adapter_parity` 通过

### Acceptance Contract

| 场景ID | 测试文件/用例 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|------|----------|----------|------|
| S-01 | `tests/test_cf_task_directory_workflow.py::test_s_01_prd_is_written_inside_its_demand_directory` | integration | canonical PRD command artifact | PRD 写入需求目录 | verified |

### Acceptance Evidence

| 场景ID | GREEN | 断言位置 | 状态 |
|--------|-------|----------|------|
| S-01 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:14` | verified |

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-003: cf-task:align → 需求目录 + 按域产出后缀 design + 前端模板

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#3.2 架构设计
- **Acceptance-Refs**: S-02, B-01

### Description
align 依自身 Step 2 代码库扫描动态识别需求触及的域（frontend/backend/通用），各域产出一份后缀 design 到需求目录；前端用 design-frontend 模板，后端/通用用 lite/full。

### Checklist
- [x] Step 2.5 加 design-frontend 分支（判定依据来自扫描，无人为 flag）+ 模板路径 + 章节映射(Frontend)
- [x] Step 4/5 按域产出 `<req>.frontend.design.md` / `<req>.backend.design.md` / `<req>.design.md`（单域/通用）
- [x] 写入需求目录（PRD 派生模式复用 PRD 所在需求目录）
- [x] 传播 8 副本（含 codex Step 5 单独适配 apply_patch/cf-task-archive）
- [x] `test_adapter_parity` 通过

### Acceptance Contract

| 场景ID | 测试文件/用例 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|------|----------|----------|------|
| S-02 | `tests/test_cf_task_directory_workflow.py::test_s_02_b_01_align_names_full_stack_and_single_domain_designs` | integration | canonical align command artifact | 全栈输出 frontend/backend designs | verified |
| B-01 | 同上 | integration | canonical align command artifact | 单域输出一份 design | verified |

### Acceptance Evidence

| 场景ID | GREEN | 断言位置 | 状态 |
|--------|-------|----------|------|
| S-02 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:20` | verified |
| B-01 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:20` | verified |

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-004: cf-task:plan → 需求目录入参 + 多 design 合并

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#2.5 验收条件
- **Acceptance-Refs**: S-03

### Description
plan 支持传需求目录，自动发现目录内全部 `*.design.md`（FE+BE），合并拆解为一份 `<需求>.md`，各 TASK 的 Source 指向其来源 design。

### Checklist
- [x] Step 1 输入支持需求目录：Glob `<dir>/*.design.md` 发现全部 design，逐个 Read（codex 用 rg/find）
- [x] Step 3/4 合并拆解为一份任务文件，TASK Source 区分来源（`<req>.frontend.design.md#…` / `<req>.backend.design.md#…`）
- [x] Step 5 写入需求目录 `<需求>.md`
- [x] 传播 8 副本（含 codex 单独适配 rg/apply_patch）
- [x] `test_adapter_parity` 通过（验收对应 S-03）

### Acceptance Contract

| 场景ID | 测试文件/用例 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|------|----------|----------|------|
| S-03 | `tests/test_cf_task_directory_workflow.py::test_s_03_plan_merges_all_designs_into_one_task_file` | integration | canonical plan command artifact | 发现全部 design 并合并为一份 task | verified |

### Acceptance Evidence

| 场景ID | GREEN | 断言位置 | 状态 |
|--------|-------|----------|------|
| S-03 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:28` | verified |

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-005: cf-task:archive → 整需求目录归档 + 旧扁平回退

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#2.5 验收条件
- **Acceptance-Refs**: S-04, E-03

### Description
archive 检测目标任务文件位于需求目录则整目录 `mv` 到 `archived/<日期>/<需求>/`；旧扁平布局回退现有逐文件归档（向后兼容）。

### Checklist
- [x] Step 3 加分支：需求目录 → 整目录归档；扁平 → 逐文件归档（保留 .prd/.design 配对逻辑）
- [x] _session 临时约束清理逻辑沿用
- [x] 传播 8 副本（含 codex 单独适配 shell/cf-task-start 措辞）
- [x] `test_adapter_parity` 通过（验收对应 S-04、E-03）

### Acceptance Contract

| 场景ID | 测试文件/用例 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|------|----------|----------|------|
| S-04 | `tests/test_cf_task_directory_workflow.py::test_s_04_e_03_archive_supports_directory_and_flat_layouts` | integration | canonical archive command artifact | 需求目录整目录归档 | verified |
| E-03 | 同上 | integration | canonical archive command artifact | 旧扁平布局逐文件回退 | verified |

### Acceptance Evidence

| 场景ID | GREEN | 断言位置 | 状态 |
|--------|-------|----------|------|
| S-04 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:36` | verified |
| E-03 | 场景用例 PASS | `tests/test_cf_task_directory_workflow.py:36` | verified |

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-006: cf-init → 动态 frontend.patterns + shared 清单

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: frontend-support-and-task-restructure.design.md#3.2 架构设计, frontend-support-and-task-restructure.design.md#2.5 验收条件

### Description
cf-init 按 Step 1 检测到的框架动态补 `frontend.patterns`（Vue→`**/*.vue`、Svelte→`**/*.svelte`、Next→`app/**` 等，属保守修补）；静态 baseline 保持中立。shared 模板清单加入 design-frontend.md。

### Checklist
- [x] cf-init 步骤 2 加"按检测框架补 frontend.patterns"指引（不全塞，按检测）
- [x] cf-init 步骤 4「shared 模板必须存在」清单加 `shared/design/design-frontend.md`
- [x] 传播 8 副本（4 平台各自 src→deployed；cf-init 跨平台非逐字）
- [x] `test_adapter_parity` + `test_cf_init_docs` 通过

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-007: cf-learn → 注入覆盖漂移 + 前端采集/checks 生成指引

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: frontend-support-and-task-restructure.design.md#3.2 架构设计, frontend-support-and-task-restructure.design.md#3.5 质量实现方案, frontend-support-and-task-restructure.design.md#2.5 验收条件
- **Acceptance-Refs**: E-02

### Description
cf-learn §1.5 域漂移检测增加"注入覆盖漂移"（实际前端文件类型未被 patterns 覆盖则提示补齐）；§2/§3 增加前端维度采集（代码分层、组件复用、样式与接口调用分离）与 checks 动态生成指引，含精度护栏。

### Checklist
- [x] §1.5 加"注入覆盖漂移"检测项（走既有确认门）
- [x] §2 采集补前端维度：services/hooks 边界、容器/展示、复用 hook/composable、组件内无裸 fetch、样式 tokens/CSS Modules
- [x] §3 checks 生成指引：前端可正则规则动态生成 checks 草稿
- [x] 精度护栏：checks `files` 用路径作用域(`*components*`/`*pages*`)避开 `services/`（fnmatch 跨 `/`）
- [x] 传播 8 副本（验收对应 S-07、E-02）

### Acceptance Contract

| 场景ID | 测试文件/用例 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|------|----------|----------|------|
| E-02 | `tests/test_cf_learn_docs.py::test_cf_learn_templates_frontend_dimensions` | integration | 4 平台 cf-learn artifacts | checks 路径限定 components/pages，不误伤 services | verified |

### Acceptance Evidence

| 场景ID | GREEN | 断言位置 | 状态 |
|--------|-------|----------|------|
| E-02 | 场景用例 PASS | `tests/test_cf_learn_docs.py:121` | verified |

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-008: frontend specs 强化（分层/复用/样式-接口分离）

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: frontend-support-and-task-restructure.design.md#2.3 功能方案

### Description
强化前端约束 specs，针对用户三诉求补框架中立 ✅/❌ 示例，作为 cf-learn 特化的起点。

### Checklist
- [x] `directory-structure.md`：强化 services 层契约（三层分离 ✅/❌；组件/hook/composable 内禁裸 fetch/axios）
- [x] `component-specs.md`：容器/展示分离 ✅/❌、复用 hook/composable、样式走 token 且不与数据获取混在同一组件
- [x] 同步部署副本（N/A：本项目 .code-flow 为 cli/scripts 域，无 frontend 部署副本；仅改 src/core 模板）

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-009: 文档同步 + 测试收尾

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008
- **Source**: frontend-support-and-task-restructure.design.md#2.5 验收条件, frontend-support-and-task-restructure.design.md#3.5 质量实现方案

### Description
同步用户文档与新增/更新自动化测试，全量回归绿。

### Checklist
- [x] `CLAUDE.md` + `AGENTS.md`（adapter 模板 4 平台 + 本项目部署副本）Task Documents 段更新需求目录工作流
- [x] `docs/USAGE.md` 同步需求目录布局（prd/align/plan/archive 路径）+ 前端 design-frontend 流程
- [x] 测试：`test_cf_init_docs` 断言 design-frontend.md + 动态 patterns；新增 `test_cf_learn_templates_frontend_dimensions`（注入漂移/前端专项/checks 护栏）；`test_adapter_parity` 全覆盖
- [x] 端到端手验：TASK-010 已用真实 Codex 0.144.4 完成 Vue/React cf-init、frontend align 与 cf-learn 走查
- [x] 全量回归：历史实现阶段 `pytest -q` 279 passed；归档复核 `pytest -q` 236 passed，`node --test tests/*.js` 13+7 passed

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-010: schema-v1 初始化契约修正 + 真实 Agent 验收

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-009
- **Source**: frontend-support-and-task-restructure.design.md#7 归档复核修正（2026-07-18）
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-migration-transaction-001, scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-05, S-06, S-07, E-01

### Description
修正 schema-v1 迁移后残留的 `cf-init` 旧字段/旧 hook 指令，补齐 Codex PreToolUse、前端 service/composable 注入覆盖、refresh-before-active 顺序与 artifact ref 幂等更新，并以真实 Codex Agent 覆盖 Vue、React、align、learn 四条 prompt 驱动边界。

### Checklist
- [x] verifier `pytest -q tests/test_cli_init_codex.py tests/test_adapter_parity.py`：`cli-code-standards#RULE-cli-dependency-allowlist-001`（不新增依赖）。
- [x] verifier `pytest -q tests/test_cli_init_codex.py`：`cli-code-standards#RULE-cli-user-content-preservation-001`（merge/初始化保留用户配置）。
- [x] verifier `pytest -q tests/test_cf_init_docs.py tests/test_adapter_parity.py`：`cli-code-standards#RULE-cli-platform-parity-001`（canonical/deployed parity）。
- [x] verifier `pytest -q tests/test_hook_command_robustness.py tests/test_cli_init_codex.py`：`cli-code-standards#RULE-cli-hook-guard-001`（guarded project resolution）。
- [x] verifier `pytest -q tests/test_cli_init_codex.py`：`cli-code-standards#RULE-cli-migration-transaction-001`（本修正不改变 breaking migration/版本提交路径）。
- [x] verifier `pytest -q tests/test_hook_command_robustness.py`：`scripts-code-standards#RULE-scripts-no-print-debug-001`（hook stdout 仍为 JSON/静默）。
- [x] verifier `pytest -q tests/test_hook_command_robustness.py`：`scripts-code-standards#RULE-scripts-no-bare-except-001`（不引入裸异常吞噬）。
- [x] verifier `pytest -q tests/test_hook_command_robustness.py tests/test_cli_init_codex.py`：`scripts-code-standards#RULE-scripts-hook-protocol-001`（PreToolUse 协议与 guard）。
- [x] verifier `pytest -q tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py`：`scripts-code-standards#RULE-scripts-context-gate-001`（Context fail-closed 不回退）。
- [x] verifier `pytest -q tests/test_adapter_parity.py tests/test_cf_init_docs.py`：`scripts-code-standards#RULE-scripts-canonical-parity-001`（无 legacy runtime residue）。
- [x] 更新 4 平台 canonical/deployed `cf-init`，以 verifier `tests/test_cf_init_docs.py` 守住 schema-v1 字段、现行 hook 集合和 8 副本 parity（覆盖全部 cli/scripts required Spec-Refs）。
- [x] 在 canonical/deployed Codex `hooks.json` 注册 PreToolUse，使用现有 guarded command，不恢复 SessionStart；以 `tests/test_cli_init_codex.py` 和 hook robustness verifier 验证。
- [x] 核心前端模板补 `src/services/**` 与 `src/composables/**`，由 `tests/test_cf_core.py` 和 `tests/test_spec_workflow_templates.py` 验证真实域匹配。
- [x] 8 份 `cf-task-start` 改为 refresh-before-active，由 `tests/test_cf_spec_session.py` 与 parity 验证。
- [x] Context application 按 artifact/section/item 幂等替换旧哈希并去重，由 `tests/test_cf_spec_context.py::test_reapplying_artifact_slot_replaces_stale_hash` 验证。
- [x] 运行 `pytest -q tests/test_cf_init_docs.py tests/test_cli_init_codex.py tests/test_adapter_parity.py tests/test_hook_command_robustness.py`。
- [x] 真实 Codex Agent 在隔离 Vue/React fixture 执行 cf-init，并按落盘文件验证 S-05/E-01。
- [x] 真实 Codex Agent 在隔离前端需求/代码 fixture 执行 align 与 learn，并按产物/确认门验证 S-06/S-07。

### Acceptance Contract

| 场景ID | 测试文件/记录 | 用例/命令 | 层级 | 真实边界 | 预期结果 | 状态 |
|--------|---------------|-----------|------|----------|----------|------|
| S-05 | task Evidence | `codex exec ... '$cf-init frontend --skip-learn'` | E2E | real Codex + installed skill + Vue fixture | patterns 含 `**/*.vue`，无旧 inject 字段 | verified |
| E-01 | task Evidence | `codex exec ... '$cf-init frontend --skip-learn'` | E2E | real Codex + installed skill + React fixture | patterns 不含 `.vue` | verified |
| S-06 | task Evidence | `codex exec ... '$cf-task-align <prd>'` | E2E | real Codex + installed skill + frontend PRD | 产出 frontend design 并含模板核心章节 | verified |
| S-07 | task Evidence | `codex exec ... '$cf-learn'` | E2E | real Codex + installed skill + frontend code | 候选来自真实证据，写入经过确认门 | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|--------------|------|
| S-05 | FAIL: 真实 Codex 追查已删除 SessionStart，未写入 Vue pattern | PASS: Vue patterns 含 `**/*.vue`，config 无 `inject`，PreTool hook 存在 | fixture `.code-flow/config.yml` / `.codex/hooks.json` 独立断言 | `/tmp/code-flow-agent-e2e-green.EQb3yP/vue-demo`，Codex 0.144.4，进程 exit 0 | verified |
| E-01 | 同源旧初始化契约会阻断完成 | PASS: React patterns 不含 `.vue`，config 无 `inject` | fixture `.code-flow/config.yml` 独立断言 | `/tmp/code-flow-agent-e2e-green.EQb3yP/react-demo`，真实 Codex 进程 exit 0 | verified |
| S-06 | N/A：已有 prompt 行为，补真实边界证据 | PASS: 产出 389 行 frontend design，§3.2~3.8 与 Compliance Matrix 完整，Design Gate pass | `product-catalog.frontend.design.md:132`、`:355` + `cf_spec_gate.py --stage design` | React fixture + installed `cf-task-align` + real Codex session | verified |
| S-07 | FAIL: live learn 发现 service/composable 未命中 frontend patterns | PASS: 4 fixture tests；输出 6 类候选/对账项和 2 条 checks；Specs 哈希前后相同；模板路径匹配测试通过 | `tests/test_cf_core.py::test_frontend_template_matches_service_and_composable_files`、`tests/test_spec_workflow_templates.py::test_frontend_template_routes_layered_javascript_files_to_frontend_specs` | Vue service→composable→component fixture + real `cf-learn`，确认门写入 0 | verified |

### Log
- [2026-07-18] created (draft) during archive review
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)
