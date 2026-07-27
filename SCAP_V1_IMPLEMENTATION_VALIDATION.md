# SCAP-V1 分阶段实施与产品验收

版本：2026-07-23
策略：`small_capital_aggressive_profit_v1`
规则：每阶段必须完成代码、语法、专项行为、产品入口和影响链验证后才能进入下一阶段。

## 阶段 0：独立版本身份与指标语义

状态：通过

实现：

- 新增独立控制模式 `aggressive_profit`，别名 `scap/profit`。
- CLI、实验启动器、运行器、汇总器和 Web 选择器统一识别。
- 输出目录使用 `ctrl_aggressive_profit`，不与 `factor_only` 混合。
- 小资金档位记录 SCAP-V1 身份、净利润目标、E0 初始退出、回撤研究边界、PF 研究门槛。
- 亏损加仓和主动替换均保持关闭。
- 汇总新增显式的 10 日前瞻收益字段与来源；旧字段暂保留兼容。

验证：

- `py_compile`：通过。
- `verify_scap_stage0_contract.py`：9 项通过。
- `main.py --help`：显示 `aggressive_profit`。
- Web HTML：显示“SCAP-V1 小资金进攻盈利（研究候选/无实盘权）”。

影响链：

- 上游数据、因子、ML、股票池：未改变。
- 决策：只有显式选择 `aggressive_profit` 时进入新模式。
- 执行、账本、NAV：未改变。
- 报告：新增字段，保留旧字段兼容。
- 上线状态：仍为 `research_candidate`。

## 阶段 1：三层仓位与现金拖累

状态：通过

实现：

- 新增纯策略模块 `small_capital_aggressive.py`。
- 分离 `risk_exposure_ceiling`、`desired_exposure_target`、`executable_exposure_target`。
- 补充 `signal_cash_drag`、`lot_feasibility_drag`、`risk_ceiling_drag`。
- SCAP 的追仓诊断使用期望仓位，订单引擎仍使用可执行上限，避免循环压低目标。
- 非 v3 或非一手适配资金档位选择 SCAP 时 fail closed。

验证：

- `py_compile`：通过。
- `verify_scap_stage1_exposure.py`：10 项通过。
- `verify_governance_mainline_v3.py`：20 项主线产品回归通过。

影响链：

- 非 SCAP 模式保持原仓位逻辑。
- SCAP 订单上限仍由现有执行引擎控制，没有绕过现金、一手或安全上限。
- 暴露账本和每日结果新增三层仓位及拖累字段。

## 阶段 2：最低佣金与成本压力

状态：通过

实现：

- 对每笔已平仓交易重新计算 0/1/5 元最低佣金。
- 同时计算 1×/1.5×/2× 滑点与市场冲击。
- 每个场景输出净利润、PF、胜率、总成本、成本/本金和是否盈利。
- SCAP 保存 `governance_scap_cost_stress_report.csv`。
- 实际账本成本不被压力场景改写，压力结果只用于准入。

验证：

- `verify_scap_stage2_cost_stress.py`：6 项通过。
- `verify_date_effective_fee_schedule.py`：5 项通过。
- `verify_governance_cost_capacity_stress.py`：7 项产品回归通过。

## 阶段 3：软惩罚与小资金候选效用

状态：通过

实现：

- SCAP 保留 100 万元基础流动性等生产硬约束。
- 原波动、2倍成交额、5/20日跌幅和前20%分位不再作为 SCAP 的组合 AND 硬删除。
- 新增 Alpha、成本、一手集中度、现金碎片和质量软惩罚。
- 尚未实现的组合重叠惩罚显式标为 `portfolio_optimizer_pending`，不伪造数值。

验证：

- `verify_scap_stage3_candidate_utility.py`：7 项通过。
- `verify_governance_mainline_v3.py`：20 项通过。
- `verify_governance_candidate_funnel_scope.py`：6 项通过。

## 阶段 4：一手组合优化

状态：通过

实现：

