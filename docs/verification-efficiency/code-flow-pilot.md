# code-flow 自身试点（进行中）

主要试点针对 code-flow 本身的验证流程。当前结果只证明下列测试在本次工作区通过，尚不能证明新旧方案的性能收益；真实任务工作负载的新旧同机对照、原始计时和输入/环境身份仍待采集。历史 `baseline-raw.json` 没有提供足以证明本次对照等价的身份，不能直接当作前后对比。

## 首轮检查（2026-10-30）

运行以下命令得到 **8 passed in 18.65s**。这些测试调用本项目真实的选择、证据、runner 和归档等实现，在临时 Git 项目中注入数据、输入变化和失败；临时工作负载不应被报告为 fluxion 实测。

```sh
python3 -m pytest -q --runxfail \
  tests/test_verification_efficiency_03.py::test_s05_shared_dependency_expands_scope \
  tests/test_verification_efficiency_03.py::test_e03_unknown_inputs_remain_conservative \
  tests/test_verification_efficiency_04.py::test_e04_identity_and_failure_invalidate_reuse \
  tests/test_verification_efficiency_05.py::test_s08_archive_reuses_complete_evidence \
  tests/test_verification_efficiency_05.py::test_e05_archive_reruns_only_missing_evidence \
  tests/test_verification_efficiency_05.py::test_b01_archive_detects_input_change_before_move \
  tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done \
  tests/test_verification_efficiency_06.py::test_e06_partial_failure_never_promotes_requirement
```

- 共享依赖变化扩大检查范围；未知输入保守选择；相同有效证据可复用。
- 环境、输入和时效变化导致重新执行；新失败和超时阻断，恢复后重新执行。
- 归档复用有效证据、补验缺口并检查移动前变化；批次部分失败不提升整个需求状态。

上述测试不是新旧方案的成本对照，也不是 S-11 骨架的完整验收。真实工作负载的可追溯身份与 S-11、S-12 的独立验收仍未完成。

同一命令随后运行三次，全部退出码为 0，墙钟时间分别为 15.734、15.701、15.600 秒，中位数 15.701 秒。原始输出、计时、命令、平台和所选代码输入的摘要见 `code-flow-current-runs.json`。这是当前版本运行测试套件的诊断数据，输入摘要只覆盖 canonical Python 脚本与所选测试文件，并未涵盖全部依赖和环境，因此不能用于证明新旧方案等价或计算性能收益，也不包含 task/批次/归档各自的冷运行与复用对照。

## fluxion 补充试点

已有数据库和浏览器基线及覆盖缺口见 `fluxion-pilot.md`；定向注入、新旧对比和浏览器关键链路仍未完成。责任：TASK-008 实现者。

## 旧版批次命令兼容性检查

使用本项目基线 commit `e3bda2516c1d4c20257ea665225034e05746b39a` 的隔离 clone，并复制当前试点测试 `tests/test_verification_efficiency_06.py`，运行 `python3 -m pytest -q --runxfail tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done`：旧版失败，原因是 `task verify` 不识别 `--tasks TASK-002`；当前工作区相同测试 **1 passed**。两个测试均使用隔离临时 Git 项目，其失败和成功说明该批次接口的行为差异，不能作为等价工作负载的性能对比。旧版要以其他方式选择同等检查，需先证明检查范围一致，再采集耗时。

## 归档回归检查

在相同旧版 clone 和当前工作区分别运行 `test_s08_archive_reuses_complete_evidence` 三次，六次均通过。完整 pytest 进程时间的中位数分别为旧版 1432.654 ms、新版 1674.653 ms；原始输出见 `code-flow-archive-regression-runs.json`。这个测试包含创建临时项目、安装、预先验收和归档等步骤，且旧版与新版目录不同；它验证两版该回归行为，不是单独的归档冷运行/复用运行，也不足以证明真实性能变化。

随后单独计量真实 `task archive` 命令：两版使用同一份 `test_verification_efficiency_05.py` 的隔离临时需求，先完成验收，再分别测试移除两条功能证据与保留证据；各三次。时间不含临时项目准备与预先验收。原始命令、结果及每条检查前后计数见 `code-flow-archive-old-raw.json`、`code-flow-archive-new-raw.json`。

| 运行时 | 条件 | 中位数 | 裁决 | 两条功能检查实际新增执行 |
| --- | --- | ---: | --- | --- |
| 旧 | 两条证据缺失 | 131.738 ms | 三次均阻断 | 0、0 |
| 新 | 两条证据缺失 | 493.390 ms | 三次均通过 | 1、1 |
| 旧 | 保留有效证据 | 386.824 ms | 三次均通过 | 0、0 |
| 新 | 保留有效证据 | 473.643 ms | 三次均通过 | 0、0 |

缺证据时两版裁决及实际工作量不同，耗时不可视为等价对照；保留证据时两条功能检查均未重启，但旧版没有报告全部验证器的 executed/reused，不能推断全流程启动次数。此处是合成临时需求上的真实 CLI 检查，不是本项目真实需求的完整 S-12 测量，也不是完整冷启动：预先验收已建立环境和部分证据。

## 真实需求的单任务验收检查

选取本项目已归档 `runtime-boundary-hardening` 的 TASK-001，实际执行其 S-01 和 B-01；新旧两版使用同一份 manifest 和两个测试文件，摘要分别记录在 `code-flow-task-old-raw.json`、`code-flow-task-new-raw.json`。每次重复先以 `--no-cache` 强制执行，再正常执行一次以建立可复用证据，最后正常复跑；三次独立重复均通过。

| 版本 | 强制执行中位数 | 正常复跑中位数 | 强制执行 / 复跑 |
| --- | ---: | ---: | --- |
| 旧 | 470.638 ms | 550.842 ms | 执行 2、复用 0 / 执行 0、复用 2 |
| 新 | 486.908 ms | 899.705 ms | 执行 2、复用 0 / 执行 0、复用 2 |

正常复跑前的证据建立过程也在原始文件中保留。旧版在干净基线 clone，新版在有大量未提交改动的实际工作区，路径和 Git 工作树不同，且本样本只调用 acceptance runner，不包含 task finish；因此时间差不能归因于运行时升级，也不满足 S-12 的完整同输入环境对照。

## 新版完整归档预检续查（2026-10-31）

隔离新版副本同步两份共享模板后，先前涉及副本一致性及文档的四组测试为 **40 passed**。对真实 `runtime-boundary-hardening` 需求执行完整归档，仍因全量 pytest 阻断：**12 failed、1049 passed、4 skipped、1 xfailed**，详见 `code-flow-real-archive-preflight-new.json`。预期失败是尚未完成的 S-12；正式验收仍用 `--runxfail`，不会将其视为通过。

这 12 项在新版隔离副本和主工作区单独重跑均失败，涉及 verifier 执行、证据锁、日志轮转、验证层和旧归档流程断言，不能再归因于副本不同步。归档未通过，不构成有效性能样本；当时还有另一个项目的验证进程运行，计时亦不适合用于对照。需要先定位并修复这些回归，再重新建立可比的 task、批次和归档实测；S-12 和最终报告仍未完成。

后续修复了日志月末漏读，并更新过时的测试 fixture 与归档流程断言；上述 12 项定向测试及主工作区全量 validators 均通过。同步到新版隔离副本后，真实需求完整归档预检也通过，见 `code-flow-real-archive-preflight-new-passed.json`。该预检期间仍有其他项目测试运行，旧版与新版测试集合也尚未证明等价，因此不将预检耗时用作 S-12 性能样本。
