---
description: 根据变更文件自动匹配并执行验证规则
---

# cf-validate

根据变更文件自动匹配并执行验证规则（测试、类型检查、lint），失败时自动尝试修复。

## 输入

- `/project:cf-validate` — 自动获取任务基线或 Git 全部变更文件
- `/project:cf-validate src/Foo.tsx` — 验证指定文件
- `/project:cf-validate --files=src/a.ts,src/b.ts` — 验证多个文件

## 执行步骤

### 1. 获取变更文件列表

用 Bash 执行：

```bash
python3 .code-flow/scripts/cf_validation.py --root "$PWD" --scope-only --json
```

有 active TASK 时使用冻结基线以来的全部任务变更（含已提交文件）；无 active TASK 时包含暂存、未暂存和未跟踪文件。用户指定路径时用 `--files "src/a.py" "src/b.py"` 原样传递；若结果确实为空才输出“无变更需要验证”。

### 2. 读取验证规则

用 Read 读取 `.code-flow/validation.yml`。如果不存在，尝试读取 `package.json` 中的 `scripts.test` 和 `scripts.lint` 作为回退。

validation.yml 格式：

```yaml
validators:
  - name: "验证器名称"
    trigger: "**/*.{ts,tsx}"
    command: "npx tsc --noEmit"
    timeout: 30000
    on_fail: "修复建议"
```

### 3. 匹配并执行验证

执行统一验证入口：

```bash
python3 .code-flow/scripts/cf_validation.py --root "$PWD" --json
```

显式范围追加 `--files "src/a.py" "src/b.py"`。程序匹配 trigger、解析 argv 并展开 `{files}`，不拼接 shell 命令；同一运行内相同 argv/cwd/timeout 去重，跨运行不复用。删除文件仍触发全局测试，但不传给文件级编译器。每条 timeout 仍按配置的毫秒值生效，总预算耗尽返回 incomplete/block。

### 4. 汇总结果

- **全部通过** → 输出确认信息
- **有失败** → 展示每个失败项的：
  - 验证器名称
  - 执行的命令
  - 错误输出（截取关键部分）
  - `on_fail` 修复建议

### 5. 自动修复

对于失败的验证项，根据错误输出分析问题根因，自动尝试修复代码。修复后提示用户再次运行 `/project:cf-validate` 确认。

## 安全设计

- `{files}` 直接展开为 argv 参数；带空格、引号的路径仍是一个参数，不手工拼接引号或执行 shell
- 范围来自任务基线、Git 状态（包括 untracked）或用户显式指定的路径
- 用户指定的路径必须位于项目根目录内

## 异常处理

- validation.yml 不存在 → 尝试检测 package.json scripts 中的 test/lint 命令
- 命令执行超时 → 输出超时提示，建议增大 timeout 或缩小验证范围
- 命令不存在或配置无效 → 返回 block 并提示所缺依赖，不当作验证通过
- 无变更文件 → 输出"无变更需要验证"
