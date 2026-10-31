---
schema: 1
requirement: verification-efficiency
scenarios:
- id: "S-01"
  title: "执行一次后输出选择与复用原因及分项非负耗时；复跑执行计数为零且复用计数准确"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实选择器、子进程计数器、证据存储与临时 Git 仓库"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-01 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["执行一次后输出选择与复用原因及分项非负耗时；复跑执行计数为零且复用计数准确"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-01"]
  design_refs: ["API-01","verification-efficiency.design.md#3.2.1 建立验证成本基线与可解释结果"]
  rules: []
  checks: ["CHK-3e1067d63390"]
- id: "E-01"
  title: "失败仍产生合法 JSON 与非零业务裁决；报告不包含传入的敏感环境值"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 CLI/Hook 子进程、stderr 与 JSON 输出"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-01 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["失败仍产生合法 JSON 与非零业务裁决；报告不包含传入的敏感环境值"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-01"]
  design_refs: ["API-01","verification-efficiency.design.md#3.2.1 建立验证成本基线与可解释结果"]
  rules: []
  checks: ["CHK-dc70b81ade78"]
- id: "S-02"
  title: "同一场景的 contract/component/integration checks 均独立登记；全部必要成员通过后场景才通过"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实场景解析、manifest 锁定与逐 check 证据"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-02 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["同一场景的 contract/component/integration checks 均独立登记；全部必要成员通过后场景才通过"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-02"]
  design_refs: ["API-02","verification-efficiency.design.md#3.2.2 支持低层测试组合覆盖与克制的 E2E 选择"]
  rules: []
  checks: ["CHK-28a34a2319cf"]
- id: "S-03"
  title: "零 E2E 且覆盖完整的计划通过；CAS 示例分解低层覆盖；不因比例或措辞自动要求 E2E"
  priority: "P0"
  level: "unit"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实计划质量函数、canonical 模板与示例 fixture"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-03 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["零 E2E 且覆盖完整的计划通过；CAS 示例分解低层覆盖；不因比例或措辞自动要求 E2E"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-02"]
  design_refs: ["API-02","verification-efficiency.design.md#3.2.2 支持低层测试组合覆盖与克制的 E2E 选择"]
  rules: []
  checks: ["CHK-17cf4cc4567c"]
- id: "E-02"
  title: "遗漏 expected、未知 check 或替换 level 却沿用旧 pass 均被识别；历史记录仍保留"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实组合映射、登记与重锁逻辑"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-02 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["遗漏 expected、未知 check 或替换 level 却沿用旧 pass 均被识别；历史记录仍保留"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-02"]
  design_refs: ["API-02","verification-efficiency.design.md#3.2.2 支持低层测试组合覆盖与克制的 E2E 选择"]
  rules: []
  checks: ["CHK-0c391a7c2b49"]
- id: "S-04"
  title: "普通 task 执行所属受影响检查；无关模块、全域浏览器和容量进程启动次数为零"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 Done Gate、临时 TASK 基线、validators 与可计数 check 子进程"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-04 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["普通 task 执行所属受影响检查；无关模块、全域浏览器和容量进程启动次数为零"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-03"]
  design_refs: ["API-03","verification-efficiency.design.md#3.2.3 让 task 与增量验证只承担必要范围"]
  rules: []
  checks: ["CHK-0af3cabf4c87"]
- id: "S-05"
  title: "修改共享鉴权、契约、测试或依赖锁选择全部受影响检查；无关修改复用未失效证据"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 Git diff、inputs glob、共享依赖文件与选择器"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-05 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["修改共享鉴权、契约、测试或依赖锁选择全部受影响检查；无关修改复用未失效证据"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-03"]
  design_refs: ["API-03","verification-efficiency.design.md#3.2.3 让 task 与增量验证只承担必要范围"]
  rules: []
  checks: ["CHK-c5e2a4a825f5"]
