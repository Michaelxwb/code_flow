# CLI Code Standards

## Rules
- cli.js 零外部依赖，仅使用 Node.js 内置模块（fs/path/child_process）
- 所有文件操作使用同步 API（fs.readFileSync 等），CLI 场景无需异步
- 文件分类必须通过 fileCategory() 集中管理，禁止在其他位置硬编码分类逻辑
- 合并策略（merge 类文件）必须保证用户自定义内容不被覆盖

## Patterns
- 新增模板文件：放在 src/core/ 或 src/adapters/ 下，fileCategory() 自动分类
- 版本对比使用 compareVersions()，支持语义版本号
- 输出摘要按 Updated/Merged/Created/Skipped/Removed 分组

## Anti-Patterns
- 禁止在 CLI 中引入 npm 外部依赖
- 禁止在合并逻辑中覆盖用户已有内容
