# Fluxion 试点准备（未验收）

来源仓库 commit：`7de468fb53012d90bd0adae977b80b25bc728d78`。以下是静态源码定位，不代表测试已执行或替代覆盖已建立。

| 原场景 | 原断言 | 候选低层位置及尚未覆盖的行为 |
| --- | --- | --- |
| `e2e/tests/agent-management/agent-management.spec.ts` E-07 | 并发更新后提交旧 revision，冲突提示且弹窗保留 | `tests/console_platform/test_agent_lifecycle_api.py::test_e01_stale_revision_conflict`、`tests/console_platform/test_agents_api.py::test_update_bumps_revision_and_rejects_stale_revision`；需真实数据库和组件测试证明提示及表单保留。 |
| `e2e/tests/overview-dashboard.spec.ts` S-02 | 七天总数 `[0,0,0,0,1,0,1]`、失败数 `[0,0,0,0,1,0,0]`，切换状态且不新增请求 | `tests/console_platform/test_overview_api.py` 为候选 API 测试；需核对同一输入与断言，另证明页面切换及请求行为。 |
| `e2e/tests/agent-management/agent-management.spec.ts` S-08/S-11 | Skill/MCP 绑定成功并显示，MCP 解绑再绑定，无绑定级开关 | `tests/console_platform/test_agent_skill_bindings.py`、`tests/console_platform/test_agent_mcp_bindings.py` 为候选；需核对真实数据库、关系复活及组件断言。 |

保留浏览器链路的候选源文件：`e2e/tests/webchat/identity-isolation.spec.ts` S-112、`e2e/tests/webchat/streams-actions.spec.ts` S-103、`e2e/tests/webchat/attachments-notifications.spec.ts` S-102/E-14/E-108（真实上传下载字节）。保留范围和证据仍需实际验收确认。

当前未测：四类缺陷注入、新旧方案覆盖对照、task/批次/归档各三次冷运行及复用运行。责任：执行 TASK-008 的实现者。不可由合成数据填充；未建立和验证独立项目 Context，也未删除或重锁任何原 E2E。现有试点报告校验仅拒绝未经验证的结论，尚不能验证测量来源或覆盖等价性。

本地验收前须按 fluxion 的 `AGENTS.md` 和 `harness-test` 规范停止现有 dev 服务并检查残留进程，使用独立数据库及 Redis；E2E 的 pretest 会自动停止 dev 服务。

## 已执行的基线（2026-10-30）

隔离 clone 使用上述 commit 的业务代码，独立安装依赖；测试使用单独 PostgreSQL 16 与 Redis 7 容器，以及项目的临时空库和 Redis 占号。试点 Context 绑定 `harness-test`、`harness-rel`，结构校验通过；设计和计划阶段尚未完成，不能据此修改或移除 E2E。

- 真实数据库上的 CAS 两个用例、Skill/MCP 绑定和概览 API 测试共 **46 passed**；使用 `tests.acceptance.datastores.create_datastore()` 建库迁移、执行后 `drop_datastore()` 清理。
- 真实浏览器、HTTP 和隔离数据库：`playwright.overview-dashboard.config.ts --grep 'S-02'` 为 **1 passed**；`playwright.agent.config.ts --grep 'E-07 stale revision|S-08/S-11'` 为 **2 passed**。这些是原方案基线，不是新旧三次对比或缺陷注入证据。

## 断言缺口复核（2026-10-30）

- 原 E-07 填写 `STALE PROMPT` 后只断言冲突提示和 Modal 可见，并未断言输入值仍然保留。候选 API 测试也不能证明浏览器表单状态；替代方案必须补上对输入值的行为断言。
- 概览 API 的 `test_empty_data_retains_unknown_rates_and_real_zero_counts` 验证七天全零，但并未用原 S-02 的混合输入断言 `[0,0,0,0,1,0,1]` 和 `[0,0,0,0,1,0,0]`；切换后的状态与不发额外请求也仍需页面层证据。
- `test_s06_unbind_then_rebind_updates_resolve` 覆盖 MCP 解绑、重新绑定和列表数量，但原浏览器用例还检查 Skill/MCP 的显示、解除后的页面变化及没有绑定级开关；不能仅凭 API 通过认定等价。
- 隔离试点 Context 中 `harness-test#RULE-test-001` 要求跨 API/DB/Runtime/Browser 的关键流程保留真实边界 E2E。试点设计与计划阶段仍为 pending，应先逐场景确定哪些跨边界链路属于关键流程并落实该规则；在此之前不能删除或重锁原浏览器用例。

