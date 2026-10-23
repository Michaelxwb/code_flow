# CI 验收与证据回传

本地默认 `changed`，全量 E2E 放到 CI/nightly。CI 执行后把报告导入 central evidence，下一次本地 verify 可以复用；`source=ci` 的运行仍会校验 `commit`、`run_url`、`exit_code`。

## GitHub Actions 示例

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
            --json > acceptance.json
      - name: Import JUnit evidence
        if: always()
        run: |
          code-flow evidence import \
            --format junit \
            --file reports/junit.xml \
            --commit "$GITHUB_SHA" \
            --run-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
            --json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: acceptance
          path: |
            acceptance.json
            reports/
```

## 约束

- `--profile full` 必须显式指定；本地 `changed` 不应升级成全量 E2E。
- 夜间任务可以只跑 `--layers e2e --profile full`，functional/validators 由 PR 流水线负责。
- 导入失败（commit/run_url 缺失、用例无法映射）必须让 job 失败，不得吞掉。
- CI 证据写入 git common dir；worktree 不提交 evidence 目录。
