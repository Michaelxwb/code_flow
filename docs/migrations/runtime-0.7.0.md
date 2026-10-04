# 0.7.0 原生平台运行时迁移

0.7.0 将 Agent 的公开调用统一到 `code-flow`，Codex 使用原生 `apply_patch` 事件入口。没有旧命令别名、无效参数容错或双写路径。

新项目执行 `code-flow init --platform=codex`。已安装 schema-v1 的项目在使用新版 CLI 后执行：

```bash
code-flow migrate --runtime --dry-run
code-flow migrate --runtime --apply
```

dry-run 在 `.code-flow/migrations/runtime-*/` 构建并验证产物后，清理备份和暂存目录，仅保留预览日志，项目目标文件保持原样。apply 重新构建并验证待安装产物，保留事务备份，更新全部已安装平台，保留用户配置、规范和任务，替换受管理的 Codex Hook 定义；`.version` 最后写入。安装版本高于 CLI 时拒绝迁移，必须先更新 CLI。

返回 `committed` 后在 Codex `/hooks` 中信任变更定义。迁移文件仍保留，可按输出的 `migration_id` 回滚：

```bash
code-flow migrate --runtime --rollback runtime-<timestamp>-<pid>
```

失败时自动恢复已写入文件。进程中断后必须先按错误提示回滚对应事务；不能启动第二次 apply 越过未完成事务。回滚不会覆盖迁移完成后又发生的文件修改，遇到此类修改会阻断并指出路径。

公开命令示例：

```bash
code-flow spec validate --task-dir ".code-flow/tasks/<日期>/<需求>" --json
code-flow task start --help
code-flow task finish --help
code-flow task verify-e2e --help
code-flow acceptance run --help
code-flow validate --help
```

`.code-flow/runtime-commands.json` 定义公开命令与业务模块的唯一映射，参数由实际解析器验证；错误入口或未知参数会明确报错。开发时执行 `node src/render-runtime-contract.js`，从同一契约生成四个平台技能中的命令示例。`.runtime-install.json` 记录版本和受管理文件哈希，命令执行及 Codex Hook 会检查完整性。安装损坏时通过上述事务迁移修复。

编辑 Hook 覆盖补丁操作；通过 shell 或其他工具修改的文件仍由 Finish 的任务基线 diff 校验。Hook 不替代阶段门禁。

Codex Hook 模板通过官方 `commandWindows` 字段提供 Windows 原生入口，使用 Python Launcher `py -3`；macOS/Linux 使用 `python3`。两者从当前目录向上定位入口，并将原始事件传给同一个 Codex 处理器。

安装损坏时 Stop 返回 `decision: block`，其余事件输出诊断；无法确认 `apply_patch` 成功时不产生 edit Evidence，并写入 degrade 日志。成功判定不接受猜测的 `status: completed` 包装。

OpenCode v2 同样使用专用原生入口 `cf_opencode_event.py`。插件传入原生 event、sessionID 和会话 location.directory，直接调用共享 prompt/edit/stop 服务，不构造 Claude 工具事件或读取其他平台的 Hook 输出。`edit/write` 使用 input.path，`patch` 使用 input.patchText；只有原生 status=completed 产生 edit Evidence。已在 v2.0.15 验证插件加载和 prompt 事件。idle 无阻断接口，收尾失败反馈进入下轮 context，Finish/verify-e2e 保持硬门禁。
