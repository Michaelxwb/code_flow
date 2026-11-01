schema: 1
requirement: spec-optimization
scenarios:
- id: S-01
  title: 模块简写在发现根中存在
  priority: P0
  level: unit
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造多根临时项目并运行审计
  expected:
  - 不报告过时，记录命中的实际源码根
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-01
  design_refs:
  - API-01
  rules: []
  checks:
  - CHK-5325ecd49392
  owner: TASK-001
- id: S-02
  title: 所有根均不存在引用
  priority: P0
  level: unit
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造缺失路径并运行审计
  expected:
  - 该路径被标记 missing
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-01
  design_refs:
  - API-01
  rules: []
  checks:
  - CHK-4c5f5688c572
  owner: TASK-001
- id: E-01
  title: 配置根无效或越界
  priority: P0
  level: unit
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 配置缺失或越界根并运行审计
  expected:
  - 报告无效根，缺失引用仍为 missing
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-01
  design_refs:
  - API-01
  rules: []
  checks:
  - CHK-45d7e18adc6b
  owner: TASK-001
- id: E-02
  title: frontmatter 重复与正文重复
  priority: P0
  level: unit
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 对含三个 frontmatter 的 spec 运行冗余扫描
  expected:
  - 结构行被排除，重复规则正文仍被报告
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-02
  design_refs:
  - API-01
  rules: []
  checks:
  - CHK-f7ba62ca4a01
  owner: TASK-001
- id: S-03
  title: 项目自定义长规范阈值
  priority: P0
  level: unit
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 设置 2500 阈值并扫描 2400 与 2600 token 的 spec
  expected:
  - 前者不报冗长，后者报告冗长
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-02
  design_refs:
  - API-01
  rules: []
  checks:
  - CHK-46647cdde8f7
  owner: TASK-001
- id: S-04
  title: 预算模拟与真实 router 一致
  priority: P0
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 对多域文件运行 budget 与真实 router
  expected:
  - 匹配规范、组装 token 和限制一致，聚合独立报告
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-03
  design_refs:
  - API-02
  rules: []
  checks:
  - CHK-b64f2e47294b
  owner: TASK-002
- id: E-03
  title: 一次注入超过限制
  priority: P0
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造命中内容超过 min(total,l1_max) 的项目并运行 budget
  expected:
  - 报告非零超限、实际总量、限制和命中明细
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-03
  design_refs:
  - API-02
  rules: []
  checks:
  - CHK-e952dd601059
  owner: TASK-002
- id: B-01
  title: 组装开销与多路径去重
  priority: P0
  level: integration
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 路由多个命中同一 spec 的路径并模拟预算
  expected:
  - 每份规范不重复注入，组装总量等于真实 router 的估算
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-03
  design_refs:
  - API-02
  rules: []
  checks:
  - CHK-625017c0a982
  owner: TASK-002
- id: E-04
  title: 配置域没有目录
  priority: P0
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 对缺域目录的项目分别运行默认和严格 doctor
  expected:
  - 默认返回 warning；严格模式阻断并说明修复
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-04
  design_refs:
  - API-03
  rules: []
  checks:
  - CHK-cd9208385dbc
  owner: TASK-003
- id: E-05
  title: 跨目录声明
  priority: P0
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 将 test 域 spec 声明于 e2e 域并运行 doctor
  expected:
  - 输出跨域诊断，不修改配置
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-04
  design_refs:
  - API-03
  rules: []
  checks:
  - CHK-d6c57b4493d3
  owner: TASK-003
- id: S-05
  title: catalog 预算导致部分省略
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 配置小预算并获取实际 catalog
  expected:
  - 保留排序和既定预算，输出确切丢弃域和数量
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-05
  design_refs:
  - API-04
  rules: []
  checks:
  - CHK-5456268a63c5
  owner: TASK-003
- id: B-02
  title: catalog 预算不足以容纳内容与提示
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 配置极小 catalog_max 并生成 catalog
  expected:
  - 在不超预算前提下返回清晰的 catalog_max 过小错误及最小预算提示
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-05
  design_refs:
  - API-04
  rules: []
  checks:
  - CHK-ca6791fed55d
  owner: TASK-003
