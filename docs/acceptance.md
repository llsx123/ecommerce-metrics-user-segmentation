# 项目一验收记录

验收时间：2026-10-25　｜　验收人：项目作者　｜　环境：Windows 11 + Python 3.13.3

## 1. 干净环境复现

按照 README「快速开始」从零创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```

| 检查项 | 结果 |
| --- | --- |
| 依赖安装 | 成功（venv 内 pandas 3.1.0 / numpy 2.5.4 / matplotlib 3.11.2 / pytest 9.1.1） |
| 测试 | `41 passed`（venv 与系统 Python 的 pandas 2.3.3 环境均为 41 passed） |
| 完整流水线 | 成功，约 71 秒 |
| 指标可复现性 | venv（pandas 3.1.0）与系统环境（pandas 2.3.3）输出完全一致：净 GMV 2,641,721.52、订单 22,164、用户 11,705、复购率 45.03% |

## 2. 验收清单

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 从干净环境按 README 可安装并运行 | 上文 venv 全流程 | ✅ |
| 核心 SQL 能实际执行 | `sql/*.sql` 全部被 `metrics.py` 执行，`outputs/monthly_metrics.csv` 等有真实结果 | ✅ |
| 关键指标通过独立测试数据验证 | `tests/test_metrics_tiny.py`：5 用户 / 6 订单手算 435 / 430 / 86 / 25% 全部通过 | ✅ |
| SQL 与 Pandas 口径一致 | `outputs/reconcile_*.csv` 全为空；核心指标 10/10 | ✅ |
| 数据质量检查能识别设计好的异常 | 10 类、46 个注入缺陷，检测数量与 manifest 精确相等 | ✅ |
| 图表与报告来自实际运行 | `reports/figures/*.png` 与 `reports/analysis_report.md` 由 `run_pipeline.py` 生成，数字可在 `outputs/pipeline_summary.json` 核对 | ✅ |
| 自动化测试通过 | 41 passed，无跳过 | ✅ |
| README 命令/目录/输出与真实项目一致 | 手动执行 README 全部命令验证 | ✅ |
| 无凭证泄漏 / 虚构数据来源 / 未验证结论 | 无任何 token；README 与报告均声明合成数据；所有数字可追溯到产物 | ✅ |

## 3. 已知限制（不阻塞验收）

1. 合成数据分布由假设决定，不代表真实业务。
2. 复购率为窗口口径。
3. 流水线约 70 秒，主要耗时在数据生成与 SQL/Pandas 双实现；未做性能优化（本项目目标不是吞吐）。

## 4. 验收结论

**通过。** 可以进入项目二开发。
