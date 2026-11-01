# Spec 自检与优化

在项目根目录手动执行以下步骤；这些检查不会作为后台任务自动运行。四个平台 Claude、Codex、Costrict、OpenCode 均可通过终端使用同一 CLI，也可从 `cf-stats` 和 `cf-spec` 入口查看指引。

1. 体检：`code-flow stats --audit --human`（机器读取使用 `code-flow stats --audit --json`）。检查过期路径、重复内容、过长规范和待复审规则，结合实际文件验证结果。默认冗长阈值是 500 token；可在 `audit.long_spec_tokens` 中调整，`audit.path_roots` 可指定路径解析根。
2. 按实际代码路径衡量单次注入，例如 `code-flow spec budget --paths src/app.py --json`。`matched_total` 是该次匹配预算，`aggregate_total` 是项目聚合量；退出码 3 表示超限。只在单次注入超过目标时考虑拆分，重复内容先人工核实。
3. 查询影响，例如 `code-flow spec impact app-rules --json`。将 ID 换成实际规范 ID 或相对 `specs/` 的路径。`truncated` 或 `errors` 表示结果不完整，需先解决；在途任务及 Context 不能受应用操作影响。
4. 预览一个明确目标，例如 `code-flow spec optimize --dry-run --paths app/rules.md --target app/conventions.md --json`。将路径替换成项目实际规范，目标目录必须存在且目标文件不存在。保存提案：`code-flow spec optimize --dry-run --paths app/rules.md --target app/conventions.md --json > plan.json`。未指定目标时只给建议，不生成可应用操作。查看 diff、路径映射模式、预算和影响，确认规则 ID、正文及 verifier 保持不变。
5. 在交互终端执行 `code-flow spec optimize --apply --plan plan.json --json`，阅读实际 diff 后明确输入 `y`。提案或输入变化、在途 Context、非交互终端和不安全路径均会拒绝；重新生成并审查提案。失败会尝试恢复原始字节；进程中断时保留备份和 journal 并拒绝后续应用，需先检查事务现场并恢复，不能直接删除证据。
6. 对受影响需求执行 `code-flow spec refresh --task-dir <需求目录> --root "$PWD" --json`，再执行 `code-flow spec doctor --task-dir <需求目录> --root "$PWD" --json`，根据结果处理漂移与阶段 Gate。doctor 对域布局默认告警，可通过 `spec_workflow.strict_domain_layout: true` 改为严格阻断。最后对实际代码路径再次运行 budget，执行相应任务验证。

审计和提案是辅助判断，不会自动删除规则或自动修改配置。跨域移动前应特别核对预览中的 source/target patterns：不同匹配范围可能改变 Conventions 的注入范围。
