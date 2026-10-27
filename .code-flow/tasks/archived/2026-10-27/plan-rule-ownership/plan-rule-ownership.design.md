---
design_template: lite
---

# Plan Rule 引用与责任归属

- 来源：运行时边界收敛计划的实际 Gate 与 Session 投影复现。
- 状态：设计草案；本需求是 runtime-boundary-hardening 的前置条件。

## 1. 文档控制

| 日期 | 内容 |
|------|------|
| 2026-10-27 | 明确共享适用规则与唯一验收负责人的区别 |

## 2. 需求分析

### 2.1 需求概述

当前 Plan Gate 将任意 TASK 中出现完整 Rule 引用都视作该 Rule 的负责人。同一 required Rule 对多个 TASK 适用时，完整声明会导致 `plan_owner_duplicate`；改为 `N/A` 又会使该 TASK 的 Session 投影缺失适用规则。需要分别表达适用引用和唯一计划负责人，保留 fail-closed 与旧计划兼容。

基线复现：运行时边界收敛草案按真实适用范围填写共享引用，并以 `Rule-Owner-Refs` 指定唯一负责人；现有 `spec gate --stage plan --artifact ...` 对四条共享 Rule 返回 `plan_owner_duplicate`。对临时副本把一个 TASK 的适用引用改成 `N/A` 后，该 TASK 的 Session 投影包含 0 条 required Rule。当前 Gate 尚不理解新 owner 字段，因此不能将其报通过。

### 2.2 功能方案

| 功能ID | 能力 | 优先级 | 验收场景 |
|--------|------|--------|---------|
| FEAT-01 | 多个 TASK 可引用同一 Rule，且只有明确负责人承担计划验证 | P1 | S-01, E-01 |
| FEAT-02 | 旧单负责人计划及各 TASK 的规则投影保持兼容 | P1 | S-02 |

### 2.3 范围与边界

| 范围 | 内容 |
|------|------|
| 本次包含 | TASK 字段、Plan Gate 的规则负责人识别、旧计划兼容和 Session 投影验证 |
| 本次不包含 | 改变 Rule enforcement、绕过 required Gate、修改浏览器验收或新增运行时依赖 |
| 后续动作 | 本需求完成后刷新并重验 runtime-boundary-hardening 的计划 |

### 2.4 验收条件

场景唯一源为同目录 `plan-rule-ownership.scenarios.md`。

| 规则 | 约束 | 场景 |
|------|------|------|
| RULE-01 | 每个 TASK 的 `Spec-Refs` 列出适用规则；`Rule-Owner-Refs` 声明该 TASK 负责的计划规则 | S-01 |
| RULE-02 | 每条 required 计划 Rule 必须有且仅有一个 owner；owner 必须同时引用该 Rule，并承担 verifier 与验收责任 | E-01 |
| RULE-03 | 未声明新字段的旧计划只有一个引用时沿用现有 owner 解释；多个引用无 owner 时阻断 | S-02 |

### 2.4.3 验证环境假设

使用 Python、PyYAML、pytest、临时 TASK 文档和真实 Context/Gate；不依赖浏览器或外部服务。

## 3. 技术设计

### 3.1 技术选型

复用现有 `cf_task_doc`、`cf_spec_gate` 与 `cf_spec_session`；按结构化 TASK 字段判断 owner，不复制 Spec 内容，也不通过字符串重命名隐藏引用。

### 3.2 架构设计

Gate 分别读取 `Spec-Refs` 和 `Rule-Owner-Refs`：所有引用参与各自 Session 投影；显式 owner 必须唯一且属于引用者。仅当整个任务文件均没有 `Rule-Owner-Refs` 字段时启用旧格式兼容：恰好一个引用者可继续作为 owner。只要任一 TASK 声明了新字段，所有 required 规则都必须显式指定 owner，`N/A` 表示该 TASK 不承担规则 owner。没有引用、多引用无 owner、多个 owner、owner 未引用或字段非法均阻断。保留 Rule-specific checklist、verifier 和验收检查。

### 3.3 接口设计

TASK Markdown 新增可选 `Rule-Owner-Refs` 字段，取值为完整 Rule 引用或 `N/A`。原有 `Spec-Refs` 语义不变。现有 CLI JSON、错误处理和固定入口保持兼容；新增诊断需清楚区分无 owner、多个 owner 与 owner 未引用。

### 3.4 性能与容量考量

复用已解析的 TASK 文档，每次 Gate 不新增跨文件扫描、持久缓存或常驻进程。

## 4. 风险与依赖

| 风险 | 应对 | 场景 |
|------|------|------|
| 共享引用被错误放行且没有负责人 | 负责人唯一性与引用一致性失败关闭 | E-01 |
| 旧计划无法验证 | 保持单引用旧计划语义，覆盖 Session 投影 | S-02 |

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计影响和落点 | 验证场景 |
|-----------|-------------|----------------|----------|
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | §3.3：Hook 协议不新增 stdout 调试输出 | S-02 |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | §3.2：显式处理解析和校验错误 | E-01 |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | §3.3：保持既有 Hook 入口与输出契约 | S-02 |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | §3.2：共享引用不改变 required Rule 的 fail-closed Gate | S-01, E-01, S-02 |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | §3.1：保持 canonical 与部署副本一致 | S-02 |

## 附录：术语表

适用引用决定 TASK Session 需要哪些规则；计划负责人负责该 Rule 的 verifier 与验收归属。
