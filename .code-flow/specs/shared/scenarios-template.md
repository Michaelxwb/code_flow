---
id: scenarios-template
description: Scenario-first acceptance source template (not auto-injected)
stages: [design]
enforcement: advisory
---

# {需求名} 验收场景

> 本文件是验收场景的唯一源。design 文档只写实现逻辑并引用场景 ID；任务文件只登记 owner 与执行命令。

```yaml
schema: 1
requirement: {需求名}
scenarios:
  - id: S-01
    title: 用户旅程标题
    priority: P0            # P0 / P1 / P2
    level: E2E              # unit / integration / E2E / manual
    exec: deferred          # auto / deferred / manual / aspirational
    env: browser            # none / local-api / db / browser
    components: [frontend, backend]
    boundary: 真实浏览器 → 入口代理 → API → PG
    preconditions: []
    steps: []
    expected: []
    design_refs:
      - backend design §3.2
      - frontend design §3.5
    rules: []
    checks: []              # plan 阶段绑定；一个场景可多个 check
```