复核时未发现 fluxion 开发服务监听，独立的试点 PostgreSQL 和 Redis 容器仍在运行。`python3 -m pytest -q --runxfail tests/test_verification_efficiency_08.py` 的当前结果为 **2 failed, 1 passed**：S-11 和 S-12 是显式占位失败，E-08 的保守拒绝测试通过。这不是故障注入或可复算基准的证据，真实性和覆盖等价性仍未验证。

## 运行时升级前后：单项契约检查（2026-10-30）

从 fluxion commit `7de468fb53012d90bd0adae977b80b25bc728d78` 创建隔离副本；旧版取该提交中项目自带的 code-flow。新版本通过当前工作区的 `migrate --runtime --apply` 安装到副本，安装后的 82 个 Python 运行时文件与当前工作区一致。两版版本号均为 0.8.0，但旧版有 20 个 Python 文件与新版本不同。真实业务仓库未升级。

工作负载为 fluxion `high-qps-remediation` 的 TASK-006、场景 S-11：`uv run pytest -q tests/contracts/test_im_contracts.py`，通过各版本的 acceptance runner 执行；使用 `UV_NO_SYNC=1` 和同一隔离副本的预装依赖。每次重复从相同原始 manifest 复制，先正常执行，再以生成的证据复跑；原始 manifest 的 SHA-256 两版一致。旧版在新版后又回滚补采复用数据，最后已在副本重新安装新版。

| 版本 | 首次运行中位数 | 复跑中位数 | 首次 executed/reused | 复跑 executed/reused |
| --- | ---: | ---: | --- | --- |
| 旧 | 1397.633 ms | 239.087 ms | 1/0（每次） | 0/1（每次） |
| 新 | 1422.577 ms | 250.233 ms | 1/0（每次） | 0/1（每次） |

上述 12 次运行均返回 pass；原始数据分别见 `fluxion-old-cache-runs.json` 和 `fluxion-new-cache-runs.json`。另有强制 `--no-cache` 的原始记录 `fluxion-old-runs.json` 和 `fluxion-new-runs.json`：该设置后的第一次复跑仍各执行一次，不能作为已复用样本。最初临时目录缺场景文件的失败保存在 `fluxion-old-preflight-failure.json`，随后补齐后才开始采样。

这是单项契约检查的小样本，表中差异不能证明整体变快，也未覆盖 task finish、批次、归档、数据库或浏览器链路；S-12 所要求的完整对照仍未完成。原始数据中临时 manifest 路径是执行时路径，临时目录已清理，原始输入身份由 manifest 摘要与仓库 commit 记录。

补充身份复核：原仓库与升级后隔离副本的 `tests/contracts/test_im_contracts.py` SHA-256 均为 `007d461c99a4b38b5e55474118ec198ff1acee42a66d8ef3fe95ac5e7b7fc639`；`uv.lock` 均为 `201d47a4e3ea8d035c7e02df2f1a5eb110045b3e0ae26b1450c33580ccb55ac2`。两版 acceptance runner 文件摘要分别为 `13ce25f7ae62d7ed430003ab244ac460339be0c5348e352a5190ead9ff6433e0` 和 `6f8a53a6c2f47cf4349a3924f17ea5358648e07e6c708636d011241906278a1c`；这是测量后对当前盘面和原仓库的复核，并非逐次运行时的完整环境快照。

旧版 `task verify --help` 不支持新版的 `--tasks` 参数。后续批次对照需要分别确定两版实际选中的检查及覆盖范围；直接比较不同范围的耗时会产生误导。不能用这项契约检查替代 task、批次和归档的测量。

`tests/test_verification_efficiency_08.py::test_fluxion_raw_sample_validation_recomputes_medians` 读取两份原始文件，检查三次样本、执行和复用计数、退出状态、项目与环境标识、实际命令一致性，并重新计算中位数；对缺样本、失败、身份变化、命令变化和合成来源的扰动进行拒绝检查。校验器只检查记录内部一致性，无法仅凭 JSON 证明记录真实，也不将本项样本视为 S-12 的完整通过。
