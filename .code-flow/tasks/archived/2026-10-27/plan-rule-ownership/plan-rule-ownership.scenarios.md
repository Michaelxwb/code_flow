---
schema: 1
requirement: plan-rule-ownership
scenarios:
- id: S-01
  title: 共享规则引用与唯一负责人
  level: integration
  boundary: 真实 TASK 文档、Spec Context、Plan Gate 与 Session 投影
  priority: P1
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  preconditions:
  - 两个 TASK 引用同一 required Rule，只有一个显式声明 Rule-Owner-Refs
  steps:
  - 校验计划并分别生成两个 TASK 的 Session 投影
  expected:
  - Plan Gate 通过且两个投影均包含该 Rule，唯一 owner 的 verifier 与验收责任完整
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - plan-rule-ownership.design.md#2.4 验收条件
  rules:
  - RULE-01
  features:
  - FEAT-01
  checks:
  - CHK-0c5a475a2a34
- id: E-01
  title: 负责人缺失、重复或未引用时阻断
  level: unit
  boundary: 真实 TASK 文档解析与 Plan Gate
  priority: P1
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  preconditions:
  - 分别构造无 owner、两个 owner、owner 未引用规则的文档
  steps:
  - 逐个执行计划规则覆盖校验
  expected:
  - 三个文档均阻断并给出对应的 owner 诊断
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - plan-rule-ownership.design.md#2.4 验收条件
  rules:
  - RULE-02
  features:
  - FEAT-01
  checks:
  - CHK-8ea3127662db
- id: S-02
  title: 旧计划与任务投影保持兼容
  level: integration
  boundary: 旧格式 TASK 文档、真实 Gate、Session 与 CLI
  priority: P1
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  preconditions:
  - 旧计划未声明 Rule-Owner-Refs，分别包含单个和多个 Rule 引用
  steps:
  - 运行 Gate 和 Session 投影并读取 JSON 结果
  expected:
  - 单引用旧计划通过，多引用无显式 owner 的旧计划阻断，原有投影与 CLI 错误协议保持有效
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - plan-rule-ownership.design.md#2.4 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-02
  checks:
  - CHK-c82d0b4af802
---
