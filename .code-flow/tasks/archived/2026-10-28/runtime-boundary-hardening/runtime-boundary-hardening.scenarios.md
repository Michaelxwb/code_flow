---
schema: 1
requirement: runtime-boundary-hardening
scenarios:
- id: S-01
  title: 守卫识别运行时导入形式
  priority: P1
  level: unit
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 AST 扫描器与临时 Python 模块
  preconditions:
  - 临时模块包含 TYPE_CHECKING 的 else 分支、模块属性私有访问、相对导入和字面量动态导入
  steps:
  - 扫描每个模块并读取依赖边及私有访问诊断
  expected:
  - 每条运行时导入和跨模块私有访问均被识别，类型专用导入不产生运行时边
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-01
  features:
  - FEAT-01
  checks:
  - CHK-b2cad7b5ef6b
- id: B-01
  title: 守卫区分入口 shim 与包内同名模块
  priority: P1
  level: unit
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 stem 分层表、临时包结构与 SCC 计算
  preconditions:
  - 一个入口 shim 与实现同名，另有两个不同包中的实现模块同 stem
  steps:
  - 扫描两种结构并检查模块身份诊断
  expected:
  - 已知 shim 可映射至实现，两个不同实现的同名歧义被明确拒绝
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-01
  features:
  - FEAT-01
  checks:
  - CHK-aad161ddf787
- id: S-02
  title: Stop 不把场景和已移动旧路径当任务
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实会话 edit 日志、临时项目文件与 Stop Hook 子进程
  preconditions:
  - 日志记录场景文档及归档后不再存在的任务旧路径
  steps:
  - 发送 Stop 事件并收集 stdout 与 stderr
  expected:
  - 场景文档不进入 TASK 校验，已移动旧路径不产生缺失文件警告，stdout 保持静默或协议 JSON
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-02
  features:
  - FEAT-02
  checks:
  - CHK-55d318482620
- id: E-01
  title: Stop 保留真实错误和活动任务门禁
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Stop Hook、临时活动 marker 与文件系统
  preconditions:
  - 项目包含损坏的活动 marker 和以目录代替 TASK 文件的读取错误
  steps:
  - 分别触发活动任务检查和非缺失文件读取错误
  expected:
  - 活动 marker 损坏返回阻断，非缺失读取错误有 stderr 诊断
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-02
  features:
  - FEAT-02
  checks:
  - CHK-7907c924815c
- id: S-03
  title: manifest 与场景解析形成单向依赖
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 场景文件、TASK 文档、manifest 锁定与真实 AST 导入图
  preconditions:
  - 临时需求包含场景源、Coverage 和对应执行命令
  steps:
  - 锁定 manifest、运行场景解析及迁移入口并检查导入图
  expected:
  - 场景与检查映射一致，manifest schema 和 scenarios 之间不存在多模块 SCC
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-03
  checks:
  - CHK-d55dabdd9c27
- id: E-02
  title: 旧版 manifest 自愈和漂移保持一致
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实旧版 manifest、TASK 与场景源文件
  preconditions:
  - 准备可自愈的旧锁、改变后的任务正文和损坏的场景源
  steps:
  - 分别运行基线校验并读取锁文件和返回原因
  expected:
  - 旧锁按既有规则自愈，正文漂移和损坏场景源返回阻断及原有错误类别
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-03
  checks:
  - CHK-dd658f0fa13b
- id: S-04
  title: 检查登记共享真实收集语义
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 pytest 收集、登记配置与 manifest checks
  preconditions:
  - 临时测试包含声明的 marker 和具体 node ID
  steps:
  - 登记检查并验证执行命令选择与收集结果
  expected:
  - 登记的 test ID 和 marker 与实际收集结果一致，选择不匹配时阻断
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-04
  checks:
  - CHK-3c77f13118a8
- id: S-05
  title: owner profile 和风险判断保持一致
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 manifest、acceptance runner 与需求验证选择
  preconditions:
  - 多个 TASK 共享检查且一个 owner 有有效 accepted risk
  steps:
  - 分别选择 smoke、changed、full 和多 owner 并读取风险结果
  expected:
  - 两处消费者选择相同场景与依赖，风险只适用于授权 owner 和检查
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-04
  checks:
  - CHK-2d9c08da4eb3
- id: S-06
  title: 合并冲突和任务 Spec 范围共用事实源
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实临时 Git worktree、任务文档、Spec Context 与 manifest
  preconditions:
  - 两分支包含不同 check 配置且 TASK 声明 Spec-Refs 与 path_mapping
  steps:
  - 执行冲突检查和任务范围解析
  expected:
  - 冲突字段被报告，范围等于显式 Spec-Refs 与实际路径映射的并集
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-05
  checks:
  - CHK-8c89e458dbe7
- id: E-03
  title: 证据和状态转换保留前置条件
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Context Evidence、active marker 与 TASK 文件
  preconditions:
  - 任务 marker 与请求不匹配且存在未验证证据
  steps:
  - 尝试应用证据和提升 TASK 状态
  expected:
  - marker 不匹配时阻断，未验证证据不能使 TASK 变为 verified
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-03
  features:
  - FEAT-05
  checks:
  - CHK-bc2f501cf8a8
