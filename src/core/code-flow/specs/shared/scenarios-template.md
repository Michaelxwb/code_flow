---
id: scenarios-template
description: Scenario-first acceptance source template (not auto-injected)
stages: [design]
enforcement: advisory
---

# {需求名} 验收场景

> 本文件是验收场景的唯一源。design 文档只写实现逻辑并引用场景 ID；任务文件只登记 owner 与执行命令。
>
> 以下是可通过场景质量检查的订单示例，使用时替换为本需求的真实行为与路径。将 YAML 放到 `<需求>.scenarios.md` 的 frontmatter 或作为整个 YAML 文件保存；不要把模板自身的 Spec 元数据当成场景源。`checks` 在 plan 生成真实 check ID 后绑定，空列表不能通过需要测试登记的 verify-plan。

```yaml
schema: 1
requirement: 订单创建
scenarios:
  - id: S-01
    title: 登录用户通过浏览器创建订单
    priority: P0            # P0 / P1 / P2；E2E 只允许 P0/P1 关键旅程
    level: e2e              # unit / component / contract / integration / system / capacity / e2e / manual
    exec: deferred          # auto / deferred / manual / aspirational
    env: browser            # none / local / local-api / browser / external / staging / capacity / ci / production
    components: [browser, frontend, api, db]
    boundary: 真实浏览器 → 订单 API → 数据库
    preconditions: [用户已登录，购物车含一件库存充足的商品]
    steps: [在浏览器点击提交订单]
    expected: [订单列表新增一条状态为 created 的订单]
    expected_refs: [{expected: 1, steps: [1]}]  # 从 1 开始，逐个 expected 引用步骤或已声明断言 ID
    why_e2e: 真实浏览器登录态与订单持久化跨前后端，需要联合验证
    trigger_paths: [src/frontend/*, src/orders/*]
    smoke: true             # check 与收集到的测试都必须登记 smoke marker
    defer_reason: 在需求终验阶段运行真实浏览器链路
    owner: TASK-001
    target_phase: review    # plan / code / review / ci / release
    features: [FEAT-01]
    design_refs: [API-01]    # 对应设计必须定义 FEAT-01 / API-01
    rules: []
    checks: []              # plan 阶段绑定；一个场景可多个 check
```

> **测试层级决策**：UI 交互/布局/字段顺序 → `component`；DTO/OpenAPI/错误码 →
> `contract`；鉴权/事务/模块边界/进程内 API → `integration`；API/CLI/后台全链路 →
> `system`；容量 → `capacity` 或 capacity 标签；只有真实浏览器 +
> 真实后端 + 真实 DB/鉴权的关键旅程才用 `E2E`。E2E 不是“用户可见结果”的默认层。
>
> **质量门禁**：E2E 必须声明浏览器 env/组件、匹配的 boundary、why_e2e、步骤和具体预期；非 smoke 必须有 trigger_paths。每个 expected 必须引用存在的步骤或断言，deferred 必须有原因、owner 与 target_phase。
>
> `scenarios parse --quality` 检查语义，`design lint` 检查设计 ID 闭环，`acceptance manifest --verify-plan` 还检查 Spec Gate 与真实测试登记/收集。start 按当前 TASK 的 E2E 与全局 smoke 生成 e2e_plan，不额外扩大本任务验收范围。收集通过不能替代真实执行证据；配置示例见工具文档 `docs/acceptance-contract.md`。
