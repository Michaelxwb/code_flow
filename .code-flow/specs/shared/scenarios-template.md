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
    priority: P0            # P0 / P1 / P2；E2E 只允许 P0/P1 关键旅程
    level: E2E              # unit / component / contract / integration / E2E / manual
    exec: deferred          # auto / deferred / manual / aspirational
    env: browser            # none / local-api / db / browser
    components: [frontend, backend]
    boundary: 真实浏览器 → 入口代理 → API → PG
    preconditions: []
    steps: []              # E2E 必填：用户可复现步骤
    expected: []           # E2E 必填：用户可观察结果
    why_e2e: ""            # E2E 必填：为什么 unit/component/contract/integration 无法覆盖
    trigger_paths: []      # 非 smoke E2E 必填：命中这些源码路径才运行
    smoke: false           # true = 发布/冒烟必须运行的关键旅程
    design_refs:
      - backend design §3.2
      - frontend design §3.5
    rules: []
    checks: []              # plan 阶段绑定；一个场景可多个 check
```

> **测试层级决策**：UI 交互/布局/字段顺序 → `component`；DTO/OpenAPI/错误码 →
> `contract`；鉴权/事务/模块边界/进程内 API → `integration`；只有真实浏览器 +
> 真实后端 + 真实 DB/鉴权的关键旅程才用 `E2E`。E2E 不是“用户可见结果”的默认层。
>
> **E2E 质量门禁**：E2E 必须有 `why_e2e`、`boundary`、`steps`、`expected`，且
> 非 smoke 场景必须有 `trigger_paths`。`plan --verify-plan` 会失败关闭；`start`
> 只把当前 TASK 的 E2E + smoke E2E 放进 `e2e_plan`，其余保持 deferred。
