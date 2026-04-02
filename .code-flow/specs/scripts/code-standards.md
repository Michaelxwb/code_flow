# Python Scripts Code Standards

## Rules
- 所有函数必须有 type hints（参数和返回值）
- Hook 脚本（stdin→stdout）必须捕获异常并输出到 stderr，禁止静默吞掉
- Hook stdout 必须是合法 JSON，且包含 `hookSpecificOutput.additionalContext` 字段
- Hook 在 no-op 场景（空输入、未命中、配置缺失）必须直接返回，不输出额外 stdout 噪音
- 配置文件解析使用 mtime 缓存，避免重复 IO
- 外部依赖仅限 pyyaml，其他功能用标准库实现
- 注入状态必须包含 session_id，支持多会话隔离
- Codex Hook 的 session_id 必须从 stdin JSON 读取，禁止用 os.getpid() 替代

## Patterns
- 新增工具函数 → 放在 cf_core.py，被其他脚本导入
- 标签匹配扩展 → 更新 _SAFE_DEPLURALS 和 _DIR_SEMANTIC_TAGS 字典
- 新增 Claude Hook → 在 settings.local.json 模板中注册，脚本放在 scripts/ 目录
- 新增 Codex Hook → 在 hooks.json 模板中注册（3 层结构：event → [{hooks:[{type,command}]}]），脚本放在 scripts/ 目录
- Codex prompt 路径提取同时支持裸路径、`@path`、反引号路径，并在注入前做去重与噪音过滤
- 测试 → tests/ 目录，使用 pytest，覆盖 happy path / fallback / 空输入

## Anti-Patterns
- 禁止在 Hook stdout 输出非 JSON 内容（会破坏 Claude Code / Codex 协议）
- 禁止使用 print() 调试输出到 stdout，用 _log() 输出到 stderr
- 禁止在 extract_context_tags() 中使用 naive 字符串操作去复数（如直接去 's'）
- 禁止在 Codex UserPromptSubmit Hook 中用 os.getpid() 作为 session_id
