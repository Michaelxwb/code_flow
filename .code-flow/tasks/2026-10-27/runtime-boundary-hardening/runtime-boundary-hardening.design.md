---
design_template: full
---

# 运行时边界收敛设计

- 基线：`main@d7e83c9`；设计根据本次会话的代码审计与用户要求整理。
- 状态：设计草案，具体执行计划和门禁结果以同目录任务文件与 Context 为准。
- 来源：[代码收敛审计](../../archived/2026-10-27/audit-followup/codebase-consolidation-audit.md)及当前依赖图、Stop 日志和回归测试复验。
- 计划前置条件：`plan-rule-ownership` 需求须先修复共享 Spec 引用被计为重复负责人；完成前本需求只能作为草案审阅，不能启动 TASK。

## 1. 文档控制

### 1.1 责任人

| 角色 | 职责 |
|------|------|
| 维护者 | 审查每批接口边界和合并结果 |
| 执行者 | 先完成场景测试，再实施和验证对应 TASK |

### 1.2 修订历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-10-27 | 将已讨论的依赖边界和 Stop 问题整理为可验证设计 |

## 2. 需求分析

### 2.1 需求概述

本次收敛剩余的架构守卫盲区、跨模块私有接口、两条已登记反向边、两个静态导入强连通分量和 Stop 旧路径噪声。目标是减少真实职责倒置，使已有工作流的状态、错误、安装和验收行为保持一致。

### 2.2 痛点与价值

| 现状 | 影响 |
|------|------|
| 15 条私有导入中既有现成公开 owner，也有需要共享业务语义的操作 | 修改时容易扩大影响面，单纯改名会暴露缺少前置条件的操作 |
| 6 模块与 3 模块静态 SCC 含延迟导入 | 模块职责交叉；这本身不证明启动时发生循环导入错误 |
| AST 守卫存在条件分支、模块属性、相对与动态导入的覆盖盲区 | allowlist 为空并不充分证明边界收敛 |
| Stop 将场景文档当作 TASK，读取归档前的日志路径时输出警告 | 已移动文档产生重复诊断，其他读取错误仍需保留 |

### 2.3 功能方案

| 功能ID | 能力 | 优先级 | 验收场景 |
|--------|------|--------|---------|
| FEAT-01 | 守卫识别受支持的真实导入形式及有意 shim | P1 | S-01, B-01 |
| FEAT-02 | Stop 识别场景文档和失效旧路径 | P1 | S-02, E-01 |
| FEAT-03 | 场景解析、manifest 基线和 schema 分层 | P1 | S-03, E-02 |
| FEAT-04 | 注册、场景选择与风险判断有明确 owner | P1 | S-04, S-05 |
| FEAT-05 | TASK 范围、合并冲突、证据和状态转换共享契约 | P1 | S-06, E-03 |
| FEAT-06 | Gate 与 Session 使用领域模型及统一判定 | P1 | S-07, E-04 |
| FEAT-07 | Context 刷新与工作流编排解除回边 | P1 | S-08, E-05 |
| FEAT-08 | 并行批次复用共享验证能力 | P1 | S-09, E-06 |
| FEAT-09 | 最终棘轮、安装和部署副本一致 | P1 | S-10, S-11 |

### 2.4 范围与边界

| 类别 | 内容 |
|------|------|
| 范围 | 上述九项能力、对应自动测试和必要的部署资源同步 |
| 非范围 | 新增面向用户的命令、浏览器功能、运行时外部依赖或持久缓存；为减少行数机械合并无关职责 |
| 约束 | 保留既有命令与 22 个固定入口 shim；不通过重标层级、延迟导入或改名绕过守卫 |
| 基线 | 2 条反向边、15 条 allowlist 条目；静态图中 6 和 3 模块 SCC；当前批次为 4 |

### 2.5 验收条件

#### 2.5.1 业务规则与约束

| 规则 | 内容 | 场景 |
|------|------|------|
| RULE-01 | 有条件导入、私有访问和歧义模块名均有可复现的守卫反例 | S-01, B-01 |
| RULE-02 | Stop 对旧路径消噪，同时保留真实读取错误和活动任务门禁 | S-02, E-01 |
| RULE-03 | 同一领域能力有明确 owner；保留基线校验、风险、证据和范围语义 | S-03, E-02, S-04, S-05, S-06, E-03 |
| RULE-04 | Gate、Context 和工作流保持 fail-closed 与原有状态迁移 | S-07, E-04, S-08, E-05 |
| RULE-05 | 批次 smoke 只验证已合并 owner，失败时保留现场 | S-09, E-06 |
| RULE-06 | 最终两类 allowlist 为空、batch 为 7、静态图无多模块 SCC，且真实入口与部署副本可用 | S-10, S-11 |

#### 2.5.2 功能验收场景

场景唯一源为同目录 `runtime-boundary-hardening.scenarios.md`；本设计的功能清单给出场景与功能的对应关系。所有链路使用 unit、integration 或 system 层，不涉及浏览器 E2E。

#### 2.5.3 非功能指标

不设未经测量的耗时目标。拆分前后比较相同输入的读文件次数和公开命令结果；不得引入无界测试收集、额外持久缓存或常驻进程。新文件必须有明确职责与依赖收益。

