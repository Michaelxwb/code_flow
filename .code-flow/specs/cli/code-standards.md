---
description: 改 CLI（src/cli.js）init/upgrade/merge/平台适配时适用：零依赖、文件分类、合并策略约束
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
- cli.js 零外部依赖，仅使用 Node.js 内置模块（fs/path/child_process/os）
- hook command 模板必须用守卫写法：`$CLAUDE_PROJECT_DIR` 优先 → git toplevel 回退 → `[ -f ]` 存在性守卫 → `cd` 后执行；禁止依赖运行时 cwd 的裸路径（repo 外触发 exit 2 会阻断用户 prompt）
- 所有文件操作使用同步 API（fs.readFileSync 等），CLI 场景无需异步
- 文件分类必须通过 fileCategory() 集中管理，禁止在其他位置硬编码分类逻辑
- 合并策略（merge 类文件）必须保证用户自定义内容不被覆盖
- 平台参数解析必须通过 parsePlatform() 集中处理，禁止在 runInit 内部重复解析
- 初始化阶段的可选操作（如 legacy 清理、pyyaml 安装）失败时必须降级为 warning，不能阻塞 init 主流程

## Patterns
- 新增模板文件：放在 src/core/ 或 src/adapters/ 下，fileCategory() 自动分类
- 新增平台适配器：在 runInit() 中添加独立的 `if (platform === '...')` 分支，不与其他平台逻辑交叉
- 版本对比使用 compareVersions()，支持语义版本号
- 输出摘要按 Updated/Merged/Created/Skipped/Removed 分组
- 清理 deprecated 目录时使用独立函数封装删除逻辑，配置 `recursive + force + retry` 以兼容 Windows 文件锁场景

## Anti-Patterns
- 禁止在 CLI 中引入 npm 外部依赖
- 禁止在合并逻辑中覆盖用户已有内容
- 禁止在 Claude 和 Codex 适配器分支之间共享局部变量（各分支自包含）