- SCAP 在效用最高的前15个正效用候选中做有界精确组合搜索。
- 同时满足剩余仓位槽、一手整数、可用现金和现金缓冲。
- 允许空组合，不为使用现金而买入负效用标的。
- 最大持仓数继续由现有 `max_positions` 控制，可用于3/4/5只配对实验。

验证：

- `verify_scap_stage4_portfolio_optimizer.py`：5 项通过。
- `verify_governance_mainline_v3.py`：20 项通过。
- `verify_board_specific_lot_rules.py`：7 项通过。

## 阶段 5：E0-E4退出与禁止亏损加仓

状态：通过

实现：

- E0：安全基线，复杂 Alpha/失败/止损/利润保护只记录。
- E1：启用 Alpha/信号失败退出。
- E2：增加买后失败与陈旧退出。
- E3：增加预登记损失控制，默认研究阈值 -12%。
- E4：增加右尾利润回撤保护。
- v3 原本强制纸面化的买后失败，在 SCAP E2 以后可以获得实验交易权。
- SCAP 默认关闭所有加仓，因此现有亏损分层加仓不能执行。

验证：

- `verify_scap_stage5_exit_policy.py`：11 项通过。
- v3生命周期数学：4项通过。
- 生命周期产品语义：11项通过。
- 执行规则：10项通过。

## 阶段 6：小资金准入与产品控制

状态：通过

实现：

- 新增 SCAP 专属准入报告，不使用机构25%单仓门槛单独否决。
- 净利润、PF、样本数、历史长度、市场状态、年份切片、成本压力和盈利风格分别判定。
- 胜率路径和右尾盈亏比路径二选一。
- 历史门槛全部通过也只进入下一研究阶段；前瞻纸面验证未完成时 `production_eligible=False`。
- Web 和 CLI 显式选择 E0-E4 与 E3 损失边界。
- Web 拒绝 SCAP 与非 v3 策略组合。

验证：

- `verify_scap_stage6_admission.py`：9 项通过。
- Web研究控制回归：2项通过。
- Web v3产品初始化回归：24项通过。

## 阶段 7：决策审计、真实产品短链与边界修复

状态：工程验收通过；盈利有效性未验证；无实盘权

实现：

- 候选门禁、入场公式和零售可执行排名均落盘 SCAP 效用分解、优化器选中标记、组合目标值、候选池大小和优化器状态。
- SCAP 候选审计优先展示优化器选中的候选，零售排名使用 `scap_candidate_utility`，不再出现“新逻辑交易、旧评分解释”的错位。
- 无已平仓交易时，成本压力报告返回完整表头的 0 行结果，不要求空 execution ledger 伪造已成交成本列。
- 中央配置验证器不再递归进入 `data/results/runs/reports` 等生成目录，避免 Windows 超长历史报告目录使验证器自身崩溃。

专项验证：

- `verify_scap_stage7_audit_trace.py`：4 项通过。
- `verify_scap_stage2_cost_stress.py`：扩充至 8 项，通过无闭合交易与输出 schema 边界。
- SCAP 阶段 0–7 专项测试：全部通过。
- `verify_governance_mainline_v3.py`、`verify_active_replacement.py`、`verify_execution_rules.py`、Web 研究控制：通过。

真实产品复验：

- 参数：2025-01-02，1 个交易日，2 万元，`mainline_v3_cabinet_native`，`aggressive_profit`，E0，PIT research。
- 成功目录：`results/decision_council/hs300_csi500_a500_strict/rules_based_president/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_profit/v3/run20260724_002228`
- 退出码：0。
- 三层仓位：风险上限 0.85、期望仓位 0.85、可执行仓位 0.5144268、一手可行性拖累 0.3355732。
- 审计：候选审计、入场公式和零售排名均含 SCAP 字段，前五个审计候选均显示优化器选中。
- 成本：没有闭合交易，压力报告为 0 行但表头完整。
- 准入：`research_stage_eligible=False`、`production_eligible=False`，符合短链不能证明盈利的预期。

真实运行发现并修复的 bug：

