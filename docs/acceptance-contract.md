# 可执行验收契约

`scenarios parse --quality` 校验场景语义，`design lint` 校验设计引用，`acceptance manifest --verify-plan` 聚合完整计划门禁。旧文件继续可读；重新规划时必须修复门禁报告的缺口，不能把旧状态当成已验证。

本页描述仓库 0.8.0 实现。安装与事务升级见 [README](../README.md#升级)和[迁移指南](migrations/runtime-0.8.0.md)；常规流程见[使用手册](USAGE.md)。

## 场景与边界

浏览器关键旅程使用 `e2e`；API/CLI/后台服务完整链路使用 `system`，局部模块组合使用 `integration`。容量测试可使用 `capacity` 层级或 `tags: [capacity]`，并登记真实 capacity 用例。

```yaml
schema: 1
requirement: 订单创建
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
    design_refs: [API-01]
    trigger_paths: [src/frontend/*, src/orders/*]
    smoke: true
    defer_reason: 在需求级终验执行真实浏览器链路
    owner: TASK-001
    target_phase: review
```

expected_refs 的 expected/steps 均从 1 开始。也可用 assertions 引用场景中已声明的稳定断言 ID；引用必须存在。条件式结果允许，但必须声明可构造的前置条件和确定的可观察结果。

环境枚举为 none/local/local-api/browser/external/staging/capacity/ci/production。components 使用稳定标识符，可使用项目模块 ID；浏览器 E2E 的组件声明必须与 boundary 相符。延后阶段为 plan/code/review/ci/release。

| 字段 | 约束 |
|------|------|
| `level` | unit / component / contract / integration / system / capacity / e2e / manual；输入 E2E 会归一为 e2e |
| `env` / `components` | 浏览器 E2E 要求 env=browser，或组件包含 frontend/browser；boundary 同时描述浏览器边界。数据库用组件 db/pg 表达，env 不接受 db |
| `expected` / `expected_refs` | 每个结果都引用存在的步骤或断言；拒绝“不回归”“提升可观”等模糊结果。性能结果给出负载、测量窗口与阈值 |
| `exec: deferred` | 必须有 defer_reason、owner、target_phase；延期仍须满足场景质量与计划登记检查 |
| `features` / `design_refs` | 分别引用功能 ID 与设计位置/ID，ID 必须在本需求设计中定义 |
| `checks` | plan 生成实际 check ID 后绑定；一个场景可绑定多个 checks，全部成员都需要各自的有效证据 |

条件式预期可以使用，但应先定义可构造的前置条件，再写确定结果，例如“库存为零时提交订单，显示错误码 OUT_OF_STOCK”。`assertions` 引用示例为 `assertions: [ASSERT-order-created]` 配合 `expected_refs: [{expected: 1, assertions: [ASSERT-order-created]}]`；断言 ID 的存在性检查不能替代断言实际执行。

### 对应的最小设计

将上述 YAML 保存为 `order.scenarios.md`（也可放入文件 frontmatter），下例保存为 `order.design.md`。design 只引用场景 ID，不复制完整验收表。

```markdown
---
design_template: lite
---
# 订单创建设计

## 需求概述
登录用户通过浏览器提交订单。

## 功能方案
| 功能ID | 名称 |
|--------|------|
| FEAT-01 | 创建订单 |

| 接口ID | 定义 |
|--------|------|
| API-01 | POST /orders，成功返回 201 和订单 ID |

## 范围与边界
包含浏览器登录态、订单 API 与数据库持久化，支付功能延期。

## 验收条件
| 场景ID | 功能ID | 接口ID |
|--------|--------|--------|
| S-01 | FEAT-01 | API-01 |
```

```bash
code-flow scenarios parse --file order.scenarios.md --quality --json
code-flow design lint --file order.design.md --scenarios-file order.scenarios.md --json
```

这些命令检查语义和引用；计划通过还需要真实任务、冻结的 Context、manifest 和测试登记。

## 规则引用与计划负责人

每个 TASK 的 `Spec-Refs` 列出实际适用的规则，供该任务的 Session 投影使用。承担计划验证的 TASK 还在 `Rule-Owner-Refs` 中列出对应规则；其他任务可引用同一规则，并用 `Rule-Owner-Refs: N/A` 表示不承担该规则的计划责任。每条 required 规则必须有且仅有一个负责人，且负责人本身必须引用该规则并提供 verifier 和验收契约。

当整个任务文件都没有 `Rule-Owner-Refs` 时，旧计划仍按单个引用者作为负责人的规则校验；一旦任一 TASK 声明该字段，所有 required 规则都需要显式负责人。缺失、重复、未引用或格式无效的负责人会阻断计划。

## 测试登记与收集

锁定时加 `--register-checks`，工具从 pytest / Playwright 的真实收集结果登记套件、具体用例、markers 和 collect。默认收集超时 10 秒，登记总预算 60 秒；只收集，不执行测试体。登记失败会保留原锁文件并输出具体 check、命令和错误。重新锁定会保留登记设置，更改设置使旧输入指纹失效。

pytest 示例：项目应注册并实际使用 browser/smoke/capacity markers。

```json
{
  "command": ["python3", "-m", "pytest", "-q", "tests/test_orders.py::test_create_order"],
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
  "command": ["npx", "playwright", "test", "tests/orders.spec.ts:8", "--project=chromium"],
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

上面的 JSON 是对应 check 的字段片段。使用项目自定义收集器时，先生成 manifest 获取真实 check ID，将登记字段放入独立文件，再通过正式命令写入：

```json
{"checks":{"CHK-实际ID":{"suite":"browser","test_ids":["tests/orders.spec.ts:8@chromium"],"markers":["smoke"],"collect":{"argv":["node","scripts/collect-tests.js"],"format":"json","timeout":20}}}}
```

```bash
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json" --registration-file registration.json
```

`--registration-file` 同样执行真实收集和执行选择校验；只允许修改登记字段，未知 check ID 会报错。capacity check 与收集到的用例都需要 capacity marker，smoke 同理。

## 计划到终验

在已完成 plan 的真实需求上使用以下入口；将尖括号路径替换为本项目路径：

```bash
# 生成或重新锁定 manifest；沿用项目实际命名的场景源
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json" --scenarios-file "<需求>.scenarios.md" --register-checks
# 同步已修改工件的引用哈希，再执行完整计划门禁
code-flow spec refresh --task-dir "<需求目录>" --root "$PWD" --json
code-flow acceptance manifest --verify-plan --require-scenarios --task-dir "<需求目录>" --task-file "<任务文件>"
# 开发期间只跑 validators，允许任务进行中，不推进状态
code-flow task verify --task-dir "<需求目录>" --checks --profile full --root "$PWD" --json
# 全层终验：按当前输入执行或复用有效证据
code-flow task verify --task-dir "<需求目录>" --layers validators,review,e2e --profile full --root "$PWD" --json
```

`--require-scenarios` 用于明确要求场景源；即使不传，`--verify-plan` 也始终检查 manifest 基线、场景语义、实际登记/收集、设计闭环和 plan Spec Gate。已有场景源会被自动发现。新锁文件声明 `quality_schema: 2`，start 复核当前质量和登记；旧锁文件缺少该版本时，start 保留原 E2E 门禁并输出 `legacy_quality_schema` 警告，提示补字段并重锁，不宣称新质量检查通过。

显式 `exec: deferred` 的 E2E 保留在 owned/smoke 提示中，编码阶段不进入 scheduled，也不执行登记收集；完整 verify-plan 仍检查其质量和登记，需求终验再执行。Done 的 integration/system/capacity 延后场景也可保留 e2e_deferred；verified 必须闭环。并行批次只运行本批 TASK 的场景，需求终验继续覆盖整个需求。

重锁按场景保存 status、revision、evidence、runs 和 stale_checks。场景契约或 check 配置变化时，保留历史并标为 stale；未变场景保留有效状态。CLI 的 relock 字段报告 preserved/stale/removed，旧锁文件损坏会给出 warnings。

验收指纹包含尚未跟踪的新文件；同一份内容在 add/commit 前后保持一致，删除后提交也一致。测试报告、计数文件等产物应加入 .gitignore；默认工作树指纹排除 .code-flow 和标准 .acceptance-manifest.json，显式 inputs 单独计算。

变更 command、inputs 或登记配置会使旧输入证明失效。多 check 场景逐个保存结果，A 通过不能覆盖 B 失败；CI 按 check 回传，格式见 [CI 证据指南](ci/acceptance-evidence.md)。手工将 TASK 或场景状态改成 verified 不会产生执行证据。

## ID、模板和规则证据

设计 frontmatter 设置 `design_template: lite|full|frontend` 中的实际模板值，再运行 `code-flow design lint --file <design> --scenarios-file <scenarios> --json`。多份设计重复 --file。检查未定义 FEAT/API/NFR、冲突 NFR、无场景功能、场景与功能错配及对应模板的必填章节。

doctor 会分别报告健康检查与各阶段 readiness。applied artifact 必须引用正确章节中的已完成条目；仅出现 Rule ID 或含有“待确认/TBD”的占位说明不构成证明。code/review 必须有执行证据。Conventions 中的关键约束应提升为 Rules；其余通过 convention_review_required 明确提示审查。

`spec apply/bind` 的工件相对当前需求目录解析，gate/doctor 使用同一基准；不搜索其他需求的同名文件。section_id 支持标题、标准 slug 和 TASK 编号；旧 task-008、rule-api-002 别名按大小写无关的完整 ID 解析。写入应用引用时立即验证目标章节和条目，仍拒绝未解决占位。`rule_artifact_stale` 保留阻断并在 next 给出显式 refresh 命令。

规则无需改代码也可以通过有效自动验证证明符合，因此 `decision=null` 本身不是错误。确实不适用时使用 `not_applicable` 和用户 decision；不得将未处理的“需同步 spec 文本”标为 applied。doctor 顶层 decision 表示诊断健康，`readiness.plan/code/review` 分别表示阶段准备情况，二者应一起查看。

## 报告与常见修复

| 报告字段 | 含义 |
|----------|------|
| `e2e_count` / `e2e_browser_count` | 声明的 E2E 数量 / 其中声明浏览器边界的数量，仍须查看 quality.errors |
| `system_count` / `capacity_count` | system 场景数 / capacity 层级或标签的场景数 |
| `runnable_smoke_count` / `runnable_browser_count` | 通过登记、真实收集和执行选择校验的场景数，不是测试用例数或已执行通过数 |
| `registration_status` | parse 时为 not_checked，verify-plan 收集后为 passed/failed；未检查的 runnable 值为 null，parse 不提供 runnable_browser_count |
| `verified_browser_count` | 当前语义报告中为 null，不以静态声明或收集结果推断浏览器执行成功 |

| 错误/提示 | 修复方式 |
|-----------|----------|
| `e2e_browser_boundary_missing` / `scenario_boundary_components_mismatch` | 确认真实浏览器边界并对齐 env/components/boundary；API/后台全链路改用 system/integration |
| `scenario_expected_nondeterministic` / `scenario_expected_reference_missing` | 写出可观察结果、明确条件与有效的步骤/断言引用 |
| `scenario_defer_metadata_missing` | 补齐延期原因、责任人和目标阶段 |
| `traceability_undefined_id` / `nfr_id_mismatch` / `scenario_feature_mismatch` | 在所有设计和场景源中统一 ID 定义、NFR 含义与功能对应关系 |
| `feature_without_scenario` / `template_section_missing` | 补验收场景或明确移出本期范围；补齐声明模板的必填章节 |
| `e2e_check_not_browser` / `capacity_check_not_marked` / `smoke_check_not_registered` | 修复实际套件/marker 及收集配置；不能只修改统计字段 |
| `check_test_not_collected` / `check_execution_selection_mismatch` | 核对具体 ID、文件/项目选择和真正执行的 command |
| `rule_applied_unresolved` / `rule_execution_evidence_missing` | 完成引用条目并重做有效验证；需要不适用决策时记录用户确认 |
| `legacy_quality_schema` | 旧计划继续使用原门禁；补齐新字段并重锁，再执行完整 verify-plan |
| `check_collection_inference_unsupported` | 用 --registration-file 声明项目收集器，再执行真实登记校验 |
| `stop_already_running` | 提示包含锁持有者 PID；等待该进程退出后重试，进程结束或被终止后 OS 自动释放锁 |

本轮问题回归入口为 `tests/test_workflow_issue_regressions.py`，覆盖同名工件隔离、旧引用、延期范围、批次 owner、真实收集、重锁历史、提交前后指纹、refresh 提示及 Stop 并发/进程超时。
| `convention_review_required` | 审查未纳入 Rules 的重要约定；需机器强制的约定提升为稳定 Rule 与 verifier |

修改 canonical 场景或任务后重新锁定 manifest，再运行 verify-plan；Context 漂移按 `code-flow spec refresh` 的诊断处理。不要删除 marker、手改 input_hash 或绕过失败的门禁。
