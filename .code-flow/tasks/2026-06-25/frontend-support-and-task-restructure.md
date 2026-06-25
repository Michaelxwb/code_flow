# Tasks: code-flow 前端支持与任务文档需求目录化

- **Source**: frontend-support-and-task-restructure.design.md
- **Created**: 2026-06-25
- **Updated**: 2026-06-25

## Proposal

让 code-flow 由 AI 命令动态识别项目组成并适配前端全链路（cf-init 检测配置、cf-learn 证据特化、align 扫描选型），不在静态模板硬编码框架清单；同时将任务文档重构为"需求目录"组织，支持前后端 design 分离、plan 多 design 合并与整目录归档。所有命令改动按 8 副本传播并受 parity 守门。

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

### Description
prd 写路径由扁平 `tasks/<日期>/<name>.prd.md` 改为需求目录 `tasks/<日期>/<需求>/<需求>.prd.md`（首建需求目录）。

### Checklist
- [x] 改 `prd.md` Step 5 与"文件位置说明"：创建并写入 `tasks/<日期>/<需求>/<需求>.prd.md`
- [x] 更新 Step 6"下一步"提示路径
- [x] 传播 8 副本（claude→costrict 逐字 / opencode / codex skill + 4 deployed）
- [x] `test_adapter_parity` 通过

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-003: cf-task:align → 需求目录 + 按域产出后缀 design + 前端模板

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#3.2 架构设计

### Description
align 依自身 Step 2 代码库扫描动态识别需求触及的域（frontend/backend/通用），各域产出一份后缀 design 到需求目录；前端用 design-frontend 模板，后端/通用用 lite/full。

### Checklist
- [x] Step 2.5 加 design-frontend 分支（判定依据来自扫描，无人为 flag）+ 模板路径 + 章节映射(Frontend)
- [x] Step 4/5 按域产出 `<req>.frontend.design.md` / `<req>.backend.design.md` / `<req>.design.md`（单域/通用）
- [x] 写入需求目录（PRD 派生模式复用 PRD 所在需求目录）
- [x] 传播 8 副本（含 codex Step 5 单独适配 apply_patch/cf-task-archive）
- [x] `test_adapter_parity` 通过

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-004: cf-task:plan → 需求目录入参 + 多 design 合并

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#2.5 验收条件

### Description
plan 支持传需求目录，自动发现目录内全部 `*.design.md`（FE+BE），合并拆解为一份 `<需求>.md`，各 TASK 的 Source 指向其来源 design。

### Checklist
- [x] Step 1 输入支持需求目录：Glob `<dir>/*.design.md` 发现全部 design，逐个 Read（codex 用 rg/find）
- [x] Step 3/4 合并拆解为一份任务文件，TASK Source 区分来源（`<req>.frontend.design.md#…` / `<req>.backend.design.md#…`）
- [x] Step 5 写入需求目录 `<需求>.md`
- [x] 传播 8 副本（含 codex 单独适配 rg/apply_patch）
- [x] `test_adapter_parity` 通过（验收对应 S-03）

### Log
- [2026-06-25] created (draft)
- [2026-06-26] started + completed (done)

---

## TASK-005: cf-task:archive → 整需求目录归档 + 旧扁平回退

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: frontend-support-and-task-restructure.design.md#3.4 接口设计, frontend-support-and-task-restructure.design.md#2.5 验收条件

### Description
archive 检测目标任务文件位于需求目录则整目录 `mv` 到 `archived/<日期>/<需求>/`；旧扁平布局回退现有逐文件归档（向后兼容）。

### Checklist
- [x] Step 3 加分支：需求目录 → 整目录归档；扁平 → 逐文件归档（保留 .prd/.design 配对逻辑）
- [x] _session 临时约束清理逻辑沿用
- [x] 传播 8 副本（含 codex 单独适配 shell/cf-task-start 措辞）
- [x] `test_adapter_parity` 通过（验收对应 S-04、E-03）

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

### Description
cf-learn §1.5 域漂移检测增加"注入覆盖漂移"（实际前端文件类型未被 patterns 覆盖则提示补齐）；§2/§3 增加前端维度采集（代码分层、组件复用、样式与接口调用分离）与 checks 动态生成指引，含精度护栏。

### Checklist
- [x] §1.5 加"注入覆盖漂移"检测项（走既有确认门）
- [x] §2 采集补前端维度：services/hooks 边界、容器/展示、复用 hook/composable、组件内无裸 fetch、样式 tokens/CSS Modules
- [x] §3 checks 生成指引：前端可正则规则动态生成 checks 草稿
- [x] 精度护栏：checks `files` 用路径作用域(`*components*`/`*pages*`)避开 `services/`（fnmatch 跨 `/`）
- [x] 传播 8 副本（验收对应 S-07、E-02）

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
- [~] 端到端手验：覆盖于文档断言 + 单测（parity/init/learn 跨平台一致、--audit 模板核对）；完整 live 走查（真实 Vue/React 项目）需用户在目标项目执行
- [x] 全量 `pytest -q`（279 passed）+ `node --test`（13 passed）绿

### Log
- [2026-06-25] created (draft)
