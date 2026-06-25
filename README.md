# code-flow

一个用于快速初始化与管理项目规范的命令行工具。通过全局安装后执行 `code-flow init`，自动生成项目约定文件与目录结构，帮助团队统一流程并提升协作效率。

## 安装

npm：

```bash
npm i -g @jahanxu/code-flow
```

pnpm：

```bash
pnpm add -g @jahanxu/code-flow
```

## 升级

npm：

```bash
npm i -g @jahanxu/code-flow@latest
```

pnpm：

```bash
pnpm add -g @jahanxu/code-flow@latest
```

## 卸载

npm：

```bash
npm rm -g @jahanxu/code-flow
```

pnpm：

```bash
pnpm remove -g @jahanxu/code-flow
```

## 基本用法

初始化（默认 `--platform=claude`）：

```bash
code-flow init
code-flow init --platform=codex
code-flow init --platform=costrict
code-flow init --platform=opencode
code-flow init --force                # 覆盖所有文件，包括用户已编辑内容
```

查看帮助：

```bash
code-flow --help
```

## 质量闭环（v0.5）

零配置开箱即用，安装后自动获得两个闭环：

**合规反馈**：spec 约束可在 frontmatter 标注机检规则，AI 编辑文件后自动检查，违规当场反馈给 AI 修正（只提示、不阻断）：

```yaml
---
description: 改 Python 脚本时适用
checks:
  - id: no-print-debug
    type: regex
    pattern: '^\s*print\('
    files: "**/*.py"
    message: 禁止 print() 调试，用日志到 stderr
---
```

**学习沉淀**：你在对话中纠正 AI 的行为（"不要用 print 调试"）会被记录，`/cf-learn` 将同类纠正聚合为候选规范（附 ✅/❌ 对照与机检草稿），由你确认后落盘——纠正一次，不用说第二遍。

**误报治理**：反馈出现误报时直接告诉 AI"这是误报"即可，同一规则误报 3 次或误报率超 10% 自动停用；`cf-stats` 可查违规榜/修正率/误报率，`cf-stats --audit` 输出僵尸规范复审清单。

**一键回退**：`config.yml` 中 `quality_loop.enabled: false` 完整回到 v0.5 行为。

> **数据声明**：质量闭环产生的所有数据（违规事件、纠正语句摘录、统计计数）仅存储在项目本地 `.code-flow/` 目录（`.session-log.jsonl` / `.check-state.json`，已加入 .gitignore），不上传、不外发、30 天滚动清理。纠正采集可经 `quality_loop.correction_capture: false` 单独关闭。

## 支持的 AI 工具

| 工具 | `--platform` | 状态 |
|------|-------------|------|
| [Claude Code](https://claude.ai/code) | `claude` | ✅ 完整支持 |
| [Codex CLI](https://github.com/openai/codex) | `codex` | ✅ 完整支持 |
| [Costrict](https://costrict.com) | `costrict` | ✅ 完整支持 |
| [OpenCode](https://opencode.ai) | `opencode` | ✅ 完整支持 |

## 生成的目录与文件

运行 `code-flow init` 后，将在项目根目录生成（或更新）以下结构：

```
.code-flow/                       # 规范核心（共用）
  scripts/                        # Python Hook 脚本（三端共用）
  specs/<domain>/                 # 领域 spec（_map.md + 约束规则）

# Claude Code (--platform=claude)
.claude/commands/                 # 命令模板
.claude/settings.local.json       # Hook 注册（PreToolUse + UserPromptSubmit）
CLAUDE.md                         # 全局指令

# Codex CLI (--platform=codex)
.codex/hooks.json                 # Hook 注册（SessionStart + UserPromptSubmit）
.codex/config.toml                # Codex 配置
.agents/skills/<skill>/SKILL.md   # 项目级 Skills
AGENTS.md                         # 全局指令

# Costrict (--platform=costrict)
.costrict/commands/               # 命令模板
.costrict/settings.local.json     # Hook 注册
CLAUDE.md                         # 与 Claude 共用全局指令

# OpenCode (--platform=opencode)
.opencode/commands/               # 命令模板（含 cf-task/）
.opencode/plugins/code-flow/      # 插件：转发到 cf_user_prompt_hook.py
opencode.json                     # 插件注册
AGENTS.md                         # 全局指令
```

## 依赖说明

- 需要 `python3` 版本 3.9 及以上
- 需要安装 `pyyaml`（`cf_init` 会尝试自动安装，失败会提示手动处理）
- 运行测试需要 `pytest`

### 运行测试

```bash
python3 -m pip install pyyaml pytest
python3 -m pytest -q tests
```

## 常见问题

- EOTP（`--otp`）
  - 原因：启用了 npm/pnpm 的一次性密码或 2FA。
  - 处理：按提示输入 OTP，或使用 `--otp` 重新执行安装命令。

- E402（`--access=public`）
  - 原因：发布/安装时访问级别不匹配或权限不足。
  - 处理：必要时使用 `--access=public` 重新发布或检查权限配置。

- name 冲突
  - 原因：本地或全局已有同名命令/包。
  - 处理：先卸载冲突包或更换名称后再安装。