1. 两日冒烟首次发现 SCAP 决策字段未进入候选审计产物；已修复审计白名单、截断排序和零售排名口径。
2. 一日复验首次在保存阶段发现无闭合交易时空 execution ledger 缺列导致成本压力抛错；已改为合法空报告并新增回归。
3. 第一次前台复验因工具短超时遗留 Python 子进程；已精确终止遗留 PID，后续长运行改用独立日志和退出码监控。该问题属于运行编排，不属于策略收益逻辑。

未通过/未完成：

- `verify_centralized_configuration.py` 不再因超长目录崩溃，但真实发现多个既有 CLI 默认值仍散落在 `main.py`、`run_governance_experiments.py` 等文件；这是跨项目配置债，未在本次特殊策略修改中冒险迁移。
- 组合重叠惩罚因缺少可靠 PIT 行业/相关性合同仍标记 `portfolio_optimizer_pending`，没有伪造完成。
- 3/4/5 只、E0-E4 长窗、v3/v3_ml、赢家加仓和扩展股票池仍是待运行的隔离实验。
- 一日/两日冒烟只证明产品链可运行，不证明赚钱。

### CHANGE-20260724-01：SCAP-V1 阶段7审计闭环与无交易边界

- 对应末梢：WBS-09.08、WBS-14.08、WBS-16.08。
- 实现：候选效用和组合优化字段进入三个最终审计产物；审计排序与真实 SCAP 决策统一；无闭合交易时输出合法空成本压力报告。
- 修改文件：`runner.py`、`scap_cost_stress.py`、`verify_scap_stage2_cost_stress.py`、`verify_scap_stage7_audit_trace.py`、本验证记录和 WBS。
- 下游影响：报告可追溯性增强；无交易短链不再在保存阶段失败；非 SCAP 排序和有交易成本重定价不变。
- 验证：专项测试、主线回归和真实一日产品短链通过。
- 是否允许上线：否；只完成工程实现，不具备长窗盈利证据和前瞻纸面证据。

## 10. 2026-07-24 五日全链与长窗启动记录

### 五日全链

- 参数窗口：2025-01-02 至 2025-01-10，限制前5个交易日，实际结束于2025-01-08。
- 运行身份：2万元、`small_capital_branch`、`aggressive_profit`、`mainline_v3_cabinet_native`、E0、PIT research。
- 运行目录：`results/decision_council/hs300_csi500_a500_strict/rules_based_president/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_profit/v3/run20260724_003407`
- 运行日志：`results/scap_5day_20260724_003406.out.log`、`results/scap_5day_20260724_003406.err.log`。
- 结果：退出码0；stderr 0字节；最终NAV 19,782.84099；总收益-1.085795%；最大回撤-1.085795%。
- 约束：现金最低9,967.84元；最多5只；最终账户持仓权重49.6137%；最大单仓20.6543%；无负现金、无超仓、无重复订单、无零股成交。
- 成交：5笔买入、0笔卖出、0笔闭合交易；因此成本压力报告合法为0行，不能用该窗口判断5元最低佣金下的闭合交易盈利。
- 审计：200行入场审计均有SCAP效用；9行显示优化器选中；状态统一为`bounded_exact_top15`。
- 准入：研究和生产均不合格，符合短窗口只作产品验证的合同。

### 2025-01 至 2026-05 长窗

- 启动时间：2026-07-24 01:06:35。
- 回测窗口：2025-01-02 至 2026-05-29，不设置最大交易日数。
- Python PID：`165024`。
- 运行日志：`results/scap_long_2025_to_202605_20260724_010635.out.log`、`results/scap_long_2025_to_202605_20260724_010635.err.log`。
- 退出码文件：`results/scap_long_2025_to_202605_20260724_010635.exit.txt`，只会在进程结束后生成。
- 监督：持续5分19秒；PID唯一、Responding=True、CPU持续增长至约244.6秒、工作集约1.996GB、stderr 0字节。
- 交接：按用户要求停止监督但保留进程，不终止、不清理。
