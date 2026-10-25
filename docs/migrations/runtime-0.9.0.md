# Scenario-First Acceptance 迁移

文件名沿用最初的 0.9 规划；Scenario-First 已包含在当前仓库 0.8.0 中。本页不表示 0.9 已发布，也不要求把 package 版本改为 0.9。

## 变化

- `<需求>.scenarios.md` 是验收场景唯一源，design 只引用 S-/E-/B- ID 并说明设计影响。
- plan 将场景投影到任务 Acceptance Coverage 与 manifest，audit 对账三者及逐 check 证据。
- 场景语义、设计 ID 和测试登记按[验收契约](../acceptance-contract.md)检查；仅能解析文件不等于计划通过。

## 迁移步骤

先安装匹配的 CLI 并完成[运行时迁移](runtime-0.8.0.md)。保留旧设计和任务定义，再从完整任务文件提取场景草稿：

```bash
code-flow scenarios migrate --task-file "<任务文件>" --output "<需求>.scenarios.md" --json
```

1. 检查草稿是否覆盖旧需求全部场景，补真实步骤、具体 expected 和逐条 expected_refs。
2. 明确 e2e/system/integration/capacity；e2e 声明浏览器边界，非 e2e 移除 why_e2e。
3. 补环境、组件、design_refs/features、触发路径与延期责任。API/CLI 全链路不再占用浏览器 E2E 数量。
4. 场景源完整后将 design 中的重复场景表改为引用，保留 FEAT/API/NFR 定义和对应关系；声明实际 design_template。
5. 重新锁定 manifest，在实际 check 上补齐套件、marker 与真实测试收集配置，再运行完整门禁。

```bash
code-flow scenarios parse --file "<需求>.scenarios.md" --quality --json
code-flow design lint --file "<需求>.design.md" --scenarios-file "<需求>.scenarios.md" --json
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json" --scenarios-file "<需求>.scenarios.md"
# 补齐对应 check 的登记配置后运行
code-flow acceptance manifest --verify-plan --require-scenarios --task-dir "<需求目录>" --task-file "<任务文件>"
code-flow audit --task-dir "<需求目录>" --root "$PWD" --json
```

迁移命令生成的草稿需要人工完善，尤其不能从旧命令名推断真实浏览器边界。登记与收集通过后仍需实际执行才能产生验收证据。

## 旧需求兼容

没有场景源且 design 保留完整旧场景定义的需求可走兼容审计，并标记 deprecated；只有引用的 design 缺少场景源时明确报 scenario_source_missing，不能推断或编造场景。

回退需恢复成套的旧设计、任务与 manifest，再执行审计。不要只删除场景源来绕过门禁；重锁计划仍需满足当前规则。
