# cf-inject

强制重新注入指定领域的编码规范（通常不需要手动调用）。

## 自动注入机制

本项目的规范注入是**全自动**的，通过两层机制保障：

1. **CLAUDE.md 指令**（主要）：Claude 根据用户提问内容自动判断领域，读取 `.code-flow/config.yml` 和对应 spec 文件，作为约束应用
2. **PreToolUse Hook**（安全网）：编辑代码文件时 Hook 自动触发，注入匹配领域的 specs

正常情况下**无需手动调用**此命令。

## 何时使用

- 需要强制刷新已注入的规范（如 spec 文件刚被修改）
- 想要预览某个领域的完整规范内容
- 自动注入未生效时的排查手段

## 输入

- `/project:cf-inject frontend` — 强制加载前端全部 specs
- `/project:cf-inject backend` — 强制加载后端全部 specs

## 执行步骤

1. 用 Read 读取 `.code-flow/config.yml`，获取指定领域的 `specs` 列表
2. 用 Read 逐个读取 `.code-flow/specs/` 下的匹配文件
3. 将规范内容直接输出到对话中，格式：

```
## Active Specs (manual inject)

### [spec-path]
[spec 内容]

---
以上规范是本次开发的约束条件，生成代码必须遵循。
```

4. 用 Write 更新 `.code-flow/.inject-state`，防止 Hook 重复注入