- id: "E-03"
  title: "无法证明影响范围时保守扩大并输出原因；无匹配路径不能把未验证 required check 变成通过"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实删除/重命名/新增文件、缺失基线及 Gate"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-03 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["无法证明影响范围时保守扩大并输出原因；无匹配路径不能把未验证 required check 变成通过"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-03"]
  design_refs: ["API-03","verification-efficiency.design.md#3.2.3 让 task 与增量验证只承担必要范围"]
  rules: []
  checks: ["CHK-bb88efd1770e"]
- id: "S-06"
  title: "跨层等价检查实际启动一次并分发各自证据；仅命令相似的不同检查分别执行"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 validators/review/acceptance 编排、子进程计数器与共享执行身份"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-06 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["跨层等价检查实际启动一次并分发各自证据；仅命令相似的不同检查分别执行"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-04"]
  design_refs: ["API-04","verification-efficiency.design.md#3.2.4 统一执行身份与有效证据复用"]
  rules: []
  checks: ["CHK-f41da1336b9a"]
- id: "S-07"
  title: "合法 CI 逐 check 证据在匹配输入下复用；缺少成员的多 check 场景仍不通过"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实证据导入、独立 checkout 与报告文件"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-07 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["合法 CI 逐 check 证据在匹配输入下复用；缺少成员的多 check 场景仍不通过"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-04"]
  design_refs: ["API-04","verification-efficiency.design.md#3.2.4 统一执行身份与有效证据复用"]
  rules: []
  checks: ["CHK-ff5b90ef21f4"]
- id: "E-04"
  title: "源码、测试、配置、环境版本或有效期变化触发失效；最新失败、skipped、超时不能被历史 pass 覆盖"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实输入/登记/环境身份、TTL 和最新失败证据"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-04 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["源码、测试、配置、环境版本或有效期变化触发失效；最新失败、skipped、超时不能被历史 pass 覆盖"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-04"]
  design_refs: ["API-04","verification-efficiency.design.md#3.2.4 统一执行身份与有效证据复用"]
  rules: []
  checks: ["CHK-060522858dca"]
- id: "S-08"
  title: "完整终验后同输入 archive 新增检查执行数为零，且源目录只在通过后移动一次"
  priority: "P0"
  level: "system"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 CLI、临时需求/Context/Git 项目、验证命令与目录移动"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-08 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["完整终验后同输入 archive 新增检查执行数为零，且源目录只在通过后移动一次"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-05"]
  design_refs: ["API-05","verification-efficiency.design.md#3.2.5 收敛归档入口并按证据缺口补验"]
  rules: []
  checks: ["CHK-19e8ab8761ef"]
- id: "E-05"
  title: "只补跑失效/缺失检查；补验失败保留源目录与失败原因，未失效检查不重跑"
  priority: "P0"
  level: "system"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 archive、失效 check 和未变化证据"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-05 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["只补跑失效/缺失检查；补验失败保留源目录与失败原因，未失效检查不重跑"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-05"]
  design_refs: ["API-05","verification-efficiency.design.md#3.2.5 收敛归档入口并按证据缺口补验"]
  rules: []
  checks: ["CHK-19c56268efc2"]
- id: "B-01"
  title: "验证与移动之间输入或 Context 改变时阻断；篡改 verified 状态不能生成有效证据"
  priority: "P0"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实移动前快照核对和文件变更注入"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 B-01 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["验证与移动之间输入或 Context 改变时阻断；篡改 verified 状态不能生成有效证据"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-05"]
  design_refs: ["API-05","verification-efficiency.design.md#3.2.5 收敛归档入口并按证据缺口补验"]
  rules: []
  checks: ["CHK-4c4d8fcbcdaa"]
- id: "S-09"
  title: "已完成批次能在其他 TASK 为 draft 时验证；依赖命中的共享 smoke 被选择，其他域不启动"
  priority: "P1"
  level: "system"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 verify --tasks、TASK 文档、局部 manifest 与 check 子进程"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-09 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["已完成批次能在其他 TASK 为 draft 时验证；依赖命中的共享 smoke 被选择，其他域不启动"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-06"]
  design_refs: ["API-06","verification-efficiency.design.md#3.2.6 统一批次关键链路验证与部分范围状态"]
  rules: []
  checks: ["CHK-55892ed92ca7"]
