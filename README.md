# code-flow

用于管理项目规范、任务和可执行验收的命令行工具。通过 `code-flow init` 安装四平台入口，再由持久化 Spec Context、场景源、阶段门禁和逐 check 执行证据约束开发流程。

本仓库当前版本为 **0.8.0**；npm 的 `latest` 标签以注册表查询为准。使用说明见[使用手册](docs/USAGE.md)，场景与测试登记格式见[可执行验收契约](docs/acceptance-contract.md)。

## 安装

npm：

```bash
npm i -g @michaelxwb/code-flow
```

pnpm：

```bash
pnpm add -g @michaelxwb/code-flow
```

## 升级

先核对已安装版本与注册表版本：

```bash
code-flow --version
npm view @michaelxwb/code-flow dist-tags --json
```

从 npm 升级到已发布的最新版本：

```bash
npm i -g @michaelxwb/code-flow@latest
```

pnpm：

```bash
pnpm add -g @michaelxwb/code-flow@latest
```

需要使用本仓库尚未发布的修复时，在仓库根目录构建并安装本地包：

```bash
npm pack --ignore-scripts
npm install --global ./michaelxwb-code-flow-0.8.0.tgz --ignore-scripts
code-flow --version
```

CLI 更新后，在目标项目执行运行时迁移，将脚本、已安装平台和 Hook 一起更新：

```bash
code-flow migrate --runtime --dry-run
code-flow migrate --runtime --apply
```

CLI 与项目 runtime 必须匹配；版本不一致时按诊断升级 CLI 或迁移 runtime。备份与回滚步骤见 [0.8 迁移说明](docs/migrations/runtime-0.8.0.md)。

## 卸载

npm：

```bash
npm rm -g @michaelxwb/code-flow
```

pnpm：

```bash
pnpm remove -g @michaelxwb/code-flow
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

## 开发与验收

需求文件集中在 `.code-flow/tasks/<日期>/<需求>/`。通常依次使用 `cf-task:prd` → `cf-task:align` → `cf-task:plan` → `cf-task:start` → `cf-task:verify-e2e` → `cf-task:archive`；Codex 使用对应的 `cf-task-*` skills。

| 阶段 | 正式运行时入口 | 检查内容 |
|------|----------------|----------|
| 场景 | `code-flow scenarios parse --file "<需求>.scenarios.md" --quality --json` | 浏览器边界、具体预期与步骤/断言引用、延期责任 |
| 设计 | `code-flow design lint --file "<需求>.design.md" --scenarios-file "<需求>.scenarios.md" --json` | ID 闭环、功能场景覆盖与已声明模板章节 |
| 计划 | `code-flow acceptance manifest --task-dir "<需求目录>" --task-file "<任务文件>" --verify-plan --json` | manifest、场景、设计、测试登记/收集与 Spec Gate |
| 开发中 | `code-flow task verify --task-dir "<需求目录>" --checks --profile full --root "$PWD" --json` | 只运行 validators，不推进任务状态 |
| 需求终验 | `code-flow task verify --task-dir "<需求目录>" --layers validators,review,e2e --profile full --root "$PWD" --json` | 全层执行与当前输入证据 |
| 诊断 | `code-flow spec doctor --task-dir "<需求目录>" --root "$PWD" --json` | 安装/Context 健康、未解决 Rule 引用与阶段 readiness |

浏览器关键旅程用 `e2e`，API/CLI/后台全链路用 `system`，容量用 `capacity`。计划通过与测试收集通过不能代替真实执行；格式、错误修复和各项数量口径见[验收契约](docs/acceptance-contract.md)。

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
  scripts/                        # Python 运行时与 Hook（四平台共用）
  runtime-commands.json            # 正式运行时命令契约
  tasks/<日期>/<需求>/             # PRD、design、scenarios、任务与验收 manifest
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
.opencode/plugins/code-flow/      # v2 插件：session.prompt 转发到 cf_user_prompt_hook.py
opencode.json                     # OpenCode 配置（`.opencode/plugins/` 自动发现，无需注册键）
AGENTS.md                         # 全局指令
```

## 依赖说明

- 需要 Node.js 18 及以上
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