- id: S-07
  title: Gate 与 Session 使用领域 owner
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Context、Gate 判定、Session 投影及 AST 导入图
  preconditions:
  - Context 包含 required Rule 与完整 TASK 引用
  steps:
  - 运行 plan/code Gate 和 Session 投影并检查依赖边
  expected:
  - 判定与投影保持一致，plan quality 不再反向导入 Gate CLI
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-04
  features:
  - FEAT-06
  checks:
  - CHK-492475b44676
- id: E-04
  title: 预算与环境不足不能伪装为延后通过
  priority: P1
  level: unit
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Gate deferral 分类与 Rule Evidence
  preconditions:
  - 分别提供 review、heavy、budget 和 env 四类证据
  steps:
  - 对四类证据运行允许延后和不允许延后两种 Gate
  expected:
  - 允许延后时仅 review 和 heavy 可放行，budget 和 env 始终阻断
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-04
  features:
  - FEAT-06
  checks:
  - CHK-ddfa92004f07
- id: S-08
  title: Context 和工作流生命周期解除回边
  priority: P1
  level: system
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实临时 Git 项目、CLI、Context、marker 与 Session 投影
  preconditions:
  - 需求目录包含可启动 TASK、Context、场景和 manifest
  steps:
  - 执行 refresh、start、finish 和需求验证并检查依赖图
  expected:
  - 命令保持原有状态与输出语义，Context 与 workflow service 不再属于同一多模块 SCC
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-04
  features:
  - FEAT-07
  checks:
  - CHK-522b648cd656
- id: E-05
  title: 启动失败不留下半更新状态
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Context 文件、marker 与启动前置门禁
  preconditions:
  - 需求有可刷新的 Context 且 manifest 校验失败
  steps:
  - 记录 Context 和 marker 后调用 start 并再次读取
  expected:
  - start 返回阻断，Context 与 marker 保持启动前状态
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-04
  features:
  - FEAT-07
  checks:
  - CHK-2493448fb268
- id: S-09
  title: 并行批次复用同一层验证
  priority: P1
  level: system
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Git worktree、并行 merge 与共享验收检查
  preconditions:
  - 两个已合并 TASK 和一个 draft TASK 共享验收需求
  steps:
  - 执行批次 merge 后的 smoke 并读取运行记录
  expected:
  - 只选择已合并 TASK 的场景，共享检查执行一次
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-05
  features:
  - FEAT-08
  checks:
  - CHK-a2b62c44ccc6
- id: E-06
  title: 批次 smoke 失败保留工作现场
  priority: P1
  level: system
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 Git worktree、并行 run ledger 与失败检查
  preconditions:
  - 批次包含一个返回非零的 smoke 检查
  steps:
  - 执行合并验证并尝试非强制 cleanup
  expected:
  - 批次状态为 blocked，cleanup 被阻止，工作树和分支保留
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-05
  features:
  - FEAT-08
  checks:
  - CHK-886cc98bf17e
- id: S-10
  title: 最终棘轮阻止依赖环与私有导入
  priority: P1
  level: unit
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 canonical AST 导入图、allowlist 与合成反向边
  preconditions:
  - 所有前置能力完成且依赖批次推进至 7
  steps:
  - 运行依赖、私有符号、批次和 SCC 守卫并注入合成违规
  expected:
  - 两类 allowlist 为空、真实图无多模块 SCC，任一合成违规使对应守卫失败
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-06
  features:
  - FEAT-09
  checks:
  - CHK-6ce4a1cc8b64
- id: S-11
  title: 打包运行时和部署副本保持一致
  priority: P1
  level: system
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实 npm pack、临时项目 init、入口 shim 与同步检查
  preconditions:
  - 在临时目录准备四个平台的空项目
  steps:
  - 从打包产物安装并调用既有入口，检查 canonical 与部署副本
  expected:
  - 四平台入口可调用且部署内容与 canonical 一致，未增加运行时依赖
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-06
  features:
  - FEAT-09
  checks:
  - CHK-4557f6777cd3
- id: S-12
  title: 旧工作流入口保留需求绑定公开导入
  priority: P1
  level: integration
  exec: auto
  env: none
  components:
  - codeflow
  - pytest
  boundary: 真实固定入口 shim、共享需求验证模块与临时 Context 文件
  preconditions:
  - 通过 canonical 与部署副本的固定入口分别导入旧公开函数
  steps:
  - 从旧入口读取空需求目录的绑定，并读取损坏的 Context 文件
  expected:
  - 空目录返回空绑定，损坏 Context 明确报错，两个入口均保留旧导入
  expected_refs:
  - expected: 1
    steps:
    - 1
  design_refs:
  - runtime-boundary-hardening.design.md#2.5 验收条件
  rules:
  - RULE-06
  features:
  - FEAT-09
  checks:
  - CHK-00c21177da28
---
