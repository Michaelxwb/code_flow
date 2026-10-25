# CI 验收与证据回传

本地默认 `changed`，全量 E2E 放到 CI/nightly。CI 执行后把报告导入 central evidence，下一次本地 verify 可以复用；`source=ci` 的运行仍会校验 `commit`、`run_url`、`exit_code`。

可选择由 code-flow 直接执行验收，或导入外部测试框架报告。前者已经写入执行证据，无需再将同一次运行的报告重复导入。场景与测试登记先通过[完整计划门禁](../acceptance-contract.md#计划到终验)，收集证明与执行证明分别保存。

## GitHub Actions 示例

以下示例假定 runner 已安装与项目 runtime 匹配的 code-flow CLI，并按项目准备测试依赖、浏览器与数据库；需求内任务已完成、可以进行终验。将示例需求路径替换为实际路径，CLI 安装方式见[迁移指南](../migrations/runtime-0.8.0.md)。

```yaml
name: acceptance

on:
  pull_request:
  schedule:
    - cron: "0 18 * * *" # nightly

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -r requirements.txt
      - name: Full acceptance
        run: |
          code-flow task verify \
            --task-dir .code-flow/tasks/2026-10-22/demo \
            --root "$PWD" \
            --layers validators,review,e2e \
            --profile full \
            --json > "$RUNNER_TEMP/acceptance.json"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: acceptance
          path: ${{ runner.temp }}/acceptance.json
```

JSON 输出放在仓库之外，避免生成报告本身改变 repo scope 输入指纹。直接执行产生的 central evidence 位于 Git common dir；上传 JSON 摘要不等于将证据恢复到另一个 checkout。

## 外部报告回传

外部流水线必须真实运行测试并生成 JUnit/Playwright 报告，再在相同 commit 的干净 checkout 导入。报告放在仓库之外或已忽略路径，CLI 不会代为执行外部报告中的测试：

```bash
code-flow evidence import --format junit --file "/tmp/junit.xml" \
  --task-dir "<需求目录>" --root "$PWD" \
  --commit "$(git rev-parse HEAD)" --run-url "<真实 CI 运行 URL>" --json
```

用例必须能唯一映射到实际 manifest check。多 check 场景的报告应分别覆盖全部成员，例如以下用例名中的 CHK-A/CHK-B 需替换为真实 check ID：

```xml
<testsuite name="acceptance">
  <testcase name="test_browser_order[CHK-A]" />
  <testcase name="test_order_storage[CHK-B]" />
</testsuite>
```

单 check 报告可以使用 `--check "<check ID>"` 明确归属；不能用它将单个报告扩散为多个 check 的成功。A 通过、B 失败时按 check 保留结果，缺少 B 的证据不能用场景汇总 pass 代替。详细映射、skipped 与退出码约束见[使用手册](../USAGE.md#code-flow-evidence-import--ci-证据导入)。

## 约束

- `--profile full` 必须显式指定；本地 `changed` 不应升级成全量 E2E。
- 夜间任务可以只跑 `--layers e2e --profile full`，functional/validators 由 PR 流水线负责。
- 导入失败（commit/run_url 缺失、用例无法映射）必须让 job 失败，不得吞掉。
- CI 证据写入 git common dir；worktree 不提交 evidence 目录。
- 不同 checkout 需通过合法导入形成自己的证据；同一仓库 worktree 才共享 common dir。验收仍会检查当前输入指纹，更改 command/inputs/登记配置后旧证据失效。
- browser/smoke/capacity 的测试登记和收集仍由 verify-plan 检查，测试必须在声明的真实环境执行；不要通过改 marker 或汇总数字伪造结果。
