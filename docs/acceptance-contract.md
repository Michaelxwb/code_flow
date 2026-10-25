# 可执行验收契约

`scenarios parse --quality` 校验场景语义，`design lint` 校验设计引用，`acceptance manifest --verify-plan` 聚合完整计划门禁。旧文件继续可读；重新规划时必须修复门禁报告的缺口，不能把旧状态当成已验证。

## 场景与边界

浏览器关键旅程使用 `e2e`；API/CLI/后台服务完整链路使用 `system`，局部模块组合使用 `integration`。容量测试可使用 `capacity` 层级或 `tags: [capacity]`，并登记真实 capacity 用例。

```yaml
schema: 1
scenarios:
  - id: S-01
    title: 浏览器创建订单
    priority: P0
    level: e2e
    exec: deferred
    env: browser
    components: [browser, frontend, api, db]
    boundary: browser -> api -> db
    why_e2e: 真实浏览器登录态与后端订单提交必须联合验证
    preconditions: [用户已经登录]
    steps: [提交订单]
    expected: [订单出现在列表中且状态为 created]
    expected_refs: [{expected: 1, steps: [1]}]
    features: [FEAT-01]
    trigger_paths: [src/frontend/*, src/orders/*]
    smoke: true
    defer_reason: 在需求级终验执行真实浏览器链路
    owner: TASK-001
    target_phase: review
```

expected_refs 的 expected/steps 均从 1 开始。也可用 assertions 引用场景中已声明的稳定断言 ID；引用必须存在。条件式结果允许，但必须声明可构造的前置条件和确定的可观察结果。

环境枚举为 none/local/local-api/browser/external/staging/capacity/ci/production。components 使用稳定标识符，可使用项目模块 ID；浏览器 E2E 的组件声明必须与 boundary 相符。延后阶段为 plan/code/review/ci/release。

## 测试登记与收集

在 manifest 对应 check 上登记套件与具体用例。重新锁定计划会保留这些设置；更改设置使旧输入指纹失效。collect 使用 argv，不经过 shell，单条最多 60 秒、单次登记校验总预算 60 秒。

pytest 示例：项目应注册并实际使用 browser/smoke/capacity markers。

```json
{
  "suite": "browser",
  "test_ids": ["tests/test_orders.py::test_create_order"],
  "markers": ["browser", "smoke"],
  "collect": {
    "argv": ["python3", "-m", "pytest", "--collect-only", "-q", "-m", "browser and smoke"],
    "format": "pytest",
    "timeout": 20
  }
}
```

原生 pytest 收集仅接受明确的 marker 或 and 组合，拒绝无法证明每个已选用例都具有相应标记的 or/not 表达式。

Playwright 示例：使用明确的 chromium/firefox/webkit/browser 项目名称，或在项目 metadata 中声明 `capabilities: ["browser"]`；用例 tags 声明 @smoke/@capacity。test_ids 使用相对项目根目录的 `file:line@projectName`。适配器按[官方 JSON Reporter](https://github.com/microsoft/playwright/blob/main/packages/playwright/src/reporters/json.ts)的 rootDir、项目 metadata 和用例 tags 解析。

```json
{
  "suite": "browser",
  "test_ids": ["tests/orders.spec.ts:8@chromium"],
  "markers": ["smoke"],
  "collect": {
    "argv": ["npx", "playwright", "test", "--list", "--reporter=json"],
    "format": "playwright",
    "timeout": 30
  }
}
```

自定义收集器可使用 format=json，输出 `{"tests":[{"id":"具体用例ID","capabilities":["browser"],"markers":["smoke"]}]}`。适配器必须从真实测试框架收集结果生成此报告；静态编造报告不能证明测试边界。登记/收集只证明套件与用例可选，实际执行仍须经过契约声明的真实边界、关键断言与有效证据。

check 的 command 必须实际选择已登记的测试 ID、文件或匹配的 marker。不可证明选择范围的 -k/grep 过滤应改用具体用例 ID。npm/pnpm/yarn 脚本会解析到 package.json 中的直接命令；串联多个 shell 命令时请拆成 preflight 与测试 check，避免登记正确却执行了别的命令。

## ID、模板和规则证据

设计 frontmatter 设置 `design_template: lite|full|frontend` 中的实际模板值，再运行 `code-flow design lint --file <design> --scenarios-file <scenarios> --json`。多份设计重复 --file。检查未定义 FEAT/API/NFR、冲突 NFR、无场景功能、场景与功能错配及对应模板的必填章节。

doctor 会分别报告健康检查与各阶段 readiness。applied artifact 必须引用正确章节中的已完成条目；仅出现 Rule ID 或含有“待确认/TBD”的占位说明不构成证明。code/review 必须有执行证据。Conventions 中的关键约束应提升为 Rules；其余通过 convention_review_required 明确提示审查。

报告中的 e2e_browser_count/system_count/capacity_count 是声明分类；runnable_smoke_count/runnable_browser_count 来自真实收集校验。没有进行登记校验时 runnable 为 null，不伪装成已执行通过。
