# Specs 自动注入校验

Prompt 和编辑入口共用 Context-first 路由。存在 active TASK 时，绑定事实来自持久化 Context；无 active TASK 的明确本地路径使用 path_mapping，没有本地路径时展示 Catalog。

**源文件与投影版本**

每次事件读取 Context 后校验 marker 的身份哈希，并对已绑定 Spec 的原始字节计算 SHA256。文件变化或缺失返回 `bound_spec_drift` / `bound_spec_missing`，需要显式 refresh；不会重选规范或继续发送旧规则。源哈希校验在输出去重之前执行，mtime 不变也不能隐藏内容变化。

投影缓存同时检查 Context 文件版本和 TASK 内容哈希。会话去重按实际输出内容生成指纹，因此 Spec-Refs、合同、Context 身份或投影中的 artifact 引用变化都能触发重注入。缓存不保存新的绑定事实。

`.code-flow/.context-state.json` 缓存经过 schema 校验的解析结果与原有身份哈希，键包含 Context 原始字节哈希、文件路径及解析器版本，缓存体另有完整性校验。每次先读取真实源文件；源文件变化、解析器变化或缓存损坏都重新解析源 YAML。缓存缺失不能让损坏源文件通过，也不会自动刷新绑定。

**批量编辑**

Codex apply_patch、OpenCode patch 把全部路径交给 `prepare_edits`；单文件编辑使用同一批量服务。服务按路径所属的项目分组，每组加载一次 Context、校验一次绑定源、解析一次相关的未绑定 Spec headers。删除与移动源路径仍参与检查。

路径查询先按 mapping 过滤无关域，再解析匹配及全局规范。全量 resolver 和 `code-flow spec catalog` 继续保留完整候选与全库元数据检查能力。

**错误和拒绝**

配置损坏、Context 无效、源文件漂移、缺失 Spec-Refs / Acceptance Contract，以及超预算都产生结构化 `SPEC_WORKFLOW_BLOCKED`。Claude/Costrict/Codex 编辑入口使用 `hookSpecificOutput.permissionDecision: deny`；OpenCode 返回原生 `blocked: true`。

Codex 字段依据 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks#pretooluse)。入口 JSON 测试与真实宿主拒绝写入测试是不同验证层次，报告测试结果时须区分。

历史 enforcement=warn/inject 仍兼容部分旧验证降级，doctor 返回 `legacy_enforcement_mode` 提示审查后显式改回 required。它们不能隐藏上述路由完整性错误。新增路径引入未绑定 required Spec 仍按现有规范给出 refresh 提示，允许本次编辑。

**输出与预算**

TASK/path 注入状态按 session_id 的 SHA256 分文件隔离，位于 `.code-flow/sessions/injection/`；此目录属于可重建运行状态。只有成功序列化、写出并 flush 输出后，入口才提交待更新的去重状态。输出异常或超时不会提前标记已发送。状态不可用时允许重新注入，并记录诊断。

Prompt 每 25 轮保留周期重注入。Prompt 和编辑前共享同一模式的投影指纹，因此重复的路径或 TASK 不重复发送相同全文。

path 模式使用 `min(budget.total, budget.l1_max)`，缺省分别为 2500/1700。token 使用当前项目的 `len(text) // 4` 估算。required 内容放不下时返回 `spec_budget_exceeded`，不发送残缺规则；应创建聚焦 TASK Context 或拆分编辑范围。

Catalog 排除 `_session/` 和 tags=[] 命令模板。Tier 0 文件仅作为导航展示。目录省略时，预算内保留已展示/总数和完整查询命令：

```sh
code-flow spec catalog --root . --stage code --json
```

**回归验证**

```sh
python3 -m pytest -q tests/test_cf_injection_hardening.py tests/test_cf_user_prompt_hook.py tests/test_cf_pre_tool_hook.py tests/test_cf_injection_version.py tests/test_codex_native_hook.py tests/test_opencode_native.py
CODE_FLOW_HOST_TESTS=1 python3 -m pytest -q tests/test_codex_host_injection.py
code-flow sync check
code-flow validate --root . --json
```

规模回归构造真实 Context：200 个绑定 Spec、TASK 引用一条规则、一次编辑 20 个文件。断言 Context 与身份哈希各计算一次，已绑定 Spec 不重复解析 header，并对实际 Codex 入口施加配置中的 5 秒超时。时间测量与解析调用次数共同用于判断回归，避免把单个小 Context 的进程内缓存结果当成实际 Hook 性能。

真实宿主测试需要本机 Codex CLI 和已有模型元数据缓存，默认跳过。显式运行时使用隔离项目、已审查的测试 Hook、本地确定性 Responses 服务和独立 provider，不调用付费模型；正例实际写入临时文件，反例由宿主拒绝并确认文件不存在。

本机 Apple M5 Pro / Python 3.9.6 的[测量记录](spec-injection-performance.json)：500 个 Spec、仅命中一个的路径 Prompt 中位数从 229.33 ms 降至 56.02 ms；200 个绑定、输出被去重的 Prompt 从 285.23 ms 降至 56.48 ms。20 文件编辑服务在解析缓存可用时从 9631.24 ms 降至 8.03 ms；完整安装的 Codex Hook 新进程首次解析为 333.36 ms，缓存可用时中位数 67.45 ms。服务调用与完整 Hook 进程分别列出，缓存状态与样本数见记录，数值不作为跨机器 SLA。