- id: S-06
  title: 查询规范影响
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造真实 Context 与任务文档，运行 impact
  expected:
  - 列出对应 Context、任务、required Rule 和状态，文件字节不变
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-06
  design_refs:
  - API-05
  rules: []
  checks:
  - CHK-3eef7502b2fb
  owner: TASK-004
- id: B-03
  title: 影响扫描达到上限
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造超出上限的任务目录并运行 impact
  expected:
  - 返回截断标记和已扫描数，不宣称影响集合完整
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-06
  design_refs:
  - API-05
  rules: []
  checks:
  - CHK-dba6c8b3bbe7
  owner: TASK-004
- id: S-07
  title: 安全提案及应用
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 构造含 Conventions 的大 spec、生成并批准提案后应用
  expected:
  - 预览显示差异和影响；应用后规则正文、ID 与 verifier 均不变
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-98cf54c9f2b9
  owner: TASK-006
- id: E-06
  title: 提案改变 RULE
  priority: P1
  level: integration
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 提交改变规则 ID 或 verifier 的提案
  expected:
  - 拒绝应用并报告差异，所有受影响文件字节不变
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-78250133c845
  owner: TASK-006
- id: E-07
  title: 目标 domain 不存在
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 对不存在的目标目录应用提案
  expected:
  - 拒绝应用并保持所有文件不变
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-e22ebc837d62
  owner: TASK-006
- id: E-09
  title: 在途 Context 或输入漂移
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 预览后更改输入或存在受影响在途任务时应用
  expected:
  - 拒绝并列出原因，不覆盖配置或任务文件
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-a45af989959a
  owner: TASK-006
- id: E-10
  title: 应用中途写入失败或中断
  priority: P1
  level: integration
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 在多文件事务的不同替换点注入失败并恢复
  expected:
  - 恢复原始字节或保留可恢复 journal，重复运行不产生半成品
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-9cf9e824389d
  owner: TASK-006
- id: S-08
  title: 按 SOP 在 fixture 仓执行
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 从体检按 SOP 执行至校验
  expected:
  - 示例命令可执行且结果与检查记录一致
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-08
  design_refs:
  - API-07
  rules: []
  checks:
  - CHK-c5aa7b5afa30
  owner: TASK-007
- id: S-09
  title: 平台与部署同步
  priority: P0
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 运行四平台 parity 与 sync check
  expected:
  - 四平台归一化一致且 canonical/deployed 无漂移
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-09
  design_refs:
  - API-07
  rules: []
  checks:
  - CHK-e1e811f14d0f
  owner: TASK-007
- id: E-08
  title: 缺省配置和既有契约
  priority: P0
  level: integration
  exec: auto
  env: local
  components:
  - runtime
  - filesystem
  boundary: 真实项目文件系统、规范解析器与路由器
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 在 0.8 风格项目运行现有及新增命令
  expected:
  - 旧 JSON 字段保留，默认阈值 500 且无新增运行时依赖
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-09
  design_refs:
  - API-07
  rules: []
  checks:
  - CHK-811d800d482e
  owner: TASK-007
- id: B-04
  title: 大仓预算与影响查询容量
  priority: P0
  level: capacity
  exec: auto
  env: capacity
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目；不依赖外部服务
  steps:
  - 在 100 份 spec、1000 任务文件的 fixture 中各运行 budget 和 impact 三次
  expected:
  - 分别记录环境与三次原始时间，各次均小于 2 秒
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-03
  - FEAT-06
  design_refs:
  - API-02
  - API-05
  rules: []
  checks:
  - CHK-267ce24a50e0
  owner: TASK-007
- id: S-10
  title: 只读生成结构优化提案
  priority: P1
  level: system
  exec: auto
  env: local
  components:
  - cli
  - runtime
  - filesystem
  boundary: 真实 CLI、运行时与隔离 Git 项目文件系统
  preconditions:
  - 隔离临时项目包含可拆分的 Conventions
  steps:
  - 运行 spec optimize --dry-run --json
  expected:
  - 输出输入摘要、映射差异、预算和影响范围，所有项目文件字节不变
  expected_refs:
  - expected: 1
    steps:
    - 1
  features:
  - FEAT-07
  design_refs:
  - API-06
  rules: []
  checks:
  - CHK-da5be90ffed6
  owner: TASK-005