- id: "E-06"
  title: "部分范围通过不提升整个需求 verified；失败/未就绪保留实际状态与现场，不阻塞无关任务启动"
  priority: "P1"
  level: "system"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实批次验证、并行运行记录和未就绪依赖"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-06 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["部分范围通过不提升整个需求 verified；失败/未就绪保留实际状态与现场，不阻塞无关任务启动"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-06"]
  design_refs: ["API-06","verification-efficiency.design.md#3.2.6 统一批次关键链路验证与部分范围状态"]
  rules: []
  checks: ["CHK-f5d938b3c9c4"]
- id: "S-10"
  title: "归一化四平台正文一致；归档仅一个执行入口；普通 task 无默认全栈重测或固定 E2E 配额"
  priority: "P0"
  level: "unit"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实四平台命令模板、生成器与部署文件"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-10 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["归一化四平台正文一致；归档仅一个执行入口；普通 task 无默认全栈重测或固定 E2E 配额"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-07"]
  design_refs: ["API-07","verification-efficiency.design.md#3.2.7 同步计划、开发、终验与归档的四平台流程"]
  rules: []
  checks: ["CHK-3c81ceb1afe2"]
- id: "E-07"
  title: "既有命令和旧计划仍可读；用户配置保留、失败迁移可恢复、Hook stdout 协议保持正确且无新 npm 依赖"
  priority: "P0"
  level: "system"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实 CLI 安装/merge/迁移与原生 Hook fixture"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-07 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["既有命令和旧计划仍可读；用户配置保留、失败迁移可恢复、Hook stdout 协议保持正确且无新 npm 依赖"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-07"]
  design_refs: ["API-07","verification-efficiency.design.md#3.2.7 同步计划、开发、终验与归档的四平台流程"]
  rules: []
  checks: ["CHK-e6e4d2952bfb"]
- id: "S-11"
  title: "本项目真实验证流程识别输入变化、最新失败与失效证据"
  priority: "P1"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "本项目真实验证 runner、需求和检查输入、证据存储与故障注入"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-11 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["输入变化、最新失败和失效证据分别触发必要检查或阻断；未变化的有效证据可复用"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-08"]
  design_refs: ["API-08","verification-efficiency.design.md#3.2.8 用 fluxion-harness 场景验证收益与漏检边界"]
  rules: []
  checks: ["CHK-917f769cf4ab"]
- id: "S-12"
  title: "新旧方案各有同机三次原始运行及输入身份，汇总可重算；记录保留链路与残余风险"
  priority: "P1"
  level: "integration"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实试点命令、输入/环境标识、计时原始文件与报告验证器"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 S-12 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["新旧方案各有同机三次原始运行及输入身份，汇总可重算；记录保留链路与残余风险"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-08"]
  design_refs: ["API-08","verification-efficiency.design.md#3.2.8 用 fluxion-harness 场景验证收益与漏检边界"]
  rules: []
  checks: ["CHK-d9a7a9bf3f9a"]
- id: "E-08"
  title: "缺少实测或把合成数据标为真实 fluxion 时拒绝给出性能达标/覆盖通过结论"
  priority: "P1"
  level: "unit"
  exec: "auto"
  env: "local"
  components: ["cli","runtime","filesystem"]
  boundary: "真实报告验证器与缺失/合成数据 fixture"
  preconditions: ["隔离临时项目；实现阶段将所属测试骨架替换为真实断言"]
  steps: ["构造 E-08 的正常/异常输入并调用实际运行时边界","核对退出码、状态、执行计数或产物"]
  expected: ["缺少实测或把合成数据标为真实 fluxion 时拒绝给出性能达标/覆盖通过结论"]
  expected_refs: [{"expected":1,"steps":[1,2]}]
  features: ["FEAT-08"]
  design_refs: ["API-08","verification-efficiency.design.md#3.2.8 用 fluxion-harness 场景验证收益与漏检边界"]
  rules: []
  checks: ["CHK-401b34a6539a"]
---

# 验收场景唯一源

本文件由设计引用；计划只分配 owner/check，运行结果由 runner 写入。测试骨架可以收集，尚未实现；不得把收集成功或预期失败当成验收通过。
