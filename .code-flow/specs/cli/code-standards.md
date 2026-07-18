---
id: cli-code-standards
description: 改 CLI（src/cli.js）init/upgrade/merge/平台适配时适用：零依赖、文件分类、合并策略约束
stages: [design, plan, code, review]
enforcement: required
verifiers:
  - rule: RULE-cli-dependency-allowlist-001
    type: test
    config:
      argv: [python3, -m, pytest, -q, tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency]
      timeout: 30
  - rule: RULE-cli-user-content-preservation-001
    type: test
    config:
      argv: [node, tests/test_cli_merge_helpers.js]
      timeout: 30
  - rule: RULE-cli-platform-parity-001
    type: test
    config:
      argv: [python3, -m, pytest, -q, tests/test_adapter_parity.py]
      timeout: 30
  - rule: RULE-cli-hook-guard-001
    type: test
    config:
      argv: [python3, -m, pytest, -q, tests/test_hook_command_robustness.py]
      timeout: 30
  - rule: RULE-cli-migration-transaction-001
    type: test
    config:
      argv: [node, tests/test_spec_workflow_migrate.js]
      timeout: 30
---

# CLI Code Standards

## Examples

✅ 零依赖 + 同步 IO（CLI 场景无需异步）

```js
const fs = require("fs");
const content = fs.readFileSync(srcPath, "utf-8");
```

❌ 引入外部依赖 / 无谓的异步链

```js
const axios = require("axios");          // 违反零依赖
await fs.promises.readFile(srcPath);     // CLI 不需要
```

## Rules
- [RULE-cli-dependency-allowlist-001] CLI runtime dependencies must stay within the reviewed package allowlist; migration work must not add an undeclared dependency.
- [RULE-cli-user-content-preservation-001] Init, merge, and migration helpers must preserve user-owned configuration and content.
- [RULE-cli-platform-parity-001] Claude, Codex, Costrict, and OpenCode adapters must retain normalized command content and canonical/deployed parity.
- [RULE-cli-hook-guard-001] Installed hook commands must resolve the project safely and remain no-op outside a code-flow project.
- [RULE-cli-migration-transaction-001] The breaking migration must provide dry-run, backup, journaled apply, rollback, idempotence, and version-last commit semantics.

## Guidance
- 双副本同步：`src/core/code-flow/`↔`.code-flow/`、`src/adapters/<p>/`↔`.<platform>/` 必须同步提交，只改模板源或部署副本一侧 = 测试通过但 live 行为不变
- 跨平台能力基线：cf-* 命令/skill 正文只能依赖 4 平台共有能力（读文件、rg/grep、编辑/写文件、向用户确认、`cf_*.py` hooks）；平台差异只允许落在**绑定 token**——命令前缀（`/project:` vs codex 裸名）、`CLAUDE.md`↔`AGENTS.md`、编辑工具措辞（`apply_patch`）、frontmatter。归一化这些 token 后 4 份正文必须逐字相同
- 善用平台特有能力（子代理、并行工具等）必须**可选 + 优雅降级**：缺该能力的平台回退基线流程且产出质量不变，绝不让任一平台拿到降级版行为；默认优先平台中立写法，仅当收益显著且回退干净时才加平台增强
- canonical 源 + 适配白名单：claude 版本是 cf-* 命令的内容 canonical 源；各平台只允许这些适配，**不得借适配删内容**——codex（`Glob`/`Read`/`Write`→`rg`/「读取」/「写入」等通用动词、命令 token `/project:cf-x`→`cf-x`、`apply_patch` 措辞、frontmatter）、opencode（`CLAUDE.md`→`AGENTS.md`、`Hook`→`插件`、frontmatter）、costrict（`.claude`→`.costrict`、`--platform`）。示例块、错误信息示例、步骤说明在任何平台都必须保留；发现某平台被砍即视为 bug，从 claude 回填
- cli.js 零外部依赖，仅使用 Node.js 内置模块（fs/path/child_process/os）
- hook command 模板必须用守卫写法：`$CLAUDE_PROJECT_DIR` 优先 → git toplevel 回退 → `[ -f ]` 存在性守卫 → `cd` 后执行；禁止依赖运行时 cwd 的裸路径（repo 外触发 exit 2 会阻断用户 prompt）
- 所有文件操作使用同步 API（fs.readFileSync 等），CLI 场景无需异步
- 文件分类必须通过 fileCategory() 集中管理，禁止在其他位置硬编码分类逻辑
- 合并策略（merge 类文件）必须保证用户自定义内容不被覆盖
- 平台参数解析必须通过 parsePlatform() 集中处理，禁止在 runInit 内部重复解析
- 初始化阶段的可选操作（如 legacy 清理、pyyaml 安装）失败时必须降级为 warning，不能阻塞 init 主流程
- 0.6.0 的 Spec Workflow 是经 dry-run/prepare/apply/journal/rollback 保护的**事务 breaking migration**；只有该显式迁移入口可删除旧 runtime 与 managed files，普通 init/merge 仍不得覆盖用户内容

## Patterns
- 新增模板文件：放在 src/core/ 或 src/adapters/ 下，fileCategory() 自动分类
- 新增平台适配器：在 runInit() 中添加独立的 `if (platform === '...')` 分支，不与其他平台逻辑交叉
- 版本对比使用 compareVersions()，支持语义版本号
- 输出摘要按 Updated/Merged/Created/Skipped/Removed 分组
- 清理 deprecated 目录时使用独立函数封装删除逻辑，配置 `recursive + force + retry` 以兼容 Windows 文件锁场景
- breaking 变更必须由 `src/migrate/` feature module 持有 backup/staging/journal，`.version` 永远最后写；`src/cli.js` 只做参数解析与委托

## Avoid
- 禁止在 CLI 中引入 npm 外部依赖
- 禁止在合并逻辑中覆盖用户已有内容
- 禁止在不同平台适配器分支（claude/codex/costrict/opencode）之间共享局部变量（各分支自包含）
