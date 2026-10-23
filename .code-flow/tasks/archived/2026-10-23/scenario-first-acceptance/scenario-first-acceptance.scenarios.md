---
schema: 1
requirement: scenario-first-acceptance
scenarios:
- id: S-01
  title: S-01
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 真实 scenarios.md + parser
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-2ce35a172ab3
- id: S-02
  title: S-02
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 两份 design 引用同一全局 ID
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-4b83da4ec908
- id: S-03
  title: S-03
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 真实 plan + coverage
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-cf9a3a7e3fb1
- id: S-04
  title: S-04
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 真实 manifest + 多 check
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-6c2b03e737a9
- id: S-05
  title: S-05
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 真实 design + scenarios + manifest
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-840d1d79290d
- id: S-06
  title: S-06
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 无 scenarios.md 的 0.8 需求
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-5fd490f59109
- id: E-01
  title: E-01
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 新需求缺少 scenarios.md
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-7a9e6baeea63
- id: E-02
  title: E-02
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: Coverage 引用未知场景
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-43845ce40756
- id: E-03
  title: E-03
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 同一 ID 两份冲突定义
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-5020ec0882e1
- id: B-01
  title: B-01
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 0.8 旧需求
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-281c779eb9d4
- id: B-02
  title: B-02
  priority: P1
  level: integration
  exec: auto
  env: none
  components: []
  boundary: 单域需求（仅后端）
  preconditions: []
  steps: []
  expected: []
  design_refs:
  - scenario-first-acceptance.design.md#2.5 验收条件
  rules: []
  checks:
  - CHK-971df35924d6
---

# Scenario-First Acceptance 验收场景
