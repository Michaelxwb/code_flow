# Backend Platform Rules

## Rules
- API 变更必须保持向后兼容或提供版本化路径。
- 外部依赖变更需更新配置与运行手册。

## Patterns
- 使用 feature flag 控制灰度发布。

## Anti-Patterns
- 禁止在生产环境使用调试级别配置。