#### 2.5.4 验证环境假设

需要 Python、PyYAML、pytest、Node.js、npm 和 Git；system 场景使用临时项目、真实仓库或 npm 包。外部浏览器、服务、生产凭证与真实用户确认均不是本需求的测试依赖。

## 3. 技术设计

### 3.1 方案选型

采用小批次的 owner 收敛：优先复用已有模块，只有业务职责确实需要时新增模块；保留导入兼容窗口并用负向测试验证架构守卫。新增模块数不是验收目标。公共 API 应表达完整操作，禁止只去掉下划线作为收敛。

### 3.2 架构设计

- 守卫保留现有 stem-keyed 分层和到期棘轮，显式区分同名 shim 与实现；受支持的条件、相对、字面量动态导入和模块属性访问须被检测或明确拒绝。
- schema 负责记录结构和字段规则；场景源解析不依赖 CLI；绑定 TASK 的基线校验由能访问 manifest owner 的用例层负责。scenarios CLI 的迁移入口可以单向调用 manifest 提取。
- Gate 的共享状态判定、Session 投影和 Context refresh 分别拥有明确领域入口；调用方向必须避免 Context CLI 与 workflow service 互相依赖。
- 证据更新和 TASK 状态提升由带前置条件的操作承载；批次 smoke 与普通需求验证共享完整验证用例，不复制检查语义。
- 必须显式处理 `cf_task_parallel → cf_task_workflow`；不能仅调整层级表来隐藏该边。
- 各 TASK 的 `Spec-Refs` 应保留实际适用的共享 Rule；唯一计划负责人使用 `Rule-Owner-Refs` 单独声明，不能用 `N/A` 隐藏适用规则以使计划通过。

### 3.3 数据设计

不改变 Scenario、manifest schema、Context、marker、Evidence、run ledger 与 TASK 文档的既有持久化格式。保留 manifest 旧版自愈、accepted risk、deferred、owner 多选、check identity、路径范围和原有错误码；相关错误不得被替换为空结果。

### 3.4 接口设计

现有 `code-flow spec`、`task`、`acceptance`、`scenarios` 与 Stop Hook 的参数、退出码和 JSON 协议保持兼容。内部共享接口必须声明输入、输出、异常和状态前置条件；验证用例不暴露任意 Markdown 状态写入。入口 shim 的历史导入兼容按当前契约验证。

### 3.5 质量实现方案

每个场景先有可收集测试 ID；计划骨架使用严格 xfail，正式验收命令带 `--runxfail`，因此骨架执行会失败而不会形成通过证据。对应 TASK 必须先替换骨架为真实断言并记录 RED。测试分层覆盖真实文件、Git worktree、marker、manifest、CLI 子进程和必要的 npm 产物；不以源码字符串作为业务行为证据。验收仅在每批完成后运行，不在计划阶段执行生产逻辑或 E2E。

## 4. 部署与运维

### 4.1 部署架构

源目录与 `.code-flow/scripts/` 按既有同步和安装规则更新。若新增或移动运行时文件，使用现有 runtime 迁移流程更新安装清单并验证打包产物。

### 4.2 发布与回滚

按独立可回滚批次交付；每批运行对应场景与相关回归。最终批次验证真实安装与双副本一致；出现状态或协议差异时回滚该批次并保留证据。

### 4.3 监控告警

Stop stdout 保持协议 JSON 或静默；真实异常继续写 stderr。旧路径警告是否消除由测试断言，不新增常驻监控。

### 4.4 数据迁移

不要求用户迁移现有需求工件。manifest、Context、marker 与旧入口的兼容性用旧版本 fixture 和真实加载路径验证。

## 5. 风险与依赖

| 风险 | 应对 | 场景 |
|------|------|------|
| 守卫假阴性或为清零而改层级 | 合成负向样例加真实导入图，最终检查两类 allowlist | S-01, B-01, S-10 |
| 丢失旧版 manifest 或证据语义 | 固定旧数据、失败路径和自愈结果 | E-02, S-05, E-03 |
| 生命周期写入次序改变 | 真实临时项目验证成功和失败路径 | S-08, E-05 |
| 并行 smoke 范围扩大或丢失工作区 | 真实 worktree 验证过滤与失败保留 | S-09, E-06 |
| 包和部署副本遗漏新实现 | 实际打包安装并校验同步 | S-11 |

## 6. 需求追溯矩阵

场景定义由同目录场景源维护，任务覆盖、唯一 owner 与 check 由计划及 manifest 投影；本节不复制场景定义。

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计影响和落点 | 验证场景 |
|-----------|-------------|----------------|----------|
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | §3.5：Stop stdout 仅协议输出，诊断走 stderr | S-02, E-01 |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | §3.5：显式异常类型与诊断，正则 verifier 覆盖 Python 改动 | S-01, B-01 |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | §3.4：保留真实 Hook 输入、JSON 输出与静默 no-op | S-02, E-01 |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | §3.2：Context、Scope 与 required Gate 保持 fail-closed | S-08, E-05 |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | §4.1：canonical、部署副本与安装产物一致 | S-10, S-11 |

## 附录：术语表

SCC 为静态导入图的强连通分量；owner 指某项规则或能力的唯一责任入口；shim 为保持固定路径的薄入口。
