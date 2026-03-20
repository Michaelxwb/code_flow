# Python Scripts Code Standards

## Rules
- 所有函数必须有 type hints（参数和返回值）
- Hook 脚本（stdin→stdout）必须捕获异常并输出到 stderr，禁止静默吞掉
- 配置文件解析使用 mtime 缓存，避免重复 IO
- 外部依赖仅限 pyyaml，其他功能用标准库实现
- 注入状态必须包含 session_id，支持多会话隔离

## Patterns
- 新增工具函数 → 放在 cf_core.py，被其他脚本导入
- 标签匹配扩展 → 更新 _SAFE_DEPLURALS 和 _DIR_SEMANTIC_TAGS 字典
- 新增 Hook → 在 settings.local.json 模板中注册，脚本放在 scripts/ 目录
- 测试 → tests/test_cf_core.py，使用 assert + 自运行模式

## Anti-Patterns
- 禁止在 Hook stdout 输出非 JSON 内容（会破坏 Claude Code 协议）
- 禁止使用 print() 调试输出到 stdout，用 _log() 输出到 stderr
- 禁止在 extract_context_tags() 中使用 naive 字符串操作去复数（如直接去 's'）
