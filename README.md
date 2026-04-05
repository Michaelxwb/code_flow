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

初始化：

```bash
code-flow init
```

查看帮助：

```bash
code-flow --help
```

## 支持的 AI 工具

| 工具 | 状态 |
|------|------|
| [Claude Code](https://claude.ai/code) | ✅ 完整支持 |
| [Codex CLI](https://github.com/openai/codex) | ✅ 完整支持 |

## 生成的目录与文件

运行 `code-flow init` 后，将在项目根目录生成（或更新）以下结构：

```
.code-flow/       # 规范核心（共用）
.claude/          # Claude Code 适配
CLAUDE.md         # Claude Code 全局指令
.codex/           # Codex CLI 适配
AGENTS.md         # Codex CLI 全局指令
.agents/skills/   # Codex Skills（项目级）
  <skill>/SKILL.md
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
