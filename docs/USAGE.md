# 使用操作说明

## 初始化流程

1. 进入项目目录
2. 执行 `code-flow init`
3. 确认生成的结构

示例：

```bash
cd your-project
code-flow init
```

初始化后会生成如下结构：

```
.
├── .code-flow/
├── .claude/
└── CLAUDE.md
```

## 日常命令

以下命令用于日常维护与自动化流程：

- `/cf-scan`：审计规范 token 与冗余/过时问题
- `/cf-stats`：统计 L0/L1 token 使用与预算
- `/cf-inject frontend`：手动注入前端 specs（Hook 失效时）
- `/cf-validate --files=...`：按文件触发验证规则并输出结果
- `/cf-learn --scope=... --content=...`：向 Learnings 追加记录

## Hook 验证示例

以下示例使用 `frontend` 路径模拟 `PreToolUse` 事件：

```bash
cd your-project
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"/absolute/path/src/components/Demo.tsx","old_string":"x","new_string":"y"}}' | python3 .code-flow/scripts/cf_inject_hook.py
```

示例中的 `file_path` 使用 `frontend` 目录路径。

如果配置了相关 Hook，执行后会在对应路径应用注入逻辑，并更新约定文件。

## 迁移与重新初始化建议

- 当已有项目需要接入时，建议先备份再执行 `code-flow init`。
- 已存在的文件默认不覆盖，若需更新内容请手动合并或删除后重新初始化。
- 多项目迁移时，逐个目录执行初始化以避免结构冲突。
