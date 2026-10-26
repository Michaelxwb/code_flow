---
schema: 1
requirement: runtime-consolidation
scenarios:
  - id: S-01
    title: 真实 npm 包安装生成完整运行时 ignore
    priority: P0
    level: system
    exec: auto
    env: none
    components: [cli, filesystem, package]
    boundary: npm pack tarball → code-flow init → 项目 .code-flow/.gitignore
    preconditions: [临时空项目目录, 本仓库可执行 npm pack]
    steps: [在临时目录解包 tarball 并对空项目执行 code-flow init --platform=claude]
    expected: [生成 20 条运行时忽略项，且包含 .stop.lock 与 .context-state.json]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#2.5 验收条件]
    rules: [RULE-03]
    features: [FEAT-01]
    checks: []
  - id: S-02
    title: 升级保留用户 ignore 行并补齐托管项
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [cli, filesystem]
    boundary: 旧版本 .code-flow/.gitignore → init upgrade → 合并后的托管块
    preconditions: [项目含旧版托管块, 用户追加自定义行]
    steps: [删除一条托管项并追加用户行，再执行 init 升级]
    expected: [被删除的托管项恢复，用户行原样保留]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-03]
    features: [FEAT-01]
    checks: []
  - id: B-01
    title: 无托管标记的用户 ignore 文件不被改写
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [cli, filesystem]
    boundary: 用户自有 .code-flow/.gitignore（无 code-flow 标记）
    preconditions: [文件内容不含托管块标记]
    steps: [对存在用户自有 ignore 文件的项目执行 init]
    expected: [文件字节级保持不变]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-03]
    features: [FEAT-01]
    checks: []
  - id: E-01
    title: 模板与 CLI 内嵌 ignore 漂移在默认测试流程失败
    priority: P0
    level: integration
    exec: auto
    env: none
    components: [cli, test-runner]
    boundary: canonical .gitignore → cli.js RUNTIME_GITIGNORE → pytest 默认入口
    preconditions: [pytest -q tests 是文档化测试入口]
    steps: [向 canonical 模板添加一条托管项但不更新 CLI，运行默认测试]
    expected: [默认测试流程返回非零并指出缺失条目]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.5 质量实现方案]
    rules: [RULE-03]
    features: [FEAT-01]
    checks: []
  - id: S-03
    title: 损坏 validation.yml 在三个入口一致阻断
    priority: P0
    level: integration
    exec: auto
    env: none
    components: [validators, hooks, cli]
    boundary: 真实 validation.yml → validate / Stop / finish 三个消费者
    preconditions: ["validation.yml 内容为 validators: [", 存在本会话编辑事件]
    steps: [分别调用 validate_files、build_stop_result 与 _run_finish_validation]
    expected: [三个入口均返回阻断，reason 为 invalid_validation_config]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-01]
    features: [FEAT-02]
    checks: []
  - id: S-04
    title: 缺失 validation.yml 保持既有产品策略
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [validators, cli]
    boundary: 无 validation.yml 的项目 → validate/finish 策略分支
    preconditions: [项目无 validation.yml, package.json 无 test/lint 脚本]
    steps: [分别调用 validate_files 与 _run_finish_validation]
    expected: [validate 返回 no_validators_configured，finish 不阻断]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-01]
    features: [FEAT-02]
    checks: []
  - id: S-05
    title: heavy validator 在 finish 默认延期
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [validators, hooks]
    boundary: quality_loop.heavy_at_finish 开关 → finish 验证结果
    preconditions: ["存在 heavy: true validator", heavy_at_finish 未开启]
    steps: [执行 finish 验证并读取 deferred_heavy 计数]
    expected: [heavy validator 未执行且 deferred_heavy 计数为 1]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.5 质量实现方案]
    rules: [RULE-01]
    features: [FEAT-02]
    checks: []
  - id: E-02
    title: Stop 阻断输出合法 JSON 与明确 reason
    priority: P0
    level: integration
    exec: auto
    env: none
    components: [hooks, validators]
    boundary: Stop Hook stdin/stdout 协议
    preconditions: [validation.yml 损坏]
    steps: [以合法 Stop 事件调用 cf_stop_hook.py 并解析 stdout]
    expected: [stdout 是单个 JSON 对象，decision=block 且 reason 含 invalid_validation_config]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-01, RULE-09]
    features: [FEAT-02]
    checks: []
  - id: S-06
    title: 行内示例与围栏代码块中的 TASK 标题不被识别
    priority: P1
    level: unit
    exec: auto
    env: none
    components: [task-doc]
    boundary: 纯解析函数 parse_task_document
    preconditions: [文档包含行内示例与围栏代码块]
    steps: [解析含行内示例标题和围栏内标题的 TASK 文档]
    expected: [只返回真实标题对应的 TASK 段落]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: S-07
    title: 重复 TASK ID 在所有入口一致拒绝
    priority: P0
    level: integration
    exec: auto
    env: none
    components: [task-doc, spec-context, spec-gate]
    boundary: parse_task_document → workflow/session/index/gate/plan 五个消费者
    preconditions: [任务文档包含两个同名 TASK-001]
    steps: [用五个消费者分别读取同一文档]
    expected: [五个消费者均抛出 duplicate_task_id 或返回等价阻断]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: S-08
    title: 缺失 Status 字段仍视为 draft
    priority: P1
    level: unit
    exec: auto
    env: none
    components: [task-doc]
    boundary: 纯解析函数 status 投影
    preconditions: [TASK 段落无 Status 行]
    steps: [解析缺失 Status 的 TASK 段落]
    expected: [status 返回 draft]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: S-09
    title: 真实任务闭环 start 到 finish 再到 verify
    priority: P0
    level: system
    exec: auto
    env: none
    components: [cli, spec-context, task-doc, hooks]
    boundary: 真实任务目录 → start → finish → verify
    preconditions: [临时仓库含完整需求目录与任务文件]
    steps: [执行 code-flow 任务 start、finish 与 spec gate]
    expected: [三个命令均按同一 TASK 状态推进且无解析分歧]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.2 架构设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: E-03
    title: plan gate 对重复 TASK ID 返回阻断
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [spec-gate, task-doc]
    boundary: 真实任务文件 → plan stage gate
    preconditions: [任务文件含重复 TASK ID]
    steps: [执行 plan 阶段 spec gate]
    expected: [gate decision=block 且引用 duplicate_task_id]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: S-10
    title: Git 原语在三个消费者行为一致
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [git, runtime]
    boundary: 真实 git 仓库 → cf_git 公共函数
    preconditions: [仓库含已跟踪修改与未跟踪文件]
    steps: [分别通过 spec_context、evidence_store、task_parallel 的调用路径读取变更]
    expected: [三个消费者返回相同的相对路径集合]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-05]
    features: [FEAT-04]
    checks: []
  - id: S-11
    title: 原子写在异常中断下不产生半写文件
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [filesystem, runtime]
    boundary: 真实文件系统 → atomic_write_text
    preconditions: [目标文件已有完整内容]
    steps: [在写入过程中注入异常并检查目标文件]
    expected: [目标文件保持原内容，临时文件被清理]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-05]
    features: [FEAT-04]
    checks: []
  - id: S-12
    title: Markdown 与表格解析统一边界
    priority: P1
    level: unit
    exec: auto
    env: none
    components: [markdown]
    boundary: 纯函数 parse_frontmatter 与 table_columns
    preconditions: [输入含无 frontmatter、无表头、列序变化]
    steps: [分别解析三类输入]
    expected: [无 frontmatter 返回空映射，无表头返回空列索引，列序变化按表头定位]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.4 接口设计]
    rules: [RULE-05]
    features: [FEAT-04]
    checks: []
  - id: S-13
    title: 删除旧 Spec 路径后公开输出与路由不变
    priority: P1
    level: system
    exec: auto
    env: none
    components: [cli, hooks, spec-context]
    boundary: 公开 CLI 命令与 Hook 输出
    preconditions: [删除前已记录基线输出]
    steps: [删除 read_matched_specs、read_specs、extract_context_tags 后重跑公开入口]
    expected: [路由结果与 Hook JSON 输出与基线一致]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#2.4 范围与边界]
    rules: [RULE-04]
    features: [FEAT-05]
    checks: []
  - id: S-14
    title: verify_plan 单次操作读取次数下降
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [runtime, acceptance]
    boundary: 聚合入口 → 读取计数探针
    preconditions: [两场景计划且测试收集通过]
    steps: [执行一次 verify_plan 并统计 TASK、场景、manifest 读取次数]
    expected: [TASK、场景、manifest 各至多读取 1 次且结果不变]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.5 质量实现方案]
    rules: [RULE-07]
    features: [FEAT-06]
    checks: []
  - id: E-04
    title: 两次读取之间文件变化触发漂移阻断
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [runtime, acceptance]
    boundary: 快照加载 → 文件变更 → 漂移校验
    preconditions: [加载后修改任务文件内容]
    steps: [加载快照后修改 TASK 文件再执行校验]
    expected: [返回 drift 阻断而不是使用陈旧快照]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.5 质量实现方案]
    rules: [RULE-07]
    features: [FEAT-06]
    checks: []
  - id: S-15
    title: 依赖方向守卫识别反向依赖
    priority: P0
    level: contract
    exec: auto
    env: none
    components: [test-runner, runtime]
    boundary: AST 导入图 → 层映射守卫
    preconditions: [人工注入一条 L0 导入 L2 的边]
    steps: [运行依赖方向守卫测试]
    expected: [测试失败并指出违规边]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.2 架构设计]
    rules: [RULE-04, RULE-07]
    features: [FEAT-07]
    checks: []
  - id: S-16
    title: 私有符号守卫与棘轮同时生效
    priority: P0
    level: contract
    exec: auto
    env: none
    components: [test-runner, runtime]
    boundary: AST 导入图 → 私有符号 allowlist
    preconditions: [allowlist 含一条存量条目]
    steps: [新增一条私有导入，再删除 allowlist 对应代码]
    expected: [新增违规失败；allowlist 条目消失也失败]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.2 架构设计]
    rules: [RULE-05, RULE-07]
    features: [FEAT-07]
    checks: []
  - id: S-17
    title: 四平台安装后 hook 路径与命令不变
    priority: P0
    level: system
    exec: auto
    env: none
    components: [cli, hooks, filesystem]
    boundary: 四种 adapter 安装 → settings/hooks/plugin → 真实 Hook 调用
    preconditions: [临时空项目]
    steps: [分别以 claude、codex、costrict、opencode 执行 init 并调用 hook]
    expected: [22 个入口路径存在且 hook 返回合法 JSON 或静默 no-op]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#4.1 部署架构]
    rules: [RULE-06, RULE-08, RULE-09]
    features: [FEAT-08]
    checks: []
  - id: S-18
    title: 包化升级清理旧平铺模块并保留 shim
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [cli, filesystem, package]
    boundary: 旧平铺安装 → runtime migrate → 新包布局
    preconditions: [旧版本项目含平铺 cf_*.py]
    steps: [执行 runtime migrate 升级到包化布局]
    expected: [22 个入口 shim 存在，旧平铺实现文件被清理，runtime-install 校验通过]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#4.4 数据迁移]
    rules: [RULE-06, RULE-10]
    features: [FEAT-08]
    checks: []
  - id: S-19
    title: canonical 模板、部署副本与 npm 产物保持 parity
    priority: P1
    level: system
    exec: auto
    env: none
    components: [cli, package, filesystem]
    boundary: src/core/code-flow → .code-flow → npm tarball
    preconditions: [工作树已同步双副本]
    steps: [运行 parity 测试并检查 npm pack 文件清单]
    expected: [双副本文件集一致且 tarball 包含包树与入口 shim]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#4.1 部署架构]
    rules: [RULE-06, RULE-08]
    features: [FEAT-08]
    checks: []
  - id: E-05
    title: 包化迁移失败时回滚到旧布局
    priority: P1
    level: integration
    exec: auto
    env: none
    components: [cli, filesystem, package]
    boundary: 迁移 staging → 注入失败 → rollback
    preconditions: [迁移过程中注入写入失败]
    steps: [执行迁移并触发失败，再执行 rollback]
    expected: [项目恢复旧平铺布局且 runtime-install 版本一致]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#4.2 发布与回滚]
    rules: [RULE-10]
    features: [FEAT-08]
    checks: []
  - id: B-02
    title: CRLF 与无 TASK 段落的边界处理
    priority: P1
    level: unit
    exec: auto
    env: none
    components: [task-doc]
    boundary: 纯解析函数边界输入
    preconditions: [输入使用 CRLF 且包含空文档]
    steps: [分别解析 CRLF 文档与无 TASK 段落文档]
    expected: [CRLF 文档正常解析，无 TASK 段落抛 task_document_empty]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-02]
    features: [FEAT-03]
    checks: []
  - id: B-03
    title: 过渡 allowlist 到期后棘轮强制清零
    priority: P1
    level: contract
    exec: auto
    env: none
    components: [test-runner, runtime]
    boundary: 私有导入 allowlist 与批次元数据
    preconditions: [allowlist 条目声明了到期批次]
    steps: [运行守卫测试并检查 allowlist 元数据]
    expected: [超过到期批次仍有条目时测试失败]
    expected_refs: [{expected: 1, steps: [1]}]
    design_refs: [runtime-consolidation.design.md#3.3 数据设计]
    rules: [RULE-05, RULE-07]
    features: [FEAT-07]
    checks: []
---
