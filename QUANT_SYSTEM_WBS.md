# 量化系统逻辑与数学 WBS

版本：2026-07-23
状态：持续维护的架构契约
适用范围：TDX 日线数据、因子柜、治理策略、月度 ML、回测、报告与 Web 启动器

## 1. 使用规则

本文件不是一次性说明书，而是代码修改索引。任何策略逻辑、数学公式、数据口径、执行规则或报告字段的修改，都必须：

1. 先按 WBS 编号查找是否已有末梢，禁止无检查地重复实现。
2. 若已有末梢，在该末梢的“变更记录”追加日期、原因、代码文件、影响链和验证证据。
3. 若没有末梢，先在正确父节点下新增末梢编号，再修改代码。
4. 从被改末梢沿“下游”检查数据、训练、决策、执行、记账、报告和 Web 展示。
5. 至少运行与风险相称的语法检查、单元式验证和同口径回测。
6. 回测结果必须标注代码版本、日期窗、资金档位、策略版本、因子柜、成本模型和 PIT 状态；不同口径不得直接排名。

末梢状态：

- `生产硬约束`：不可因追求收益而绕过，例如时间隔离、T+1、涨跌停、现金和一手约束。
- `研究门槛`：可通过预登记实验修改，但不得用同一回测窗口反复调参后宣称有效。
- `诊断`：只解释结果，不改变交易。
- `待验证`：有实现但证据不足，默认不得获得交易权。

## 2. 顶层目标与数学契约

### 2.1 当前用户目标

当前资金画像为“小资金、可接受较大回撤、以最终净赚钱为第一目标”。对应目标函数是：

`最大化 TerminalNetProfit = FinalNAV - InitialCash`

同时必须满足：

- 成本后净收益，不使用毛收益代替。
- 不使用杠杆，不允许现金、持仓股数或库存穿透。
- 保留 A 股一手、T+1、停牌、涨跌停和交易费用约束。
- 保留 PIT、标签成熟日、训练隔离和数据泄漏检查。
- “可接受大回撤”只降低对波动/回撤的偏好权重，不等于允许无边界风险或错误模型扩大仓位。

### 2.2 胜率、盈亏比与赚钱的关系

单笔成本后期望：

`E = p × AvgWin - (1 - p) × AvgLoss - Cost`

其中 `p` 是胜率，`AvgWin` 和 `AvgLoss` 均取正数绝对值。盈亏比：

`PayoffRatio = AvgWin / AvgLoss`

利润因子：

`ProfitFactor = GrossProfit / |GrossLoss|`

因此：

- 高胜率可以配合较低盈亏比赚钱。
- 高盈亏比可以配合较低胜率赚钱。
- 两者不能都差；“只看其中一个”仍必须由成本后期望或利润因子兜底。
- SCAP 的唯一主目标是成本后期末净利润；压力利润因子只作健康门槛，胜率与盈亏比仅作路径诊断，不再直接控制仓位。任何概率预测取得交易权前还必须通过校准、有效样本量和漂移门禁。

### 2.3 当前建议的策略方向

优先研究 `mainline_v3_monthly_lgbm_hybrid`，但只能作为候选，尚不能上线。理由：

- 它允许规则排序与月度、时间隔离的 ML 排序连续融合，适合小资金从较大的股票池中集中选择少量标的。
- ML 权重由锁定验证收缩，验证 IC 不正时回退到规则排序。
- 2026-07-23 最后一次全程运行在 92.65% 因动态特征 schema 漂移失败，修复前没有可用的最终结果。
- 历史正收益运行与 2026-07-23 最新代码/日期窗并非同一口径，不能据此直接宣布策略有效。

当前执行建议：

- 小资金档位继续使用 2 万元、一手适配、最多 5 只、允许持有现金。
- 不为了“资金小”强制满仓。
- 用户授权的SCAP特殊版已开启主动换股，但仅允许每日一组、同期限可比、成本后LCB为正、挑战者仓位状态可执行的完整配对；研究门禁未通过，不能据此上线。
- 下一次必须做同日期、同因子柜、同成本、同资金档位的 `v3` 与 `v3_ml` 配对回测。

### 2.4 小资金进攻盈利特殊版

独立研究版本定义为 `small_capital_aggressive_profit_v1`（SCAP-V1），完整设计见 `SMALL_CAPITAL_AGGRESSIVE_PROFIT_V1.md`。该版本不得用 `factor_only` 名义冒充完整利润策略，也不得覆盖现有基线。

- 第一目标仍为成本后最终净利润。
- PF 兜底，胜率与盈亏比二选一路径，不要求同时很高。
- 利用小资金的一手组合可精确搜索、容量压力低、可集中和可等待优势。
- 生产硬约束不放松；未经证实的质量门槛作为可消融软惩罚。
- 用户授权的研究特殊版已经开启主动替换、亏损摊平和盈利加仓；三类动作不得各自直接下单，必须作为互斥提案进入同一成本后增量财富优化器。未完成校准和统一执行改造前仍为 `research_candidate`。
- 2025-01 至 2026-05 已被反复观察，不再视为完全封存样本外。

## 3. 末梢级 WBS

### WBS-00 目标、口径与实验身份

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-00.01 | 初始现金、资金档位、持仓数和现金缓冲形成唯一运行身份 | `config.py:get_backtest_capital_profile` | 08、09、12、13 |
| WBS-00.02 | 主目标为成本后期末净资产，不以胜率代替收益 | `config.py` 资金档位元数据；本文件 2.1 | 13 |
| WBS-00.03 | 每次运行固定日期窗、策略版本、因子柜和控制模式 | `main.py`、`main_launcher_web.py` | 全链 |
| WBS-00.04 | 不同日期窗、代码状态或 PIT 状态的结果不可直接排名 | `environment_manifest.json`、报告 | 13、14 |
| WBS-00.05 | 小资金风险偏好：高回撤容忍、无杠杆、允许现金 | `config.py:small_capital_branch` | 08、11 |
| WBS-00.06 | SCAP-V1 使用独立策略身份、控制模式和输出目录，当前仅为 research_candidate | `config.py`、`main.py`、`main_launcher_web.py`、`runner.py` | 全链 |
| WBS-00.07 | SCAP运行身份必须显式包含E阶段、损失边界、有效CLI覆盖、资金/成本/PIT/因子柜、代码状态及控制/原因/评分schema；缺项时禁止受控比较 | manifest、输出路径、摘要、比较器；待修复 | 全链 |
| WBS-00.08 | 所有跨模块数值必须登记语义、单位、方向、时间点、范围、缺失口径和交易权限；`rank_score[0,1]`、概率、收益率和人民币效用不得复用同一字段 | `ScoreContract`/schema registry；设计冻结候选 | 03、05、06、07、08、10、14、16 |

### WBS-01 运行环境与配置

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-01.01 | 固定解释器 `stock_ai`，不得依赖 PATH 中的 `python/py` | `AGENTS.md` | 全链 |
| WBS-01.02 | 配置启动时统一校验，非法参数 fail closed | `config.py:assert_valid_configuration` | 全链 |
| WBS-01.03 | Pipeline 步骤开关与参数分离 | `pipeline_steps.py`、`config.py` | 02-14 |
| WBS-01.04 | 运行进度包含状态、百分比、错误和 PID | `main_launcher_web.py`、`results/runtime_progress*.json` | 15 |
| WBS-01.05 | 实验快照记录有效运行参数 | `main.py`、`runs/run_*/runtime_config_snapshot.json` | 13、14 |
| WBS-01.06 | Web委派的Windows worker默认打开独立可见命令窗口；Ctrl+C必须写`interrupted/keyboard_interrupt` checkpoint并以退出码130结束，不得伪装为完成或无解释失败 | `main_launcher_web.py`、`main.py`、`runner.py`、`runtime_checkpoint.py` | 14、15、16 |

### WBS-02 数据时点与可投资范围

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-02.01 | TDX `.day` 解码为日线 OHLCVA | `functions/tdx_reader.py` 等数据模块 | 03、09、12 |
| WBS-02.02 | 交易日历只使用当时可知交易日 | `functions/data/trading_calendar.py` | 06、09、10 |
| WBS-02.03 | 股票主数据按生效日查询 | `functions/data/pit_level1_*` | 04、05 |
| WBS-02.04 | 指数成分按历史生效区间查询，禁止使用今日成分回填历史 | `functions/data_sources/historical_index_membership.py` | 04、13 |
| WBS-02.05 | 公司行动和复权信息按可得时间进入 | `functions/data/pit_level1_builder.py` | 03、09、12 |
| WBS-02.06 | 停牌、ST、板块权限和上市状态形成硬过滤 | `functions/investable_universe.py` | 05、07、09 |
| WBS-02.07 | 名义价格用于成交，一致复权价格用于收益研究 | `functions/pricing/*` | 03、09、12 |
| WBS-02.08 | PIT Level-1/2 状态为 research_only 时不得标记生产合格 | `functions/decision_council/research_gate.py` | 13、14 |

### WBS-03 特征与标签

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-03.01 | 技术特征仅由 `t` 及以前数据构造 | `functions/feature_engineering.py` | 04、05、06 |
| WBS-03.02 | 横截面标准化只使用当日横截面 | 因子模块 | 04、05 |
| WBS-03.03 | 缺失值处理必须区分“未知”“中性”和“不可用” | 各因子模块、06.07 | 04、06 |
| WBS-03.04 | 收盘后信号的买入标签从下一可成交日开盘开始 | `monthly_lgbm_hybrid.py:build_excess_return_labels` | 06 |
| WBS-03.05 | 标签成熟日为未来观察日，未成熟标签不得训练 | 同上 | 06 |
| WBS-03.06 | 净超额标签扣除股票级往返成本 | 同上 | 06、13 |
| WBS-03.07 | 禁止 future、label、执行日收盘等泄漏字段进入模型 | `functions/leakage_detector.py`、`pit_feature_contract.py` | 06、13 |

### WBS-04 因子注册、证据和因子柜

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-04.01 | 每个因子有唯一名称、方向、角色和经济家族 | `factor_candidate_registry.py`、`factor_semantic_contract.py` | 05 |
| WBS-04.02 | 近亲因子先聚合，避免数量多的家族重复投票 | `cabinet_native_scoring.py` | 05 |
| WBS-04.03 | 因子证据等级由覆盖、IC、稳定性和成本后价差决定 | `factor_evidence_grade.py` | 04.05 |
| WBS-04.04 | 因子替换必须同家族、同角色、证据更强 | `factor_replacement_engine.py` | 04.06 |
| WBS-04.05 | 因子柜构建、裁剪和 appeal 各自产生审计产物 | `clean_factor_cabinet_builder.py` 等 | 14 |
| WBS-04.06 | 未裁决基本面/事件家族保持 pending，无交易权 | `monthly_lgbm_hybrid.py:PENDING_FEATURE_SPECS` | 06 |

### WBS-05 候选评分与规则主线

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-05.01 | 单因子先转为当日横截面分位数 | `cabinet_native_scoring.py` | 05.02 |
| WBS-05.02 | 近亲中位数形成 family score | 同上 | 05.03 |
| WBS-05.03 | 家族等权且单家族权重有上限，缺家族权重不重分配 | 同上 | 05.04 |
| WBS-05.04 | `RoleScore = clip(0.5 + Coverage × Σw_f(F_f-0.5), 0, 1)` | 同上 | 05.05 |
| WBS-05.05 | Strict entry 优先，Proxy 仅补 Strict 缺失权威 | 同上 | 05.06 |
| WBS-05.06 | 最终规则分数 = base entry + timing adjustment - liquidity penalty | 同上 | 06、07 |
| WBS-05.07 | 风险分数只做惩罚/仓位，不可伪装成 alpha 奖励 | `runner.py:_apply_candidate_risk_penalty` | 07、11 |
| WBS-05.08 | 候选漏斗各层必须记录分母，口径不同时禁止算通过率 | `candidate_funnel_audit.py` | 14 |
| WBS-05.09 | SCAP 候选排名分数、预测收益率、预测胜率和人民币动作效用必须分列；量纲覆盖已修复，当前0—1评分与`scap_candidate_utility`分列并由运行时合同校验 | `small_capital_aggressive.py`、`mainline_v3.py`、`scap_v2_contracts.py`；已实现 | 07、08、09、10、13、14、16 |
| WBS-05.10 | 候选评分唯一接口输出 `ScoreContract`：字段名、语义、单位、范围、方向、as-of、来源和是否有交易权；兼容别名只能只读映射，不得反向覆盖权威字段 | 新 `score_contract.py`、schema registry；设计冻结候选 | 06、07、08、10、14、16 |

### WBS-06 月度 ML 与连续融合

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-06.01 | 月初仅用当日之前已成熟标签训练 | `OnlineMonthlyLGBMController._train_as_of` | 06.04 |
| WBS-06.02 | 按日期分组的 LambdaRank 学横截面排序 | `fit_monthly_lgbm_ranker` | 06.04 |
| WBS-06.03 | 内层 purge/early stopping/一标准误选择复杂度 | `monthly_lgbm_hybrid.py` | 06.04、13 |
| WBS-06.04 | 锁定外层验证计算 rank IC、NDCG、换手和稳定性 | 同上 | 06.05 |
| WBS-06.05 | ML 权重由验证证据收缩，且不超过预登记上限 | `calibrate_fusion_weight` | 06.06 |
| WBS-06.06 | `Hybrid=(1-w)×RulePercentile+w×MLPercentile` | `apply_continuous_rank_fusion` | 07 |
| WBS-06.07 | 动态 `cabinet_family_*_score` 推理缺列按训练 schema 补齐并用训练中位数填充；固定特征缺列仍报错 | `predict_daily_rank` | 07、14 |
| WBS-06.08 | ML 只改变排序，不直接批准/否决入场 | `monthly_lgbm_hybrid.py` | 07 |
| WBS-06.09 | 5 日模型负责入场排序，20 日模型负责持有/替换价值，返回单位不得与分位数混算 | `dual_horizon_lgbm.py`、`multi_horizon_value.py` | 07、10 |
| WBS-06.10 | 收盘后决策的校准标签必须从下一事实可成交时点开始，并同时保存 gross return、逐腿费用和 net return；成本只允许在标签或动作效用其中一处扣除一次 | `entry_calibration.py`、执行日历、成本模型；待修复 | 07、09、10、13、16 |
| WBS-06.11 | `sample_count=0` 的启发式先验不得标记为已校准或取得交易权；预测权须同时通过日期聚类有效样本、rank IC、概率校准和漂移门禁，失败时回退到因子柜排序而非伪概率 | `entry_calibration.py`、`small_capital_aggressive.py`、新 forecast authority gate；待修复 | 07、08、10、11、13、14、16 |
| WBS-06.12 | V3 Lean在交易窗口前使用至少252个交易日PIT历史只训练不交易地warm-up；固定warm-up与数据截止时，改变绩效起点不得改变同日ForecastDistribution或ActionPlan | `entry_calibration.py`、`runner.py`、runtime identity；proposed | 07、08、13、16 |

### WBS-07 入场决策

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-07.01 | v3 入场仅保留事实/状态硬否决，不重复旧软门槛 | `mainline_v3.py` | 07.04 |
| WBS-07.02 | 排名证据覆盖必须大于 0 | 同上 | 07.04 |
| WBS-07.03 | 新标的一手金额必须同时满足单股上限和可用现金 | 同上 | 07.04、09 |
| WBS-07.04 | 在可行候选中按最终分数顺序选择，直至持仓槽/现金耗尽 | 同上 | 08、09 |
| WBS-07.05 | 已持仓行与新候选行状态分离，selected 不等于已成交 | 同上 | 09、10 |
| WBS-07.06 | 小资金 v3 新入场从一手开始 | 同上、`retail_execution.py` | 08、09 |
| WBS-07.07 | SCAP-V1 仅保留生产硬过滤；波动、成交额倍数、短期跌幅和前20%分位作为可消融软惩罚 | `runner.py`、`small_capital_aggressive.py`、`mainline_v3.py` | 08、09、13、14 |
| WBS-07.08 | 每日最终规则/ML/风险评分只生成一次并同时供生命周期与入场使用；兼容字段填充不得再次执行选择器 | `runner.py`、`mainline_v3.py`；待修复 | 08、10、14、16 |

### WBS-08 仓位和小资金适配

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-08.01 | 2 万元档位初始现金 20,000、缓冲 2,000、最多 5 只 | `config.py:small_capital_branch` | 09、11、12 |
| WBS-08.02 | 单只持仓上限 40%，一手也不得穿透结构上限 | 同上、`retail_execution.py` | 09、11 |
| WBS-08.03 | 默认允许现金，不为满仓降低质量门槛 | `capital_usage_mode=allow_cash` | 07、11 |
| WBS-08.04 | 增仓必须通过生命周期 add_allowed 与分层约束 | `position_lifecycle.py` | 09、10 |
| WBS-08.05 | 高回撤容忍不改变无杠杆、现金非负和持仓数硬约束 | `execution_runtime.py` | 09、12 |
| WBS-08.06 | 当前利润目标元数据为 `terminal_net_profit_after_cost` | `config.py:small_capital_branch` | 13、14 |
| WBS-08.07 | 风险上限、策略期望仓位和一手可执行仓位分列，不得用可执行值回写并掩盖信号不足 | `small_capital_aggressive.py`、`runner.py` | 09、11、13、14 |
| WBS-08.08 | 当前`policy._select_scap_discrete_entries`与`_apply_unique_action_plan`会两次调用整数优化，连续分配器还前置决定补仓权重；必须收敛为一次联合ActionPlan，其他入口只能做候选缩减或影子诊断 | `policy.py`、`integer_action_optimizer.py`、组合分配器；2026-07-27复核仍未达标 | 09、10、11、13、14、16 |
| WBS-08.09 | 策略期望仓位必须使用“进入持仓槽位约束前”的正效用合格信号数；合格信号数、优化器选中数和可下单数必须分列，槽位已满不得伪装成无信号 | `mainline_v3.py`、`runner.py`；槽位分离已实现，现金/一手约束仍待继续拆分 | 11、13、14、16 |
| WBS-08.10 | 终端净利润目标下，组合优化应比较扣费后预期收益金额与整数手数；“每只固定一手、效用分数求和”只能作为诊断基线，不得直接视为利润最优 | `small_capital_aggressive.py`、`mainline_v3.py`；待实验 | 09、11、13、16 |
| WBS-08.11 | 原始正效用信号、结构性一手可行、当前现金可行、槽位可分配、优化器选中、零售可执行必须逐层分列；策略期望不得由当前现金可行性反向决定 | `mainline_v3.py`、`runner.py`、`candidate_funnel_audit.py`；待修复 | 11、13、14、15、16 |
| WBS-08.12 | 新开仓槽位、已有持仓加仓权和替换配对权必须分离；满5只只阻止第6只新标的，不得阻止已有持仓的合法正效用加仓 | `small_capital_aggressive.py`、`mainline_v3.py`、`runner.py`；设计冻结候选 | 09、10、11、14、16 |
| WBS-08.13 | 策略希望仓位、现金缓冲上限、风险上限、整手可行上限、订单后预计仓位和实际仓位分别落盘；各类现金拖累必须加总守恒；实际仓位超过上一决策授权上限时必须自检，只有不超过最小持仓整手且最多10个百分点的不可避免粒度偏差可通过 | `runner.py`、`exposure_runtime.py`、`runtime_integrity_audit.py`、报告/Web | 11、13、14、15、16 |
| WBS-08.14 | 每个决策日只能有一个权威 `ActionPlan`，联合选择退出、替换、亏损摊平、盈利加仓、新入场和持有；禁止先分配组合后再用替换/零售层覆写目标权重 | 新 integer action optimizer、`policy.py`、`runner.py`；设计冻结候选 | 09、10、11、12、13、14、16 |
| WBS-08.15 | 候选缩减使用规则分、稳健净边际利润、一手金额、风险和论点族的 Pareto 并集；禁止只按人民币绝对效用取前15而系统性偏向高价股，并输出每个被裁候选的支配证据 | 新 candidate reducer；设计冻结候选 | 07、08、11、14、16 |
| WBS-08.16 | V3 Lean直接优化订单后整数手数；SCAP连续分配、`_select_scap_discrete_entries`和第二次ActionPlan过滤全部降级为影子，每个decision_id只能产生一个ExposureAuthorization和一个ActionPlan | `policy.py`、`integer_action_optimizer.py`、`runner.py`；proposed | 09、10、11、12、14、16 |
| WBS-08.17 | `small_capital_lean`独立档位固定20,000元、默认1,000元缓冲、软目标4只/硬上限5只；Web空值继承档位，任何显式覆盖必须进入启动确认、runtime identity与输出身份 | `config.py`、`main_launcher_web.py`、`runtime_identity.py`；待修复 | 09、11、14、15、16 |
| WBS-08.18 | V3.1使用A/B/C/D分层交易权：A为0.50SE成熟权威，B为0.25SE且每只仅一手/总暴露不超40%，C只消费独立PIT规则回退分布且全组合最多一个一手，B+C探索合计不超55%，负证据D无交易权；normal/bull持仓少于4只且A/B正效用与全部硬约束有slack时，空新入场计划属于性质测试失败 | `entry_calibration.py`、新 forecast authority gate、`scap_v3_lean.py`、`integer_action_optimizer.py`；设计冻结候选 | 09、10、11、13、14、16 |

### WBS-09 订单、费用与成交

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-09.01 | `t` 日收盘决策，最早 `t+1` 可成交时点执行 | `execution_rules.py` | 12 |
| WBS-09.02 | 最低买入数量按市场和日期规则确定 | `security_trading_rules.py` | 07、09.05 |
| WBS-09.03 | 卖出遵守 T+1 库存，不允许库存下穿 | `execution_runtime.py` | 12 |
| WBS-09.04 | 停牌和涨跌停阻塞订单并记录原因 | `execution_rules.py` | 12、14 |
| WBS-09.05 | 佣金、最低佣金、印花税、过户费和滑点逐笔计入 | `fee_schedule.py`、`cost_model.py` | 10、12、13 |
| WBS-09.06 | 市场冲击按参与率/流动性估计并设合理上限 | `cost_model.py` | 10、12 |
| WBS-09.07 | 替换卖出与买入使用持久 pair id，卖出失败不得裸买 | `pending_orders.py`、`execution_runtime.py` | 10、12 |
| WBS-09.08 | 小资金回测输出0/1/5元最低佣金及1/1.5/2倍滑点冲击敏感性；真实券商费率确认前不得只引用零最低佣金结果 | `scap_cost_stress.py`、`runner.py` | 12、13、14 |
| WBS-09.09 | 全平/部分退出意图独立于原因字符串持久化；pending保留起因、最新原因、最高优先级原因和历史 | `policy.py`、`pending_orders.py`、`execution_runtime.py`；待修复 | 12、13、14、16 |
| WBS-09.10 | 主动替换必须以完整买卖对原子注册；条件现金可使用保守卖出净回款，任一腿注册前不可行时两腿均不得注册，完整性审计双向检查孤儿买腿和孤儿卖腿 | `replacement_contract.py`、`pending_orders.py`、`execution_runtime.py`、`runtime_integrity_audit.py`；设计冻结候选 | 10、12、13、14、16 |
| WBS-09.11 | 订单生命周期必须显式区分pending/partial/filled/cancelled/expired/rejected；订单与成交使用幂等键，重启或重放不得重复扣款、加股或重复收费 | `pending_orders.py`、`execution_runtime.py`、运行快照；设计冻结候选 | 10、12、13、14、16 |
| WBS-09.12 | 涨跌停、最小数量、数量步长和权限必须按交易日、板块、ST/退市整理期及上市初期状态生效；缺少可靠状态时fail closed并披露 | `security_trading_rules.py`、`execution_rules.py`、PIT证券主数据；设计冻结候选 | 02、07、12、13、16 |
| WBS-09.13 | 买单、替换对、最低佣金和现金缓冲统一进入 `CashReservationLedger`；可用现金只扣一次已注册保留，替换买腿只使用保守卖出净回款，提交/取消/部分成交均须幂等守恒 | `execution_runtime.py`、`pending_orders.py`、新 reservation ledger；设计冻结候选 | 10、12、13、14、16 |
| WBS-09.14 | 候选效用、ActionProposal、订单保留、成交、闭合配对、终端模拟清算、成本压力和准入必须消费同一不可变费用profile；最低佣金必须进入runtime identity，0/1/5元仅为显式压力情景 | `cost_model.py`、`action_utility.py`、`scap_cost_stress.py`、`runtime_identity.py`；待修复 | 08、10、12、13、14、16 |

### WBS-10 持有、退出与替换

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-10.01 | 持仓状态为 flat/building/holding/protecting/exiting/cooldown | `position_lifecycle.py` | 07、09 |
| WBS-10.02 | 安全减仓是组合风险动作，不是 alpha 评价 | `policy.py`、`runner_summary.py` | 13 |
| WBS-10.03 | 利润保护只在 MFE 达阈值后启动，避免把普通亏损伪称止盈 | `position_lifecycle.py` | 09 |
| WBS-10.04 | 信号失败、买后失败、陈旧和 alpha collapse 分别记录退出原因 | 同上、`policy.py` | 12、13 |
| WBS-10.05 | 主动替换要求同期限可比、扣除双边成本且 challenger LCB 优于持仓点估计 | `active_replacement.py` | 09 |
| WBS-10.06 | SCAP特殊版主动替换开启；每日最多一组，必须同时生成持久卖买pair，挑战者状态可执行，其他硬退出优先 | `config.py`、`contracts.py`、`engine.py`、`policy.py`、`runner.py` | 09、12、13 |
| WBS-10.07 | 重新启用替换前，固定样本外窗口的 5/10/20 日市场中性净 reward 均值和下置信界至少一个主期限必须为正 | `action_counterfactual_reward.py`；待补正式 admission gate | 10.06 |
| WBS-10.08 | 用户授权SCAP特殊版分别开启亏损摊平和盈利加仓；亏损线使用-3%/-6%分层，盈利线使用+5%/+10%分层，二者仍受因子、趋势、成交量、层数和单股上限约束；E4累计拥有E1-E4退出权 | `small_capital_aggressive.py`、`position_lifecycle.py`、`runner.py`、`policy.py` | 09、12、13、16 |
| WBS-10.09 | E0 是“仅安全退出、其余退出纸面记录”的反事实基线，不是可独立验收的盈利策略；E0长窗只能诊断入场与退出需求 | `small_capital_aggressive.py:scap_control_enabled`、`position_lifecycle.py` | 09、13、14、16 |
| WBS-10.10 | 活动退出必须先按E阶段分别授权每个信号，再在已授权信号中做原因优先级；未授权的高优先级纸面信号不得遮蔽已授权的低优先级真实退出 | `decision_arbitration.py`、`position_lifecycle.py` | 09、12、13、14、16 |
| WBS-10.11 | 退出原因使用唯一规范词典；生命周期、订单优先级、执行全平仓、控制触发、交易配对和Web不得混用`profit_hard_stop_exit`与`hard_stop_exit` | `exit_reason_contract.py`、`position_lifecycle.py`、`policy.py`、`execution_runtime.py`、报告/Web | 09、12、13、14、15、16 |
| WBS-10.12 | SCAP控制名称必须来自唯一注册表；未知、空白或拼写错误控制一律fail closed，不得默认启用 | `small_capital_aggressive.py`、`runner.py` | 09、10、14、16 |
| WBS-10.13 | SCAP E1信号失效家族连续3个决策日确认后才能退出；卖出后10个交易日冷却且不得以极端高分绕过 | `decision_arbitration.py`、`position_lifecycle.py`、`config.py` | 08、09、12、14、16 |
| WBS-10.14 | 同股票同决策只允许一个动作方向，卖出优先；新卖出意图必须取消旧pending买单，已有卖出意图必须拒绝新买单 | `decision_arbitration.py`、`policy.py`、`pending_orders.py` | 09、12、14、16 |
| WBS-10.15 | 当前新入场先做离散整数选择，补仓先依赖连续目标权重，已形成订单再由第二次ActionPlan过滤；目标合同仍要求所有动作先形成不可下单的`ActionProposal`并只由一次联合优化生成`ActionPlan` | `decision_arbitration.py`、`position_lifecycle.py`、`policy.py`、`execution_runtime.py`；2026-07-27复核为部分实现 | 08、09、12、13、14、16 |
| WBS-10.16 | 主动替换挑战者必须通过统一仓位状态；`blocked/cooldown/exiting/protecting_profit`不得先卖持仓，避免策略配对在零售适配层退化为孤儿卖腿 | `active_replacement.py`、`retail_execution.py`、`execution_runtime.py` | 09、12、13、16 |
| WBS-10.17 | 除硬安全退出外，固定动作优先级不得直接决定交易；所有动作以相同执行起点、期限和“不动作”基准的后验成本后增量财富分布比较，至少输出均值、日期聚类标准误、稳健下界和压力损失；执行层不得二次用软分数否决 | `action_utility.py`、`entry_calibration.py`、`decision_arbitration.py`、`policy.py`；待修复 | 08、09、11、12、13、14、16 |
| WBS-10.18 | 盈利加仓与亏损摊平必须是两条独立可达路径；当前触发幅度、支持分位、趋势/尾部风险、LCB正效用及连续分配正权重差仍形成硬AND，违反目标合同，须改为统一效用加少数事实硬约束 | `position_lifecycle.py`、`action_utility.py`、`policy.py`；2026-07-27确认未达标 | 08、09、11、13、14、16 |
| WBS-10.19 | 所有软动作效用必须相对同一个“不动作/持有现金”基准计算增量终值，禁止绝对收益、相对收益和双边替换收益混在同一比较表或重复扣成本 | `action_utility.py`、`decision_arbitration.py`；设计冻结候选 | 09、11、13、14、16 |
| WBS-10.20 | 整手优化不得把人民币效用与无量纲碎片/风险惩罚直接相加；必须把惩罚转换为人民币 certainty equivalent，并实际接入行业/论点/收益相关性、组合边际风险和非线性最低佣金；相关矩阵缺失或奇异时使用可披露的保守收缩回退 | 现 `small_capital_aggressive.py`，目标为唯一 action optimizer；待修复 | 08、09、11、12、13、14、16 |
| WBS-10.21 | `ActionProposal` 必须声明动作、股票、手数域、执行起点、期限、无动作基准、情景增量财富、逐腿成本、硬约束和证据来源；提案本身无交易权，只有通过唯一优化器并形成 `ActionPlan` 才可注册订单 | 新动作接口、`policy.py`、`execution_runtime.py`；设计冻结候选 | 08、09、11、12、13、14、16 |
| WBS-10.22 | V3 Lean所有软动作统一使用10日PIT收缩预测和`mu_shrunk-0.50×cluster_se`激进口径；新开仓、两类加仓、替换和软退出不得分别选择point/LCB，软证据进入效用而非硬AND | `entry_calibration.py`、`action_utility.py`、proposal factory；proposed | 08、09、11、13、14、16 |

### WBS-11 组合风险与暴露

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-11.01 | 安全代理决定暴露上限，不直接选股 | `safety_agent.py` 等 | 08、09 |
| WBS-11.02 | 单股、行业、策略组和风险贡献约束分别审计 | `allocation.py`、`runtime_integrity_audit.py` | 09、13 |
| WBS-11.03 | 实际暴露受一手可行性限制，目标暴露不得假装已实现 | `retail_execution.py`、`runner.py` | 13、14 |
| WBS-11.04 | SCAP 高仓位研究门槛以压力成本后净利润、压力 PF、模型权威、有效样本和集中度为主；胜率与盈亏比只作诊断。`_high_exposure_research_gate`已移除胜率/盈亏比硬否决，但压力利润和模型权威仍需收敛到唯一准入合同 | `runner.py:_high_exposure_research_gate`、`scap_admission.py`；部分实现 | 11.05、13、14、16 |
| WBS-11.05 | 高仓位还要求样本数、正已实现 PnL 和集中度合格 | 同上 | 08、09 |
| WBS-11.06 | 允许较大回撤只影响研究偏好，不绕过风险贡献和可交易性 | 本文件 2.1 | 全链 |
| WBS-11.07 | 新入场、两类加仓、替换和追仓共同消费唯一 `ExposureAuthorization`：NAV基准、目标/上限、现金缓冲、单股/论点族上限、压力损失预算和有效期；任何模块不得私有重算或绕过 | 新 exposure contract、`runner.py`、`policy.py`、`execution_runtime.py`；设计冻结候选 | 08、09、10、12、13、14、16 |
| WBS-11.08 | 风险输入至少采用收缩协方差或因子/聚类模型；样本不足、矩阵奇异或相关性缺失时降级到保守论点族/单股上限，并在 ActionPlan 中披露降级状态 | 风险模型、新 action optimizer；设计冻结候选 | 08、10、13、14、16 |
| WBS-11.09 | 协方差、相关系数、波动率、CVaR和人民币风险CE必须使用显式单位合同；禁止把收益协方差当相关系数乘人民币利润。收缩只能由一个权威风险入口执行，缺失时不得以零相关伪装无风险 | `runner.py:_rolling_candidate_covariance`、`scap_v3_lean.py`、`integer_action_optimizer.py`；待修复 | 08、10、13、14、16 |
| WBS-11.10 | 同一ActionPlan风险只允许一个人民币主惩罚：CVaR可用时不再叠加相关利润折扣，只有协方差时使用边际波动CE，两者缺失时只用单股/论点/压力硬上限；禁止风险证据重复扣减造成隐性保守 | 新风险单位合同、`integer_action_optimizer.py`；设计冻结候选 | 08、10、13、14、16 |

### WBS-12 回测记账

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-12.01 | 现金 = 前日现金 - 买入金额 - 费用 + 卖出净额 | `backtest_engine.py`、`execution_runtime.py` | 12.04 |
| WBS-12.02 | 持仓数量按成交更新，订单不等于成交 | 同上 | 12.04 |
| WBS-12.03 | 交易配对区分已平仓和期末未平仓 | `trade_pairing.py` | 13 |
| WBS-12.04 | NAV = 现金 + 可估值持仓市值，受限流动性另作折价披露 | 回测/估值模块 | 13 |
| WBS-12.05 | 公司行动、分红税和名义价格口径写入账本 | 数据与执行模块 | 13、14 |
| WBS-12.06 | 禁止零股订单、负现金、持仓超限和库存下穿 | `runtime_integrity_audit.py` | 13、14 |
| WBS-12.07 | 交易总回报PnL与PF必须纳入持有期公司行动现金、税和股本调整；价格交易PnL另列，不得与账户净利润混称同口径 | `trade_pairing.py`、公司行动账本；待修复 | 13、14、16 |
| WBS-12.08 | 回测期末不得为美化已实现指标强制平仓；必须分别保存按最后可靠名义价格估值的未平仓、可变现折价、终止日待执行订单及可选强平压力结果 | `trade_pairing.py`、`account_state.py`、`runner_summary.py`；设计冻结候选 | 13、14、16 |
| WBS-12.09 | 公司行动发生时必须同步调整持仓、可卖库存、成本、待执行订单和替换pair数量/价格；无法可靠处理配股、退市或长期无报价时fail closed并单列状态 | 公司行动账本、`pending_orders.py`、`execution_runtime.py`；设计冻结候选 | 09、13、14、16 |

### WBS-13 绩效、反事实与准入

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-13.01 | 总收益、年化、波动、最大回撤均从日 NAV 计算 | `runner_summary.py` | 14 |
| WBS-13.02 | 交易胜率、平均赢亏、盈亏比和利润因子从已平仓交易计算 | `trade_pairing.py` | 11、14 |
| WBS-13.03 | 最终赚钱优先看成本后总收益、PF、已实现和未实现 PnL | `runner_summary.py` | 14 |
| WBS-13.04 | 入场、持有、卖出、替换各自生成多期限反事实 reward | `action_counterfactual_reward.py` | 10、14 |
| WBS-13.05 | 反事实 reward 是诊断，不自动等同可交易利润 | 同上、报告 | 14 |
| WBS-13.06 | 基准池使用前期固定成分和固定再平衡口径，状态必须披露 | `performance_benchmark` 相关模块 | 14 |
| WBS-13.07 | research gate、formal gate、PIT gate 分离，任一未过不得上线 | `research_gate.py` | 14、16 |
| WBS-13.08 | 模型/策略比较必须同日期、同数据、同资金、同成本和同因子柜 | 比较运行器 | 16 |
| WBS-13.09 | 买入前瞻收益按 gross/variable_cost_proxy/full_cost_status 唯一命名，准入使用闭合交易成本压力而非伪造全成本前瞻值 | `runner_summary.py`、`scap_cost_stress.py` | 14、16 |
| WBS-13.10 | 小资金集中度门禁报告结构硬上限、实际集中度和机构门槛对照，不用机构25%门槛单独否决 | `scap_admission.py` | 14、16 |
| WBS-13.11 | SCAP准入证据量必须与最多持仓数和主持有期限相容；固定交易笔数不得隐式强迫高换手，年度比例需避免少切片离散突变 | `scap_admission.py`；待功效分析 | 14、16 |
| WBS-13.12 | SCAP唯一主目标为期末成本后净利润，压力利润因子为健康门槛；胜率只展示、盈亏比作二级诊断，二者不再共同或择一控制高仓位 | `runner.py:_high_exposure_research_gate`、`scap_admission.py`；设计冻结候选 | 11、14、16 |
| WBS-13.13 | 期末收益算术差、逐日复合主动收益和相对财富比必须分列命名并披露公式，不得共用“相对基准”模糊标签 | `runner_summary.py`、Web、Excel；设计冻结候选 | 14、15、16 |
| WBS-13.14 | 已用于问题发现、阈值选择或B0—B11择优的338日窗口一律标记development/audit，不得再称最终样本外；正式结论使用预注册主假设、未触碰前瞻窗口或纸面运行 | 比较运行器、run manifest、`scap_admission.py`；设计冻结候选 | 14、16 |
| WBS-13.15 | 多期限、多个模块和多组实验的择优必须报告有效样本量、重叠收益依赖、block bootstrap置信区间及多重比较校正；固定60条样本不得直接视为充分 | `evaluation.py`、`scap_admission.py`；设计冻结候选 | 14、16 |

### WBS-14 报告与审计产物

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-14.01 | 策略摘要同时给账户口径和已投入资本口径 | `runner_summary.py` | 用户 |
| WBS-14.02 | 交易对摘要给胜率、盈亏比、PF、已实现/未实现 PnL | `trade_pairing.py` | 用户 |
| WBS-14.03 | 候选漏斗给每层计数、拒绝数和可比性 | `candidate_funnel_audit.py` | 用户 |
| WBS-14.04 | ML 训练给训练月、成熟截止、特征、IC、NDCG、最佳迭代 | `monthly_lgbm_hybrid.py` | 用户 |
| WBS-14.05 | 动态 ML schema 填充记录缺失列数量和名称 | `predict_daily_rank` | 用户、16 |
| WBS-14.06 | 退化标志、PIT 状态、基准状态必须进入摘要 | `runner_summary.py` | 用户 |
| WBS-14.07 | 报告不得把 smoke test、失败运行或不完整运行当正式结论 | 报告流程 | 用户 |
| WBS-14.08 | SCAP 候选门禁、入场公式和可执行排名必须落盘效用分解、优化器选中状态与目标值，排序口径必须与实际决策一致 | `runner.py`；候选/入场/零售排名审计 CSV | 用户、16 |
| WBS-14.09 | 纸面退出原因必须由未经过阶段开关裁剪的反事实信号生成，至少覆盖损失控制；活动退出原因与纸面退出原因不得混用 | `position_lifecycle.py`；已实现 | 用户、10、13、16 |
| WBS-14.10 | 候选漏斗各层必须同一统计范围且单调不增；持仓、待执行订单和新入场候选不得混在同一漏斗层，`candidate_shortfall`必须使用对应的信号层 | `runner.py`、`candidate_funnel_audit.py`；待修复 | 用户、08、09、15、16 |
| WBS-14.11 | 控制触发摘要必须覆盖损失控制、陈旧退出、论点失败及规范化硬止盈原因，并分别对账纸面触发、活动触发、订单和成交 | `candidate_funnel_audit.py`；待修复 | 用户、10、12、15、16 |
| WBS-14.12 | 对历史持仓逐日展开全部单因子原始分、加权分、信誉分和权重占比；只读审计，不取得决策权 | `holding_factor_products.py` | 用户、15、16 |
| WBS-14.14 | 关闭、未请求或无事件的模块必须输出可读取的稳定schema和显式状态；禁止只含BOM无表头CSV | 各报告构建器、`runner.py:_save`；设计冻结候选 | 用户、15、16 |
| WBS-14.15 | 持仓因子产品必须区分原始分、校准分、实际决策权重和贡献金额；Excel补MAE、真实日期轴、动态覆盖公式并明确Top12与全因子范围 | `holding_factor_products.py`、`factor_curve_web.py`、`build_scap_factor_workbook.mjs`；设计冻结候选 | 用户、15、16 |
| WBS-14.16 | 新旧运行产物必须携带schema版本、迁移/兼容状态和字段级数据质量；缺失值、无穷值、异常值、重复键和过期价格不得静默填0 | 报告构建器、Web读取器、schema registry；设计冻结候选 | 用户、15、16 |
| WBS-14.17 | 每日落盘评分单位审计、预测权审计、候选缩减审计、动作提案表、唯一 ActionPlan、授权暴露、现金保留和执行对账；必须能从成交反推唯一决策模块和边际价值 | 报告构建器、新审计产品；设计冻结候选 | 用户、13、15、16 |
| WBS-14.18 | 大型产物按依赖 DAG 流式生成并逐件原子写临时文件后重命名；`core_complete`、`audit_complete`、`web_complete` 分阶段标记，单个附属表失败不得抹掉已完成核心回测 | `runner.py:_save`、artifact manifest；设计冻结候选 | 用户、15、16 |

### WBS-15 Web 启动与监控

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-15.01 | Web 默认小资金档位并显示真实默认参数 | `main_launcher_web.py` | 00、08 |
| WBS-15.02 | 策略版本和 ML 权重显式选择 | 同上 | 05、06 |
| WBS-15.03 | 启动前做 PIT、因子柜、日期和参数预检 | 同上、preflight 验证 | 全链 |
| WBS-15.04 | 失败状态保存原始异常信息和完成百分比 | 同上 | 用户 |
| WBS-15.05 | 运行完成链接必须指向该 run 目录而非旧结果 | 同上 | 用户 |
| WBS-15.06 | Web 仅在显式选择时启动 SCAP-V1，并显示“研究候选/无实盘权”、退出阶段和损失边界 | `main_launcher_web.py` | 00、09、13、16 |
| WBS-15.07 | 使用 `--no-live-monitor` 启动的既有长任务，只允许通过只读日志附着页补充进度；必须显示日志新鲜度、主PID存活、交易日进度、ETA、NAV、持仓和错误日志大小，不得伪造完整账户监控字段 | `tools/scap_log_progress_web.py` | 用户、16 |
| WBS-15.08 | SCAP Web必须同时展示原始/可行信号、槽位、优化器选中和最终订单数；不得只显示`entry_confirmed_count=0`而隐藏仍存在的合格信号 | `live_monitor_web.py`、`live_monitor_dashboard.py`；待修复 | 用户、08、14、16 |
| WBS-15.10 | SCAP初始化后monitor和结果页均提供逐因子曲线与Excel入口；保存完成前显示等待，完成后不需独立手工启动服务 | `holding_factor_products.py`、`factor_curve_web.py`、`live_monitor*.py`、`main_launcher_web.py` | 用户、14、16 |
| WBS-15.11 | 治理长窗必须有持久心跳、阶段/日期/ETA、最后成功检查点、完成标记和失败原文；重启从一致性检查点恢复，Web识别陈旧状态且不得把旧run显示为当前run | `runtime_progress.py`、`runner.py`、`live_monitor_web.py`；设计冻结候选 | 用户、14、16 |
| WBS-15.12 | Web 分别展示计算、核心保存、审计保存、Excel和因子页状态；每个入口绑定当前 run manifest，保存失败显示具体 artifact、重试资格和最后成功检查点，不得用空白页代表运行中 | `main_launcher_web.py`、`live_monitor_web.py`、artifact manifest；设计冻结候选 | 用户、14、16 |
| WBS-15.13 | Web启动的独立worker默认使用`visible_interruptible`命令窗口模式，窗口持续显示无缓冲stdout/stderr；自动化可显式切换`background_logged`，健康/进度API必须披露实际模式 | `main_launcher_web.py` | 用户、01、16 |

### WBS-16 验证与发布

| 末梢 | 合同/公式 | 主要实现 | 下游 |
|---|---|---|---|
| WBS-16.01 | 修改 Python 文件先 `py_compile` | `AGENTS.md` | 发布 |
| WBS-16.02 | 动态 ML schema 漂移必须有回归测试 | `verify_governance_monthly_lgbm_contract.py` | 发布 |
| WBS-16.03 | 主动替换启停和配对完整性必须有策略集成测试 | `verify_active_replacement_policy_integration.py` | 发布 |
| WBS-16.04 | 执行规则、T+1、涨跌停、费用和交易配对分别验证 | `verify_execution_rules.py` 等 | 发布 |
| WBS-16.05 | 完整策略上线前做同口径长窗、年份切片、成本压力和反事实检查 | 验证脚本/固定比较运行器 | 发布 |
| WBS-16.06 | 研究 gate 未通过时只能标记研究候选 | `research_gate.py` | 发布 |
| WBS-16.07 | SCAP-V1 按合同冻结→基线→入场消融→退出锦标赛→组合优化→股票池→前瞻纸面运行顺序准入 | `SMALL_CAPITAL_AGGRESSIVE_PROFIT_V1.md`、`verify_scap_stage0_contract.py` 至 `verify_scap_stage7_audit_trace.py` | 发布 |
| WBS-16.08 | 每次 SCAP 修改至少执行对应阶段专项测试、受影响主线回归和真实短链产物检查；短链不作为盈利证据 | `SCAP_V1_IMPLEMENTATION_VALIDATION.md` | 发布 |
| WBS-16.09 | 长窗运行必须记录总交易日、平均/中位单日耗时、因子数量、影子组合数量、CPU并行度和ETA；不参与当前交易决策的影子组合应作为独立诊断实验，不得默认把正式回测放大为因子数倍 | `runner.py:_build_shadow_runners`、`fast_shadow.py`、运行日志 | 资源验收、发布 |
| WBS-16.10 | E阶段发布前执行全部退出信号组合、原因全链闭环、六层漏斗单调性、公司行动黄金账本和运行身份可比性测试 | 新专项验证脚本；待实现 | 发布 |
| WBS-16.12 | 统一控制必须验证多退出授权、3日确认复位、同股卖出优先、pending买单取消、monitor双入口、14股×74因子覆盖和Excel公式/渲染 | `verify_decision_arbitration_contract.py`、`verify_factor_product_integration.py`、浏览器与工作簿验收 | 发布 |
| WBS-16.13 | SCAP新开仓漏斗只统计首次入场；加仓与替换买腿使用独立分母。20日产品验收必须检查配对两腿均登记/成交、动作归因字段、74因子覆盖和研究门禁 | `candidate_funnel_audit.py`、`verify_scap_unified_action_contract.py`、真实20日run | 发布 |
| WBS-16.14 | SCAP-V2按报告真相→原子替换→仓位/槽位→统一净效用→整数手优化→盈利加仓→亏损摊平→因子/PIT顺序施工；每阶段执行专项测试、5日构造、20日产品链和匹配338日消融 | `SCAP_E4_DETAILED_IMPLEMENTATION_SPEC_20260726.md`及新增验证脚本；设计冻结候选 | 发布 |
| WBS-16.15 | 发布验收增加断电/异常注入、重复运行幂等、部分成交、公司行动跨pending、期末未平仓、板块日期规则、schema迁移、内存/耗时预算和monitor陈旧状态测试 | 新专项验证脚本及20日故障链；设计冻结候选 | 发布 |
| WBS-16.16 | 小资金整手策略必须验证“优化器选中→组合整手权重→订单整手→T+1成交→实际仓位”同口径；旧版真实结果应被授权仓位自检判失败，修复后同日期短窗应通过，且不可把整手粒度偏差误判为新增买单越权 | `verify_scap_action_utility_v2.py`、`runtime_integrity_audit.py`、同日期5日真实短链 | 发布 |
| WBS-16.17 | 新接口增加性质/变形测试：分数单调变换不改变排序、提高费用不得提高净效用、复制候选不得改变既有订单、减少现金不得增加买单、关闭某动作只删除该动作、同一 ActionPlan 重放不得重复成交或收费 | 新 `verify_scap_v2_property_contracts.py`；设计冻结候选 | 发布 |
| WBS-16.18 | SCAP-V2 迁移固定为黄金回放→单位合同双写→校准修复→影子动作提案→唯一整数动作优化→现金/执行账本→统一风险授权→流式保存/Web→同口径经济检验；每阶段需专项、受影响回归、5日构造和20日产品验收后才能进入下一阶段 | `SCAP_V2_FULL_REMEDIATION_SPEC_20260726.md`、阶段验收记录；设计冻结候选 | 发布 |
| WBS-16.19 | Ctrl+C验收必须证明命令窗口可见、退出码130、全局进度为interrupted、run checkpoint保留最后完成日且非stale；策略修复另需验证校准warm-up起点不变性、补仓可达性和单日整数优化调用恰为一次 | `verify_runtime_checkpoint_and_schema_v2.py`及待补专项 | 发布 |
| WBS-16.20 | V3 Lean发布前自动生成实盘权威调用图，并断言每个decision_id优化器调用一次、Plan后无软否决、每张订单可反查唯一提案/计划、同单位字段单写入、warm-up起点不变；WBS末梢必须具备proposed/implemented/verified/released/deprecated状态和代码指纹 | 新架构一致性与性质测试；proposed | 发布 |
| WBS-16.21 | 黄金复原验收固定为配置/费用单一事实源→漏斗与拒绝血缘→风险单位→论点非恶化→购买软证据→赢家加仓→退出锦标赛；每阶段先静态检查与性质测试，再20日全链，最后同口径开发窗、滚动窗和未触碰留出窗 | `reports/SCAP_V3_1_GOLDEN_RESTORE_FULL_MODEL_SPEC_20260727.md`及待补验证脚本；设计冻结候选 | 发布 |
| WBS-16.22 | 激进性验收不得用机械满仓率，但必须验证非空计划可达性、A/B/C层级边界、同论点软2硬3、风险不重复扣减，以及“提高证据/现金不得减少可行买单、负证据不得通过回退取得交易权” | 新V3.1严格度与liveness性质测试；设计冻结候选 | 发布 |

## 4. 2026-07-23 运行复盘

### 4.1 最后一次运行 bug

运行目录：

`results/governance/hs300_csi500_a500_strict/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_factor/v3_ml/run20260723_180048`

进度文件结论：

- 开始：2026-07-23 18:00:48
- 失败：2026-07-23 21:03:22
- 完成度：92.65%
- 异常：`candidate frame is missing trained ML features: ['cabinet_family_size_style_score']`

根因链：

`当月训练历史出现 size_style 家族`
→ `模型 schema 锁定该列`
→ `后续某日该家族没有合格 proposal`
→ `cabinet_native_scoring 未生成整列`
→ `predict_daily_rank 把动态缺列当固定契约损坏`
→ `运行在推理阶段失败`

修复合同见 WBS-06.07，回归验证见 WBS-16.02。

### 4.2 23 日已完成 v3 结果

正式完成目录：

`results/governance/hs300_csi500_a500_strict/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_factor/v3/run20260723_121807`

关键结果：

| 指标 | 数值 |
|---|---:|
| 日期窗 | 2025-01-02 至 2026-05-29 |
| 交易日 | 338 |
| 总收益 | -18.28% |
| 年化收益 | -14.01% |
| 最大回撤 | -19.38% |
| 平均实际仓位 | 38.89% |
| 已投入资本收益 | -27.71% |
| 平仓数 | 166 |
| 平仓胜率 | 47.59% |
| 盈亏比 | 0.539 |
| 利润因子 | 0.489 |
| 已实现 PnL | -2,492.46 元 |
| 未实现 PnL | -1,192.65 元 |
| 研究准入 | blocked |

这个结果不是“胜率略低但盈亏比高”，而是胜率和盈亏比都不足，成本后期望为负。放宽回撤或提高仓位只会放大亏损。

### 4.3 主动替换诊断

| 项目 | 数值 |
|---|---:|
| 主动替换平仓 | 160 / 166 |
| 主动替换平仓 PnL | -2,418.28 元 |
| 替换交易平均持有 | 12.8 日 |
| 总执行成本 | 466.12 元 |
| 替换 5 日市场中性 reward 均值 | -0.250% |
| 替换 10 日市场中性 reward 均值 | -0.232% |
| 替换 20 日市场中性 reward 均值 | -0.225% |

结论：当前最明确的负贡献源是未经样本外证实的高频主动替换，不是风险控制过严。对应修改见 WBS-10.06。

## 5. “既要又要”冲突清单

| 冲突 | 错误做法 | 当前提炼 |
|---|---|---|
| 胜率 vs 盈亏比 | 同时设很高硬门槛 | PF 兜底，胜率/盈亏比二选一 |
| 收益 vs 回撤 | 因能承受回撤就取消全部风险约束 | 降低回撤惩罚偏好，但保留无杠杆和硬约束 |
| 集中 vs 分散 | 小资金仍机械持有很多只 | 最多 5 只，一手可行；是否降至 3 只必须 A/B 验证 |
| 满仓 vs 质量 | 小资金必须把现金用光 | 默认允许现金，信号不足不强制部署 |
| 换股速度 vs 成本 | 预测优势为正就每天替换 | 先过成本、LCB、样本外 reward admission |
| ML 灵活性 vs schema 稳定 | 任一缺列直接崩溃或全部静默补值 | 仅动态家族列可审计填充，固定列缺失硬失败 |
| 因子多 vs 信息多 | 因子数量直接增加投票权 | 近亲→家族→角色分层聚合 |
| 历史收益 vs 当前有效 | 拿旧代码/旧窗口最好结果指导上线 | 只比较同口径当前代码结果 |

## 6. 变更影响登记

### CHANGE-20260723-01：修复月度 ML 动态家族 schema 漂移

- 对应末梢：WBS-03.03、WBS-06.07、WBS-14.05、WBS-16.02。
- 修改：动态 `cabinet_family_*_score` 缺列时按训练 schema 建列，使用训练中位数填充，并输出填充数量/名称。
- 不修改：固定基础特征仍 fail closed；模型、训练特征、权重和融合公式不变。
- 上游检查：WBS-04.02 家族列按当日 evidence 动态生成。
- 下游检查：WBS-06.06 融合、WBS-07 入场排序、WBS-14 审计字段。
- 验证：`verify_governance_monthly_lgbm_contract.py` 全部通过。

### CHANGE-20260723-02：小资金档位关闭未验证主动替换

- 对应末梢：WBS-00.05、WBS-08.06、WBS-10.05、WBS-10.06、WBS-10.07、WBS-16.03。
- 修改：`small_capital_branch.active_replacement_enabled=False`，通过运行器、决策上下文和 policy 显式传递。
- 不修改：入场、持有、安全减仓、真实生命周期退出、T+1、费用与一手规则。
- 上游证据：160/166 平仓来自替换，替换多期限反事实均值为负。
- 下游检查：订单原因、交易配对、PnL、报告诊断。
- 验证：`verify_active_replacement_policy_integration.py` 全部通过。

### CHANGE-20260723-03：登记小资金进攻盈利特殊版设计

- 对应末梢：WBS-00.06、WBS-05.09、WBS-07.07、WBS-08.07、WBS-08.08、WBS-09.08、WBS-10.08、WBS-13.09、WBS-13.10、WBS-15.06、WBS-16.07。
- 用户目标：优化小资金、可集中、可承受较大波动和以最终赚钱为先的优势，形成独立特殊版本完整方案。
- 现有实现检查：`factor_only` 是诊断模式；执行、账本、PIT、因子柜和 ML 可复用；候选硬过滤、仓位口径、退出、最低佣金和研究门槛需分阶段验证或扩展。
- 数学/逻辑变化：本次只登记设计，不改变交易。设计规定最终净利润第一、PF兜底、胜率/盈亏比二选一，新增候选效用、三层仓位和整数手数组合优化合同。
- 修改文件：`SMALL_CAPITAL_AGGRESSIVE_PROFIT_V1.md`、`QUANT_SYSTEM_WBS.md`。
- 上游输入影响：无；未改变数据、因子、股票池或训练。
- 下游模块影响：无运行时影响；未来实现将影响候选、仓位、退出、成本报告、研究准入和 Web。
- 不变量：PIT、时间隔离、T+1、涨跌停、一手、现金非负、无杠杆、账本守恒和主动替换关闭。
- 验证：文档结构与 WBS 末梢检查；无 Python 逻辑修改，不执行策略回测。
- 回测：无；SCAP-V1 当前状态为 `research_candidate`。
- 是否允许上线：否。

### CHANGE-20260723-04：SCAP-V1 阶段0独立身份与指标语义

- 对应末梢：WBS-00.06、WBS-13.09、WBS-15.06、WBS-16.07。
- 实现：新增 `aggressive_profit` 控制模式及 `scap/profit` 别名，CLI、实验启动器、运行器、汇总器、Web 和输出目录统一隔离；资金档案登记特殊版本与研究参数。
- 指标：新增显式 10 日前瞻收益字段及来源，旧字段保留兼容；尚未伪造 excess/proxy 口径。
- 修改文件：`config.py`、`main.py`、`run_governance_experiments.py`、`runner.py`、`runner_summary.py`、`main_launcher_web.py`、`verify_scap_stage0_contract.py`。
- 上游影响：无数据、因子、ML 或股票池变化。
- 下游影响：显式选择新模式时使用独立控制语义和输出路径；账本与执行不变。
- 验证：相关文件 `py_compile` 通过；`verify_scap_stage0_contract.py` 9 项通过；CLI help 与 Web 产品入口通过。
- 验收记录：`SCAP_V1_IMPLEMENTATION_VALIDATION.md`。
- 是否允许上线：否，继续阶段1。

### CHANGE-20260723-05：SCAP-V1 阶段1三层仓位

- 对应末梢：WBS-08.07、WBS-11.03、WBS-14.01、WBS-16.07。
- 实现：新增纯函数计算风险上限、策略期望和一手可执行仓位；信号、手数可行性和风险上限拖累分别记账。
- 修改文件：`small_capital_aggressive.py`、`runner.py`、`verify_scap_stage1_exposure.py`。
- 关键修正：追仓诊断比较期望仓位，订单引擎使用可执行上限；不再用可执行值回写并伪装为期望值。
- 兼容性：仅 `aggressive_profit` 使用新语义；其他模式不变。
- fail closed：SCAP 必须配合 v3 和一手适配资金档位。
- 验证：专项10项通过；`verify_governance_mainline_v3.py` 20项通过。
- 是否允许上线：否，继续阶段2。

### CHANGE-20260723-06：SCAP-V1 阶段2成本压力

- 对应末梢：WBS-09.05、WBS-09.06、WBS-09.08、WBS-13.03、WBS-16.07。
- 实现：新增逐笔闭合交易成本重定价，覆盖0/1/5元最低佣金与1/1.5/2倍滑点冲击。
- 产物：`governance_scap_cost_stress_report.csv`，包含场景净利润、PF、胜率、成本/本金和盈利状态。
- 不变量：不修改真实成交账本；压力场景仅用于研究准入。
- 验证：专项6项、日期费率5项、容量成本回归7项全部通过。
- 是否允许上线：否，继续阶段3。

### CHANGE-20260723-07：SCAP-V1 阶段3候选效用

- 对应末梢：WBS-05.09、WBS-07.07、WBS-14.03、WBS-16.07。
- 实现：SCAP 将旧波动、成交额倍数、短期跌幅和前20%分位从硬删除改为软惩罚；基础可交易性和100万元流动性硬约束保留。
- 效用：Alpha奖励减去最低佣金成本、一手集中度、现金碎片和质量惩罚。
- 审计：未实现的组合重叠项标记 pending，不伪造。
- 兼容性：非 SCAP 的 v3 和其他模式保持原筛选。
- 验证：专项7项、v3回归20项、漏斗产品回归6项通过。
- 是否允许上线：否，继续阶段4。

### CHANGE-20260723-08：SCAP-V1 阶段4一手组合优化

- 对应末梢：WBS-07.04、WBS-08.08、WBS-09.02、WBS-16.07。
- 实现：在前15个正效用候选中搜索不超过剩余仓位槽的整数手组合，目标为总效用减现金碎片惩罚。
- 行为：允许空组合；不强制买负效用候选；现金缓冲、板块交易单位和结构上限不变。
- 兼容性：非 SCAP 仍使用原贪心选择。
- 验证：专项5项、v3回归20项、板块交易单位7项通过。
- 是否允许上线：否，继续阶段5。

### CHANGE-20260723-09：SCAP-V1 阶段5退出族

- 对应末梢：WBS-08.04、WBS-10.03、WBS-10.04、WBS-10.08、WBS-16.07。
- 实现：E0至E4逐级启用信号失败、买后/时间失败、损失控制和右尾利润保护；默认E0。
- 加仓：SCAP 默认阻断所有加仓，现有亏损摊低只保留诊断。
- 损失控制：E3默认研究阈值-12%，持有不足3日不触发；E0仍记录纸面信号。
- 兼容性：非 SCAP 的 v3 后入场失败纸面化规则不变。
- 验证：专项11项、生命周期数学4项、产品语义11项、执行规则10项通过。
- 是否允许上线：否，继续阶段6。

### CHANGE-20260723-10：SCAP-V1 阶段6准入与产品控制

- 对应末梢：WBS-13.03、WBS-13.07、WBS-13.10、WBS-15.06、WBS-16.07。
- 实现：新增小资金专属准入报告；机构25%门槛只作诊断，40%账户结构上限仍为硬约束。
- 准入：成本后净利润、PF、样本、时间、市场状态、年度切片、成本压力及胜率/右尾路径分别审核。
- 产品：CLI与Web显式提供E0-E4和损失边界；SCAP配非v3时拒绝。
- 防误上线：历史门槛通过仍不赋予生产权，前瞻纸面门槛固定为未通过。
- 验证：专项9项、Web研究控制2项、Web v3初始化24项通过。
- 是否允许上线：否，进入全链收口。

### CHANGE-20260724-01：SCAP-V1 阶段7审计闭环与无交易边界

- 对应末梢：WBS-09.08、WBS-14.08、WBS-16.08。
- 现有实现检查：真实两日运行发现决策字段未落审计，真实一日运行发现无闭合交易时保存阶段失败。
- 数学/逻辑变化：不改变候选效用公式或交易动作；只统一审计排序口径，并定义零闭合交易的合法空压力报告。
- 修改文件：`runner.py`、`scap_cost_stress.py`、`verify_scap_stage2_cost_stress.py`、`verify_scap_stage7_audit_trace.py`。
- 下游影响：三个候选审计产物可解释实际 SCAP 决策；无交易 smoke test 可完整保存。
- 不变量：非 SCAP 排序、有闭合交易成本重定价、现金/一手/T+1/PIT 约束不变。
- 验证：SCAP 阶段0–7、主线V3、替换、执行、Web专项通过；真实一日产品运行退出码0。
- 回测口径与结果：仅2025-01-02一日、E0、2万元，用于产品链验证，不作为收益证据。
- 是否允许上线：否，仍缺长窗、隔离实验和前瞻纸面证据。

### CHANGE-20260724-02：既有SCAP长窗的只读日志进度网页

- 对应末梢：WBS-15.04、WBS-15.07、WBS-16.08。
- 用户目标：不重启、不停止正在运行的长窗回测，通过网页查看还需多久以及程序是否仍在运行。
- 现有实现检查：原任务使用`--no-live-monitor`，没有原生状态流；首次桥接复用了完整治理监控页，只写`stage`字段，且PowerShell `Move-Item -Force`无法覆盖既有状态文件，桥接在第二次刷新时退出，网页停在69/338。
- 修复：状态桥接改为UTF-8直接写入；新增专用只读日志网页，直接解析控制台进度，显示百分比、交易日计数、elapsed、ETA、日期、NAV、持仓、日志更新时间、主PID状态和stderr大小。
- 修改文件：`tools/scap_log_progress_bridge.ps1`、`tools/scap_log_progress_web.py`、`QUANT_SYSTEM_WBS.md`。
- 上游输入影响：只读取`scap_long_2025_to_202605_20260724_010635.out.log/.err.log`和主PID状态；不读取或修改策略数据。
- 下游影响：仅新增本机只读HTTP页面；不改变候选、订单、成交、现金、持仓、NAV或报告。
- 不变量：主回测PID `165024`不重启、不停止；网页进程与回测进程隔离。
- 验证：固定解释器Python 3.10.19；`py_compile tools/scap_log_progress_web.py`通过；页面`/`与`/api/status`均HTTP 200；API实测158/338、46.7%、ETA 12:47:26、主进程alive、stderr 0字节。
- 运行地址：`http://127.0.0.1:62985/`；网页辅助PID `235588`。
- 是否允许上线：该页面仅为本机运行辅助工具，不改变SCAP研究准入状态。

### CHANGE-20260724-03：SCAP长窗中途性能诊断

- 对应末梢：WBS-05.08、WBS-14.03、WBS-16.05、WBS-16.09。
- 操作：只读检查实时网页API、主PID、20秒CPU/IO、进程树、逐日耗时分布和治理主循环；不修改、不停止当前回测。
- 当前状态：167/338（49.4%），最新日期2025-09-08，NAV约20,500，已用11:33:22，ETA约11:49:58，stderr 0字节。
- 耗时证据：167日平均249.1秒/日；前20日312.4秒/日；最近20日166.4秒/日；已明显加速但总量仍大。
- 主要瓶颈：当前因子柜74个因子，`enable_shadow_portfolios=True`使每个交易日顺序执行每个因子的`FastShadowPortfolioRunner.step()`，每次重新调用`build_daily_candidates()`；随后正式路径再次构建候选、执行SCAP策略并写候选审计。
- 并行性：主回测是单一Python进程；虽有16逻辑CPU和底层库线程，但日级影子组合循环没有按模型并行。
- 逻辑冲突：SCAP的声誉模块当前不获得交易控制权，但完整影子组合仍默认运行，形成“诊断完整性”和“正式回测速度”同时最大化的既要又要。
- 当前处理：不中途切换`enable_shadow_portfolios`，避免同一回测前后口径变化；保持PID `165024`继续运行。
- 后续建议：新增预登记的SCAP正式快速口径，关闭不参与决策的影子组合；完整74因子影子归因作为独立诊断运行。两种口径必须验证正式交易/NAV一致后，快速口径才能作为默认长窗。
- 是否影响收益结论：本条只解释资源耗时，不改变当前策略结果或准入状态。

### CHANGE-20260724-04：SCAP长窗完成状态与最终运行快照

- 对应末梢：WBS-13.03、WBS-13.07、WBS-14.07、WBS-15.07、WBS-16.05、WBS-16.09。
- 状态采样：2026-07-24 18:27，控制台338/338、100%、最终日期2026-05-29、退出码0、stderr 0字节；正式运行目录`run20260724_010636`。
- 结果快照：338日，最终NAV 19,761.32元，总收益-1.1934%，年化-0.8937%，最大回撤-11.1868%，Sharpe -0.0090，最终现金10,188.32元、持仓5只。
- 交易证据：闭合交易0、已实现PnL 0、PF/胜率/盈亏比均无定义、成本压力0行；E0没有产生研究退出，不能把期末未实现净值当成已验证交易盈利。
- 准入：`research_stage_eligible=False`、`production_eligible=False`；失败包含净利润、PF、闭合交易、历史长度、正切片、成本压力和盈利风格门槛。
- 监控bug：日志已到338/338且退出码存在时，Windows `OpenProcess` 状态仍可能让网页显示alive；修复为`current >= total`优先判定完成。
- 修改文件：`tools/scap_log_progress_web.py`、`QUANT_SYSTEM_WBS.md`。
- 影响链：只修正只读网页完成状态，不修改已完成回测产物或任何策略逻辑。
- 是否允许上线：否；该结果直接否决E0作为盈利版本，下一步必须按预登记顺序研究E1退出，而不是提高仓位或启用加仓。

### CHANGE-20260724-05：SCAP E0长窗全链路根因定位

- 对应末梢：WBS-07.07、WBS-08.06、WBS-08.07、WBS-08.09、WBS-08.10、WBS-09.03、WBS-09.04、WBS-10.08、WBS-10.09、WBS-13.03、WBS-14.02、WBS-14.09、WBS-16.05。
- 用户目标：定位338日长窗亏损和零闭合交易究竟发生在哪个环节；本条只读分析，不修改策略、订单、账本或回测产物。
- 运行口径：`run20260724_010636`，2025-01-02至2026-05-29，2万元，SCAP `aggressive_profit`、E0、v3、主动替换关闭。
- 主根因链：生命周期层确实识别了大量退出风险，但E0阶段开关在订单生成前把它们全部降为纸面信号；1681条持仓状态中`paper_exit_state=1070`，而`exit_state=0`。纸面触发包括硬止盈270、损失控制133、利润回吐810、买后失败289、信号失败464、陈旧退出68；活动触发、退出订单和卖出成交均为0。
- 执行层排除：成交账本只有5笔`normal_buy`且全部成交，没有任何卖单进入执行层。因此T+1、停牌、涨跌停和卖单撮合不是本次“零退出”的首要故障点；断点位于“退出信号识别→阶段授权”。
- 资金链次因：5只各买一手后槽位占满，默认禁止加仓且主动替换关闭，组合此后冻结；期末现金10,188.32元，平均实际仓位50.63%，平均风险上限91.66%，说明低仓位主要来自固定一手/五槽位/无增仓无替换，而不是风险上限压制。
- 三层仓位逻辑缺陷：优化器选中后才统计`qualified_entry_count`；槽位占满时该值连续335/338日为0，随后“信号数为0”函数把策略期望仓位回落为实际仓位，使无容量被错误呈现为无信号，违反WBS-08.07。应拆分槽位约束前合格信号、优化器选中和最终可下单三个计数。
- 利润目标错配：当前组合器每个候选只允许一手，目标为无量纲效用之和，且剩余现金仍足够买一手时现金碎片惩罚为0；它没有直接最大化`预期收益率×投入金额−成本`，因此不能证明与`terminal_net_profit_after_cost`一致。
- 入场质量次因：5笔买入的5日命中率0、平均收益-4.09%、超额-6.70%；10日命中率20%、平均收益-0.81%、超额-9.25%；20日命中率80%、平均收益+5.20%，但超额仍为-10.53%。说明短期入场明显差、20日绝对收益并非全无，但相对基准持续落后。
- 最终损益解释：期末5只中2盈3亏，未实现PnL合计-459.16元；公司行动现金流+220.48元，合成账户损失-238.68元。没有止损、陈旧退出或利润保护把路径收益实现为闭合利润。
- 审计次级缺陷：`paper_loss_containment_exit=133`存在，但E0下`paper_exit_reason`仍可能引用已被阶段开关裁剪的活动损失控制信号，导致纸面原因不完整；该缺陷不导致零卖单，但会误导退出归因。
- 准入解释：无闭合交易使PF、胜率、盈亏比和闭合成本压力均无定义；本结果只能证明E0不具备盈利版本资格，不能用来判断E1-E4哪一个最优。
- 客观结论：首要断点是退出阶段授权，不是Web、进程、行情读取或成交引擎；第二层问题是持仓槽位冻结和期望仓位审计失真；第三层问题是短期入场质量与利润目标优化器错配。
- 下一步受控实验：先修复审计计数和纸面退出原因，但不改变交易；随后在同数据、同代码基线、同成本、同股票池下只切换E0→E1，验证真实卖单、闭合交易和成本后净利润。若E1仍无改善，再依次E2、E3、E4；不得同时开启加仓、替换或改选股。
- 验证证据：只读核对`governance_execution_ledger.csv`、`governance_position_state_ledger.csv`、`governance_trade_pairs.csv`、`governance_entry_payoff_report.csv`、日级摘要、期末持仓及公司行动账本；未执行新回测。
- 是否允许上线：否。

### CHANGE-20260724-06：六项薄弱点独立报告、审计修复与五日产品验收

- 对应末梢：WBS-08.07、WBS-08.09、WBS-08.10、WBS-10.08、WBS-10.09、WBS-14.08、WBS-14.09、WBS-16.07、WBS-16.08。
- 用户目标：每个薄弱点独立形成证据、根因、解决方案和修复有效性报告；报告目录为`reports/scap_weak_points_20260724/`，含总览及01至06六份报告。
- 已修复一：`mainline_v3.py`在持仓槽位限制前记录正效用合格信号，并记录剩余槽位和`mainline_v3_no_remaining_slot`；`runner.py`分列`pre_slot_qualified_entry_count`、`optimizer_selected_entry_count`、`exposure_signal_count`，SCAP期望仓位使用前者，非SCAP口径不变。
- 已修复二：`position_lifecycle.py`使用同一退出优先级分别生成活动原因与未阶段裁剪的纸面原因；E0纸面损失控制不再因活动权限关闭而丢失原因，真实卖单权限不变。
- 暂不直接修改：E0阶段矩阵、五槽位/加仓/替换组合、利润金额优化器和入场因子。前两项必须先做E1-E4单变量实验；利润优化器必须等待预期收益校准准入；5笔入场样本不足以安全重拟合。
- 专项测试：新增`verify_scap_weak_point_audit_remediation.py`，验证正效用口径、满槽位时信号与选中分离、纸面损失原因及原因优先级；全部通过。
- 回归测试：`py_compile`通过；`verify_scap_stage1_exposure.py`、`verify_scap_stage4_portfolio_optimizer.py`、`verify_scap_stage5_exit_policy.py`、`verify_governance_mainline_v3.py`、`verify_scap_stage7_audit_trace.py`、`verify_governance_v3_lifecycle_math.py`、`verify_execution_rules.py`、`verify_lifecycle_alert_semantics.py`全部通过。
- 产品验收第一次尝试：漏传`--capital-profile small_capital_branch`，预检按合同拒绝并报`aggressive_profit requires a retail lot-aware capital profile`；保留stdout/stderr证据，不计为代码失败。
- 最终产品验收：`run20260724_185544`，2025-01-02至2025-01-08共5日，E0、v3、小资金档位、关闭影子组合；退出码0、stderr 0、最终NAV 19,782.84元、持仓5只。
- 字段对账：五日`pre_slot_qualified_entry_count`为136/131/125/121/128，优化器选中为5/3/1/0/0；满槽位两日仍保留正效用信号，期望目标不再由“选中数0”循环回写。最后一日有22个候选明确记录`mainline_v3_no_remaining_slot`。
- 生命周期对账：执行账本5笔买入、0笔卖出；2025-01-08出现1条`post_entry_failure_exit`纸面原因、活动原因为空，证明E0纸面/活动语义分离。短链没有达到-12%损失边界，纸面损失原因由专项合成场景验证。
- 行为可比性：两次有效五日运行的NAV与持仓路径一致；正效用计数收紧只改变审计口径，不改变本短链选中、成交和账户结果。
- 有效性结论：WBS-08.09与WBS-14.09达到逻辑及产品层验收；它们不构成盈利提升证据。01/02/04/05的经济有效性仍须按报告中的隔离实验完成。
- 修改文件：`mainline_v3.py`、`runner.py`、`position_lifecycle.py`、`verify_scap_weak_point_audit_remediation.py`、六份薄弱点报告、总览和本WBS。
- 是否允许上线：否；下一经济实验仍是固定其他变量只把E0切换为E1。

### CHANGE-20260724-07：修复后跨模块矛盾复审

- 对应末梢：WBS-08.07、WBS-08.09、WBS-08.11、WBS-10.08、WBS-10.10、WBS-10.11、WBS-14.10、WBS-14.11、WBS-15.08、WBS-16.08。
- 用户目标：检查六项薄弱点修复后是否产生新矛盾，以及既有模块间是否仍有隐藏逻辑冲突；本条只读诊断，不修改交易行为。
- P0退出阶段遮蔽：`position_lifecycle.py`先按未授权原始信号选择原因，再清除阶段未启用原因。E3中E4利润回吐/硬止盈可先占据原因并被清空，从而遮蔽已启用的E3损失控制；E1/E2同样可能被更高阶段纸面信号遮蔽。必须改为“先逐信号授权，后做活动原因优先级”。
- P0陈旧退出越级：阶段合同规定`stale_exit`自E2启用，但活动`exit_reason`清理把`stale_time_exit`与`signal_failure_exit`合并检查；E1的信号失败已启用，因此E1可错误放行陈旧退出。同时状态列`stale_time_exit`仍按正确的`stale_exit`开关为False，形成`exit_state=True`但专属活动标志False的内部矛盾。
- P0硬止盈词典冲突：生命周期主原因写`profit_hard_stop_exit`，`policy.ORDER_PRIORITIES`和`execution_runtime.full_exit_reasons`只登记`hard_stop_exit`。真实E4硬止盈会退化为`normal_sell`订单原因，虽零目标通常仍能全平，但控制订单数、成交归因和按原因PnL会错误。
- P1仓位分层仍不完整：新`pre_slot_qualified`来自包含`cash_feasible`与一手可行性的`eligible`，因此只解决了槽位反向污染，尚未解决“当前现金不足→信号数归零→期望仓位回落”的循环。需继续拆为原始正效用、结构可行、现金可行、槽位、优化器、零售执行六层。
- P1下游旧语义：最终五日产品中2025-01-07/08的槽位前信号为121/128、优化器选中为0，但`governance_exposure_reconciliation.csv`仍将两日`candidate_shortfall_flag=True`。Web也只展示`entry_confirmed_count`，用户仍会看到“0个确认”而看不到大量槽位前信号。
- P1候选漏斗非单调/混范围：五日产品有4/5天出现`capital_pass_count > entry_confirmation_pass_count`，最后两日为0对4；后层大于前层。`ideal_portfolio_count=5`同时包含持仓，`order_count`还可能包含前一决策日待执行订单，不能作为同一新入场漏斗直接比较。
- P1控制摘要缺项：`candidate_funnel_audit.py`仅汇总利润回吐、买后失败、信号失败和硬止盈，遗漏损失控制、陈旧退出和论点失败；WBS-14.09修复后的纸面损失原因仍无法在统一控制摘要中闭环。
- P2信号计数饱和：五日正效用信号为121至136，远高于最多15个优化候选和5个持仓槽位；`desired_exposure_from_signal_count`在4个以上即饱和，数量不再表达强弱。后续应使用预登记的Top-K、绝对期望边际或分层信号强度，而不是把上百个弱正效用等同于强信号。
- P2 Web词典：Web纸面原因中文映射未登记`loss_containment_exit`，新原因会显示内部英文标识；不影响成交，但影响可理解性。
- 修复归因：候选漏斗/Web旧语义是WBS-08.09新增字段未同步下游造成的新不一致；退出遮蔽、陈旧越级、硬止盈别名和控制摘要缺项为既有问题，本次深度复审首次系统定位。
- 验证证据：静态核对`mainline_v3.py`、`runner.py`、`position_lifecycle.py`、`policy.py`、`execution_runtime.py`、`candidate_funnel_audit.py`及Web；动态核对`run20260724_185544`日级结果、暴露对账和候选漏斗；固定解释器确认E1下`signal_failure_exit=True`而`stale_exit=False`。
- 安全结论：在WBS-10.10和WBS-10.11修复并通过组合触发测试前，不应开始E1-E4经济比较；否则阶段差异本身不可信。
- 修改文件：仅报告、WBS；未修改Python交易逻辑，未启动新回测。
- 是否允许上线：否。

### CHANGE-20260724-08：SCAP-V1全链路完整修改设计

- 对应末梢：WBS-00.07、WBS-07.08、WBS-08.10、WBS-08.11、WBS-09.09、WBS-10.10、WBS-10.11、WBS-10.12、WBS-12.07、WBS-13.11、WBS-14.10、WBS-14.11、WBS-15.08、WBS-16.10。
- 用户目标：对全部已知薄弱点、逻辑薄弱点、跨模块冲突及新增问题给出可施工、可验证、可归因的完整修改方案。
- 设计文件：`SCAP_V1_FULL_REMEDIATION_PLAN_20260724.md`，覆盖18类问题、Phase A至H施工顺序、禁止并行变更、测试矩阵和最终产品形态。
- 新增P0发现：SCAP未知控制名默认返回True，存在拼写错误绕过阶段矩阵的fail-open风险；必须使用唯一控制注册表。
- 新增P0/P1发现：runner同一天先后两次执行v3入场策略；生命周期使用第一次原始分数，而真实入场使用第二次最终风险/ML分数，E1信号失败可能不对应实际决策信号。设计要求兼容字段、最终评分和一次选择三段拆分。
- 新增可比性发现：SCAP输出路径、策略摘要、准入报告和environment manifest没有完整显式记录E阶段、损失边界、有效CLI覆盖、代码状态与原因schema；当前不同E阶段运行不能依赖目录或摘要自动认定为受控实验。
- 新增账本口径发现：账户NAV包含公司行动现金，但交易配对PF不接收公司行动账本；终端净利润与PF不是同一经济口径，必须新增总回报交易PnL并保留价格PnL诊断。
- 新增准入冲突：504日、最多5只、20日主期限理论约126笔闭合交易，而固定最低150笔隐含平均持有低于16.8日，可能强迫高换手；两年`positive_year_slice_share>=0.60`又离散等价于2/2年份全正。需以有效机会数、置信区间和滚动切片重做功效分析。
- 修改策略：本条只形成设计，不修改Python交易行为。实施固定为运行身份→控制/原因状态机→单一评分链→六层漏斗→订单/账本→报告/Web/准入→入场与利润优化→E0-E4经济锦标赛。
- 验证设计：E阶段采用5×2^8退出组合测试；每个规范原因完成生命周期→订单→pending→成交→交易配对→PnL→摘要→Web闭环；候选漏斗每日单调；公司行动使用黄金账本；所有经济比较必须通过运行身份可比性门禁。
- 当前允许动作：仅可从Phase A运行身份与基线冻结开始；Phase B状态机完成前禁止启动E1-E4收益排名。
- 修改文件：`SCAP_V1_FULL_REMEDIATION_PLAN_20260724.md`、`QUANT_SYSTEM_WBS.md`。
- 是否允许上线：否。

## 7. 后续实验顺序

1. 先完成 SCAP-V1 指标唯一语义、独立版本身份和三层仓位审计，不改变交易。
2. 确认真实券商最低佣金；未知时输出 0/1/5 元及成本压力场景。
3. 使用修复后的代码配对重跑 `v3` 与 `v3_ml`，唯一变量为 ML 融合，主动替换均关闭。
4. 若基础入场仍亏损，逐项消融现有质量硬过滤和分位门槛，不先提高仓位。
5. 入场期望为正后，按 E0→E1→E2→E3→E4 做单变量退出锦标赛。
6. 退出后成本净利润和 PF 达标，再研究一手组合优化、3/4/5只持仓和单仓软上限。
7. 赢家加仓、扩展股票池和主动替换均为后续独立实验；主动替换必须先满足 WBS-10.07。
8. 历史滚动、成本压力、PIT、完整性和前瞻纸面运行全部通过后，才讨论真实资金上线。

## 8. 新末梢/变更模板

```text
### CHANGE-YYYYMMDD-NN：标题

- 对应末梢：
- 用户目标：
- 现有实现检查：
- 数学/逻辑变化：
- 修改文件：
- 上游输入影响：
- 下游模块影响：
- 不变量：
- 验证命令与结果：
- 回测口径与结果：
- 是否允许上线：
```

### CHANGE-20260724-09：Phase A运行身份、结果隔离与五日产品验证

- 对应末梢：WBS-00.07、WBS-14.11、WBS-16.10。
- 用户目标：完整修改分阶段实施；每阶段执行产品验证和Bug测试；最终再运行20日全链路。
- 现有实现检查：原输出目录、环境清单、策略摘要及SCAP准入报告没有共同冻结`scap_exit_stage`、`scap_loss_stop`、目标指标、有效日期和代码状态，E0-E4结果存在误比较风险。
- 数学/逻辑变化：新增稳定运行身份哈希`H(effective_parameters, dates, costs, PIT, factor_source, code_fingerprint)`；任何退出阶段、止损线、日期、成本或关键代码变化都会生成不同身份。目录增加紧凑标签`e{stage}_l{loss_bp}`，完整值仍写入清单、摘要和准入报告。
- 首次产品Bug：可读的`exit_E0/loss_0p12`双层目录使深层审计CSV超过Windows传统`MAX_PATH`，时间隔离证据写入失败，且尚未进入交易。修复为单层`e0_l1200`后重跑；工具超时曾遗留一个重复回测进程，按精确PID终止重复实例，仅保留带stdout/stderr证据的实例。
- 修改文件：`runtime_identity.py`、`runner.py`、`runner_summary.py`、`scap_admission.py`、`preflight.py`、`main.py`、`verify_scap_runtime_identity.py`及本WBS。
- 上游输入影响：不改数据、因子、候选评分、交易成本和交易规则，只冻结它们的有效身份。
- 下游模块影响：`environment_manifest.json`新增`runtime_identity`与`effective_config_hash`；策略摘要和准入报告新增资本档位、目标指标、SCAP版本、退出阶段、止损线、运行身份哈希和代码指纹。
- 不变量：E0五日成交、持仓路径、NAV及信号/槽位计数必须与`run20260724_185544`一致。
- 验证命令与结果：固定解释器3.10.19；`py_compile`通过；`verify_scap_runtime_identity.py`与`verify_scap_weak_point_audit_remediation.py`全部通过。
- 回测口径与结果：`run20260724_213717`，2025-01-02至2025-01-08共5个交易日，E0、止损-12%、2万元、最多5只、v3、最新74因子柜、关闭影子组合；stderr=0；最终NAV 19,782.840990元，5笔买入、0笔卖出、期末5只；最后一日槽位前信号128、优化器选中0。与基线结果精确一致，证明Phase A仅改变身份与可审计性。
- 运行身份：`9a8994b48e64841e3dda0821ccd9238061b598bd361cbce248ee3da22610a444`；代码指纹`f69262f5280a1a19902ab6d850f25b4187aa27cef8d0a01b23c2e2f3321e6a38`。
- 是否允许上线：否；Phase A通过，但必须继续完成Phase B-H和20日全链路。

### CHANGE-20260724-10：Phase B控制鉴权、规范原因与整仓清算合同

- 对应末梢：WBS-09.09、WBS-10.10、WBS-10.11、WBS-10.12、WBS-16.10。
- 用户目标：修复所有模块的逻辑薄弱点，并在阶段结束后执行产品验证和Bug测试。
- 现有实现检查：旧链路先从所有原始触发器选择最高优先原因、再清除无权原因，导致E3损失信号可能被E4未授权利润信号遮蔽；`stale_time_exit`错误复用`signal_failure_exit`权限；`profit_hard_stop_exit`与`hard_stop_exit`别名跨生命周期/政策/执行不一致；损失退出不在执行层整仓原因集合；未知SCAP控制默认放行。
- 数学/逻辑变化：改为“每个触发器先按E阶段鉴权→仅在已授权集合中按优先级选唯一原因”；建立规范退出原因、优先级、控制映射及整仓清算集合；未知SCAP控制抛出`ValueError`；订单显式携带`liquidation_intent`并贯穿pending与成交账本。
- 修改文件：`exit_reason_contract.py`、`small_capital_aggressive.py`、`position_lifecycle.py`、`policy.py`、`pending_orders.py`、`execution_runtime.py`、`runner.py`、`verify_scap_exit_contract.py`及本WBS。
- 上游输入影响：不改退出触发公式和E0-E4阶段定义，只修复权限顺序及规范语义。
- 下游模块影响：政策原因统一为`profit_hard_stop_exit`；损失/信号/陈旧/利润等完整退出不再依赖易漂移的字符串集合或目标权重推断；pending和执行账本可直接审计清算意图。
- 不变量：E0所有退出仍为纸面观察，真实成交和NAV不得改变。
- 验证命令与结果：`py_compile`通过；新增测试覆盖5个阶段、6项控制及全部256种触发组合；`verify_scap_stage5_exit_policy.py`、`verify_execution_rules.py`、`verify_governance_v3_lifecycle_math.py`和`verify_scap_weak_point_audit_remediation.py`全部通过。
- 回测口径与结果：`run20260724_214441`，与Phase A同一5日E0口径；stderr=0，最终NAV 19,782.840990元、5买0卖、期末5只、最后一日信号128/优化器0，与既有基线精确一致。执行账本新增`liquidation_intent=False`的买单证据。
- 是否允许上线：否；控制/原因合同通过，仍需单一评分链、六层漏斗、pending历史/公司行动账本、报告/Web/准入和20日全链路。

### CHANGE-20260724-11：Phase C单一最终评分权威与一次优化

- 对应末梢：WBS-07.08、WBS-08.11、WBS-16.10。
- 用户目标：消除策略全链路中的“既要又要”和重复权威，每阶段完成产品验证与Bug测试。
- 现有实现检查：同一交易日先以柜原始分数运行一次V3选股，再做生命周期，之后才做ML/可靠性融合和风险惩罚并第二次选股；生命周期、退出和最终订单可能读取不同分数。风险惩罚虽声明覆盖所有候选，实际只作用于第一次已选候选，形成路径依赖。
- 数学/逻辑变化：最终链路固定为`柜角色分→可选ML/可靠性融合→所有候选统一一手风险惩罚→唯一risk_adjusted_primary_score→生命周期/状态→一次组合优化`。第一次兼容调用只附着最终分数且`selection_enabled=False`，不得覆盖入场决定；优化器仅在生命周期后执行一次。
- 修改文件：`mainline_v3.py`、`runner.py`、`position_lifecycle.py`、`policy.py`、`pending_orders.py`、`execution_runtime.py`、`verify_mainline_v3_single_score_chain.py`及本WBS。
- 上游输入影响：因子柜和原始角色分不变；风险惩罚从“旧选择后局部作用”改为“选择前全候选同口径作用”。
- 下游模块影响：生命周期、订单、pending、成交及候选审计共享`mainline_v3_score_authority=risk_adjusted_primary_score`和`single_final_score_v1`；新增`mainline_v3_selection_evaluated`证明兼容评分阶段未选股、最终阶段才选股。
- 不变量：一个交易日只有一个最终评分权威和一次组合优化；候选审计`entry_matrix_score==primary_score`。
- 验证命令与结果：`py_compile`通过；`verify_mainline_v3_single_score_chain.py`、`verify_governance_mainline_v3.py`、`verify_scap_stage4_portfolio_optimizer.py`和`verify_governance_v3_lifecycle_math.py`全部通过。
- 回测口径与结果：`run20260724_215028`，同一5日E0产品短链，stderr=0；候选审计1000行中`entry_matrix_score`与`primary_score`不一致数为0。最终NAV 19,840.200968元、5买0卖、期末5只，较旧路径增加57.36元；这是统一风险排序导致选中标的改变，不是盈利有效性证据。
- 行为变化解释：买入序列改为`sh600848、sh600754、sh603341、sz001289、sz300888`，属于修复旧“先选后罚”路径依赖的预期结果；不得与旧代码基线当作单变量收益实验。
- 是否允许上线：否；评分权威通过，但仍须六层漏斗、订单/账本、报告/Web/准入及最终20日全链路。

### CHANGE-20260724-12：Phase D六层候选漏斗与单调性产品断言

- 对应末梢：WBS-08.09、WBS-08.11、WBS-14.10、WBS-16.10。
- 用户目标：把信号、现金、槽位、选中和执行拆成细小末梢，验证修复是否引起新矛盾。
- 现有实现检查：旧`pre_slot`混入现金约束，`capital_pass_count`只统计前25条详情，却与全量候选级联比较，导致5日中4日漏斗非单调；满仓时“信号为零”和“槽位为零”仍可混淆。
- 数学/逻辑变化：新增严格子集链`raw positive signal → structural/market/position-cap feasible → cash feasible → remaining-slot feasible → optimizer selected → registered buy`；SCAP期望暴露改用原始正效用信号数，现金和槽位只解释可执行拖累，不反向删除信号。
- 修改文件：`mainline_v3.py`、`runner.py`、`candidate_funnel_audit.py`、`verify_scap_six_layer_funnel.py`及本WBS。
- 上游输入影响：不改最终评分和优化目标，只拆解资格层次。
- 下游模块影响：日级结果、候选详情、漏斗日报和漏斗摘要新增六层字段；产品运行逐日调用`assert_scap_funnel_monotonic()`，任何逆序直接失败。
- 不变量：每个交易日六层计数必须非递增；满5只时允许原始信号大于0，但槽位层必须为0。
- 验证命令与结果：`py_compile`通过；`verify_scap_six_layer_funnel.py`、`verify_scap_stage1_exposure.py`、`verify_scap_stage7_audit_trace.py`和`verify_scap_weak_point_audit_remediation.py`全部通过。
- 回测口径与结果：`run20260724_215845`，同一5日E0产品短链，stderr=0、最终NAV 19,840.200968元，与Phase C交易结果一致；五日六层无单调性失败。
- 五日证据：原始信号164/160/157/158/155；结构可行148/143/137/139/138；现金可行148/143/137/134/133；槽位可行148/143/137/0/0；优化器选中5/3/1/0/0。最后两日明确是“仍有155级信号、但满仓无槽位”，不再误报信号消失。
- 是否允许上线：否；六层漏斗通过，仍需pending原因历史、公司行动收益归属、报告/Web/准入及20日全链路。

### CHANGE-20260724-13：Phase E持久订单原因历史与公司行动总收益配对

- 对应末梢：WBS-09.09、WBS-12.07、WBS-16.10。
- 用户目标：修复订单、成交、交易配对和账户收益之间的薄弱链路，并逐阶段做产品验证。
- 现有实现检查：同一股票已有持久卖单时，只有新原因优先级严格更高才更新，导致同优先级的新事实被吞掉；账本只有单一`reason`。账户现金应用分红和送股，但交易配对只读取成交账本，交易PF/盈亏可能与账户总收益不一致。
- 数学/逻辑变化：pending新增`origin_reason/latest_reason/highest_priority_reason/reason_history/reason_schema_version`；同优先级新原因更新当前权威但保留完整历史。交易配对按日期在成交前应用已实际入账的公司行动；送股增加配对库存但不增加成本，现金分红按卖出股份比例分配，交易总收益=`卖出净收益-成本+分红现金`。
- 修改文件：`pending_orders.py`、`execution_runtime.py`、`runner.py`、`trade_pairing.py`、`verify_pending_order_reason_history.py`、`verify_trade_pairing_corporate_actions.py`及本WBS。
- 上游输入影响：只使用回测中已经应用并写入`governance_corporate_action_ledger`的事件，不额外引入未验证未来数据。
- 下游模块影响：pending和成交账本可追溯原因演化；闭合交易新增公司行动前PnL、分红现金、送股数量和总收益合同；开放持仓新增累计公司行动现金/股份，PF、盈亏比和胜率使用总收益口径。
- 不变量：无公司行动时新旧配对结果一致；公司行动不能重复应用；原因历史不得覆盖原始原因。
- 验证命令与结果：`py_compile`通过；pending合成测试覆盖同优先级与更高优先级升级；公司行动黄金测试覆盖100股10元买入、10股送股、50元分红、110股10元卖出，卖价PnL 100元、总收益150元、汇总150元；执行规则及实验跟踪回归通过。
- 回测口径与结果：`run20260724_220429`，同一5日E0产品短链；stderr=0、最终NAV 19,840.200968元，与Phase D一致；5条pending买单均保存五项原因字段；期内无公司行动与闭合交易，开放持仓公司行动累计为0，符合事实。
- 是否允许上线：否；订单与总收益合同通过，但仍需报告/Web/准入、盈利研究接口和最终20日全链路。

### CHANGE-20260724-14：Phase F准入功效、完整控制汇总与Web合同

- 对应末梢：WBS-13.11、WBS-14.11、WBS-15.08、WBS-16.10。
- 用户目标：报告、Web和准入不能再存在不同模块口径冲突，并完成阶段产品验证。
- 现有实现检查：固定150笔闭合交易与504日、5槽位、20日主期限不兼容；两年`positive_year_share>=0.60`离散等价于两年全正；控制汇总缺少损失、陈旧、投资逻辑失败；专业监控漏掉运行身份、六层漏斗、原因历史及6项已有基准字段。
- 数学/逻辑变化：SCAP准入升级为v2，闭合交易证据目标30笔且显式报告理论机会容量；稳定性改为126交易日窗口、63日步长，至少4个切片、正收益切片占比≥60%。5日等证据不足窗口保持拒绝，不用降低标准伪造通过。
- 修改文件：`scap_admission.py`、`candidate_funnel_audit.py`、`runner.py`、`live_monitor_web.py`、`live_monitor_dashboard.py`、`verify_scap_admission_opportunity_compatibility.py`、`verify_scap_web_contract.py`及本WBS。
- 上游输入影响：交易结果不变；准入使用同一日级NAV、总收益交易配对和成本压力结果。
- 下游模块影响：控制触发汇总覆盖利润回吐、买后失败、信号失败、投资逻辑失败、陈旧、损失和利润硬保护；Web展示运行身份、E阶段/止损、六层计数、pending原因历史和完整基准身份。
- 不变量：短窗口必须因证据不足拒绝；Web只展示事实，不改变策略；准入不能通过强迫高换手来凑样本。
- 验证命令与结果：准入机会容量/滚动切片测试、SCAP Web静态合同、专业监控布局、Web研究控制、V3初始化和端点链接测试全部通过。测试还发现并修复专业监控遗漏的6个既有基准字段。
- 回测口径与结果：`run20260724_221111`，同一5日E0产品链；stderr=0、策略报告23,957字节、最终NAV保持19,840.200968元。准入版本v2，机会容量1、滚动切片0，正确输出`research_gate_blocked`。
- 控制闭环：控制汇总现含8行；纸面买后失败1次、活动0、订单0、成交0，与E0阶段权限一致；其余控制0，未出现别名丢失。
- 是否允许上线：否；报告/Web/准入合同通过，仍需盈利研究接口、20日全链路及最终全回归。

### CHANGE-20260724-15：Phase G二十日成本后人民币利润审计

- 对应末梢：WBS-08.10、WBS-13.11、WBS-14.11、WBS-16.10。
- 用户目标：小资金可接受大回撤，胜率和盈亏比只需一项，唯一主目标是赚钱；必须客观分析适合的策略和修改方式。
- 客观约束：不能把决策日后的20日真实收益作为当日选股分数，否则是未来数据泄漏。因此本阶段只建立事后人民币利润审计；运行时激活保持`False`，未来必须用预注册滚动样本外预期利润模型。
- 数学/逻辑变化：每个候选一手20日成本后人民币利润=`one_lot_cash_required × (forward_return_20d - estimated_round_trip_cost_rate)`；分别统计优化器选中、未选中和全样本的数量、均值、中位数及正利润率。
- 修改文件：`scap_profit_objective.py`、`runner.py`、`verify_scap_profit_objective_audit.py`及本WBS。
- 产品Bug一：初始长文件名在深输出目录下可写但普通`Import-Csv`无法消费，改为短文件`scap_profit_audit.csv`和`scap_profit_summary.csv`。
- 产品Bug二：旧`_forward_return()`只读被有效结束日截断的决策特征，短窗口所有未来收益为空；改为只在事后审计使用、包含向后审计期的`audit_prices`，不进入交易决策。
- 上游输入影响：交易与评分不变；仅在保存阶段读取审计价格。
- 下游模块影响：每次产品运行生成可直接消费的人民币利润审计与摘要，并明确`audit_only_future_20d_not_available_at_decision_time`。
- 验证命令与结果：利润公式黄金测试与全特征管线集成测试通过；集成测试存在既有DataFrame碎片化性能警告，不影响本阶段数值正确性，后续单列性能重构。
- 回测口径与结果：最终产品验证`run20260724_222333`，同一5日E0决策窗口、向后20日审计价格；stderr=0、NAV仍为19,840.200968元。200条候选中195条有完整20日结果，优化器选中9条。
- 关键盈利证据：选中9条平均成本后利润47.91元、中位14.20元、正利润率55.56%；未选中186条平均102.74元、中位12.50元、正利润率61.29%。现有相对效用在这个极小窗口没有提升平均人民币利润，反而均值明显落后；这不是最终统计结论，但足以禁止直接宣称当前优化器已实现“利润最大化”。
- 策略含义：下一步应以滚动样本外`E[net_profit_yuan_20d]`排序，并用5日大亏概率作灾难约束；在校准完成前维持现有交易权威，不以5日审计过拟合。
- 是否允许上线：否；盈利审计接口通过，但运行时人民币利润模型尚未准入。

### CHANGE-20260724-16：Phase H E0-E4单变量退出实验合同

- 对应末梢：WBS-10.10、WBS-14.11、WBS-16.10。
- 用户目标：避免“既要又要”地同时开启多个控制，后续每次修改和实验都能检查是否影响其他模块。
- 逻辑变化：每次SCAP运行保存固定五行`scap_exit_stage_contract.csv`，逐阶段列出信号失败、买后失败、陈旧、损失、利润回吐和利润硬保护权限；同时冻结声誉、市场状态、冷却、主动替换、亏损加仓和赢家加仓均关闭。
- 比较合同：E0-E4实验只能改变`exit_stage`；数据、日期、代码指纹、成本、股票池、资本档位、因子柜和评分必须通过运行身份门禁，否则不得排名收益。
- 修改文件：`small_capital_aggressive.py`、`runner.py`、`verify_scap_exit_stage_contract.py`及本WBS。
- 验证命令与结果：E0-E4矩阵专项测试通过；并联合回归退出鉴权、单一评分、六层漏斗、pending历史、公司行动、准入和Web合同，全部通过。
- 回测口径与结果：`run20260724_222744`，同一5日E0产品链；stderr=0、NAV 19,840.200968元不变；实验矩阵5行且仅E0标记为当前阶段，E1/E2/E3/E4权限逐级增加符合注册表。
- 是否允许上线：否；Phase A-H代码与阶段产品验证完成，下一步执行最终20日全流程验收。

### CHANGE-20260724-17：20日全流程产品验收、短路径修复与最终回归

- 对应末梢：WBS-00.06、WBS-13.11、WBS-14.11、WBS-15.05、WBS-16.01、WBS-16.08、WBS-16.10。
- 用户目标：完成所有模块后，运行真实20日小窗口，从开始、决策、执行、记账、报告到保存做全流程产品验证和bug测试。
- 第一次20日运行：`run20260724_223111`完成20个交易日和全部保存，stderr=0；但深层身份目录使`governance_unified_research_gate_summary.csv`和`governance_portfolio_constraint_report.csv`的完整路径超过普通Windows工具可稳定消费的范围。虽然文件存在，普通`Import-Csv`无法打开，因此产品验收判定失败，不用“计算已完成”掩盖“用户打不开”。
- 产品修复：SCAP输出根缩短为`results/decision_council/scap/{alpha_bundle}/{exit_loss}/{logic}/run*`；完整股票池、策略、资本档案、控制模式、E阶段、损失边界、因子柜和代码指纹仍写入`environment_manifest.json`、策略汇总和准入报告，路径不再承担完整身份数据库职责。
- 最终20日验收目录：`results/decision_council/scap/cab_c6dae8d4d69c/e0_l1200/v3/run20260724_223951`；目录长度131，125个文件、109个CSV，普通PowerShell逐文件`Import-Csv`失败数0；两个原长路径失败报表的新路径长度分别176和174，均成功读取。
- 运行完整性：进程正常退出，stderr字节数0；20/20交易日完成，日期2025-01-02至2025-02-06；六层漏斗逐日单调断言0失败；`governance_runtime_integrity_audit.csv`的10项检查全部通过。
- 结果：初始资金20,000元，最终资金20,402.200968元，成本后净利润402.200968元，总收益2.011005%，最大回撤-3.883995%，平均实际仓位59.5432%；研究基准收益6.673677%，超额收益-5.127011%。5笔买入、0笔卖出、期末5只、交易成本10.799元、闭合交易0。
- 退出证据：当前E0只观察不执行；买后失败纸面触发15次，活动触发/订单/成交均为0。零闭合交易意味着闭合胜率、盈亏比和利润因子均不可定义，不能用日胜率42.11%替代交易胜率。
- 人民币利润审计：优化器选中9条完整样本，20日平均成本后利润47.91元、中位14.20元、正利润率55.56%；未选中760条平均173.99元、中位29.24元、正利润率68.68%。当前相对效用排序在本窗口未证明最大化人民币利润，下一阶段优先滚动样本外`E[net_profit_yuan_20d]`，但未预注册校准前保持`audit_only`，不得把未来20日收益泄漏进当日决策。
- 可比性检查：短路径修复前后20行日度结果按日期、NAV、现金、持仓数、实际仓位和成本逐格比较，差异0；利润摘要和完整性审计SHA256一致。执行账本文件哈希不同源于运行时订单UUID，经济核心结果不变。
- 最终测试：运行身份、退出授权、单一评分、六层漏斗、pending原因历史、公司行动总收益、利润审计、E0-E4矩阵、SCAP准入、Web合同、专业监控、端点、V3初始化和decision-council phase-one均通过；利润审计测试在`FutureWarning`升级为错误的模式下通过。
- 验证器薄弱点：`verify_mainline_outputs.py`的代码、数据、33策略选择检查通过，但仍固定查找4个旧版根目录汇总产物，当前不存在而退出1。该结果登记为旧路径验证器契约问题，不误报为本次SCAP运行失败，也不伪造兼容文件。
- 上游/下游影响：只改变SCAP产物根路径和审计布尔列的pandas显式类型转换；数据、PIT、因子、评分、优化、执行、费用、记账和E0行为不变；Web/报告消费者依靠运行目录和清单读取，不依赖被删减的路径语义。
- Web端口复核：主配置页与随运行监控页均通过`127.0.0.1:0`向Windows申请当次空闲端口，不存在需要随结果目录迁移的固定端口；每次启动会打印新的`/run`、`/results`或监控URL。2026-07-24复核时没有相关Python Web进程处于监听状态，因此此前端口不能继续使用。`_discover_result_runs()`递归发现新短目录，并成功返回`run20260724_223951`，证明结果页的数据发现已适配新路径。
- Web下一步选择冻结：为保持与20日E0基线的单变量可比性，下一次只勾选“治理主线单次运行”，账户选择`small_capital_branch/20000元/5只/allow_cash`，仅选择`hs300_csi500_a500_strict`，控制模式`aggressive_profit`，退出阶段仅改为`E1`，损失边界仍为`-0.12`，策略`mainline_v3_cabinet_native`，因子来源`selected_factor_cabinet`并固定`pruned_run20260714_184846_581132_20260715_230524`，窗口`2025-01`至`2025-02`且预设`short_20`；不同时勾选其他任务、股票池、影子组合或ML版本。
- 是否允许上线：否。工程全链验收通过，但20日证据太短、无闭合交易、落后研究基准、入场排序在利润审计中落后未选池，准入正确输出`research_gate_blocked`。

### WBS增量末梢（2026-07-25）

| WBS末梢 | 单一职责 | 上游 | 下游 | 验收 |
|---|---|---|---|---|
| WBS-14.12 | 对历史持仓逐日展开全部单因子原始分、加权分、信誉分和权重占比；只读审计，不取得决策权 | 持仓账本、alpha提案、因子柜元数据 | CSV、Excel、Web曲线 | 股票/日期覆盖率100%，因子长表行数=`持仓日行数×因子数` |
| WBS-15.09 | 提供按股票、因子角色和分值口径筛选的只读曲线页，并允许为单只股票打开独立窗口 | WBS-14.12 | 人工复核、截图与问题定位 | 健康端点、序列端点、交互选择、控制台无错误 |
| WBS-16.11 | 候选门禁流式汇总完整记录纸面/活动退出子原因，避免“明细有触发、汇总为0” | 候选门禁分片 | 控制触发汇总、研究诊断 | 流式测试覆盖loss/thesis等布尔字段且不全量拼接 |

### CHANGE-20260725-01：25号E1结果诊断、卖出链审计与逐因子曲线产品

- 对应末梢：WBS-14.12、WBS-15.09、WBS-16.11，并复核WBS-13.11、WBS-14.11、WBS-16.10。
- 分析对象：`results/decision_council/scap/cab_c6dae8d4d69c/e1_l1200/v3/run20260724_233436`。该任务于2026-07-24 23:34启动、2026-07-25 01:07完成；实际窗口是2025-01-02至2026-05-29、338个交易日，不是此前约定的20日小窗口，不能与20日E0结果当作单变量实验。
- 核心结果：20,000元降至17,977.17元，总收益-10.1142%，最大回撤-16.0630%，平均实际仓位54.6424%；基准收益47.7568%；22笔闭合交易，胜率45.45%，盈亏比0.7561，利润因子0.6301；买入后10日平均毛收益-1.634%，扣可变成本后-1.846%；研究准入继续阻断。
- 满槽/缺口证据：338日中308日持有5只，293日同时存在超过5%的仓位缺口；满5只时平均目标仓位88.97%、实际仓位56.20%、缺口32.99%。13,809条候选记录被`mainline_v3_no_remaining_slot`阻断，全部加仓状态为`scap_all_adds_disabled`，主动替换订单为0。当前矛盾不是手续费，而是“5槽位满仓口径、禁止加仓、禁止主动替换”与高目标仓位同时存在。
- 候选比较：在93个可审计的满槽日中，87日存在现金可行且综合分高于最弱持仓的候选，中位分差0.06498；这只证明替换路径被结构性封闭，不证明高分候选事后一定盈利，严禁把未来收益用于当日替换。
- 退出逻辑：E1只执行`signal_failure_exit`；价值/成长/现金流/盈利类论文宽限20日，其他类默认10日。宽限后满足“入场分与趋势分均低于0.45”、或“入场支持不低于0.45且当前支持低于0.35并衰减至少0.20”、或“下跌趋势分不低于0.75且延续分低于0.45”之一时卖出。E2的买后失败/陈旧退出、E3的-12%损失控制、E4的盈利回撤/硬止盈在E1仅纸面观察，不拥有下单权，因此`-0.12`在本次不是活动止损。
- 冲突诊断：22笔卖出全部是信号失效；亏损交易仍出现约-25%、-20.57%、-19.22%的大额亏损。冷却期关闭后出现8次再入场，包括卖出后下一交易日或极短时间买回，构成“信号失效卖出—立即重新满足入场”的迟滞冲突。手续费合计124.63元，仅约占终值亏损的6.16%，不能解释主要亏损。
- 报表bug与修复：候选门禁明细已有纸面loss/thesis/stale/profit触发，但流式汇总遗漏相应布尔字段，导致部分控制触发汇总错误显示0。已在`functions/decision_council/runner.py`补齐纸面与活动的thesis/stale/loss/hard/profit-hard字段，并扩展`verify_candidate_gate_streaming_summary.py`。修复只影响未来运行的诊断汇总，不回写历史运行，也不改变交易决策。
- 新产品：`tools/build_scap_holding_factor_dataset.py`生成14只历史持仓、1,641个持仓股票日、74个因子、121,434行逐因子长表，覆盖率100%；`tools/scap_factor_curve_web.py`提供按股票/分值口径/因子角色筛选和独立窗口；Excel保存摘要、约束、闭合交易、卖出诊断、因子映射及14只股票的全部因子矩阵和原生曲线图。
- 输出目录：`outputs/20260725_scap_e1_analysis/`；诊断报告为`SCAP_E1_RESULT_DIAGNOSIS_20260725.md`，工作簿为`SCAP_E1_20260725_持仓逐因子曲线.xlsx`。本次Web为只读临时服务，地址`http://127.0.0.1:59482/`，端口由当次启动确定，不写成生产固定端口。
- 方案冻结：第一阶段先做单变量纸面实验——仅给盈利持仓分批加仓、主动替换采用“候选20日人民币净利润保守下界－持仓保守下界－完整换手成本－安全边际”、每日最多一组配对替换；E1增加连续3日确认、卖出后10日冷却和恢复阈值迟滞。随后分别独立测试E2、E3、E4，禁止同时放开所有杠杆，以免无法归因。小资金且可接受回撤不等于应容忍负期望；首要目标是把成本后人民币期望转正，再讨论提高仓位。
- 验证证据：Python 3.10.19；修改文件语法编译通过；候选门禁流式汇总、SCAP Web合同、退出授权/原因/清算合同、六层漏斗合同全部`[PASS]`；Web健康端点返回14只股票和74个因子，浏览器实测筛选与独立窗口入口正常、控制台无警告/错误；工作簿公式错误扫描0，摘要和股票曲线页已渲染复核。
- 上游/下游影响：历史数据、PIT、因子计算、评分、优化、订单、费用、记账、E1授权和历史运行均未修改；新增工具只读取已保存产物。流式汇总字段补全会改变未来控制汇总的计数，但不会改变订单。若未来实施加仓、替换或迟滞，必须分别建立新末梢和预注册对照，复核现金、槽位、T+1、费用、涨跌停、退市/公司行动、报告可比性及Web解释。
- 是否允许上线：否。此次完成的是诊断、可视化和报表bug修复；现有E1策略成本后期望为负且显著落后基准，任何加仓、主动替换和退出规则变更均须通过独立样本外实验后才能取得交易权。

### CHANGE-20260725-02：逐因子产品正式接入与控制冲突统一

- 对应末梢：WBS-10.10至WBS-10.14、WBS-14.12、WBS-15.09、WBS-15.10、WBS-16.12。
- 用户目标：逐因子曲线和Excel不再作为一次性工具，正式接入初始化、monitor、结果页和保存链；统一互相打架的退出/买卖模块，修复重复买卖，并继续检查同类冲突。
- 产品链修改：`holding_factor_products.py`在SCAP保存末端从已落盘持仓、alpha提案和因子权重账本生成`holding_factor_curves/`；自动输出长表、持仓日表、卖出诊断、工作簿载荷、状态清单和`SCAP_持仓逐因子曲线.xlsx`。`factor_curve_web.py`成为正式只读产品模块，原`tools/`命令保留兼容包装。
- Web统一：治理monitor顶部新增逐因子曲线和Excel下载入口；保存前曲线页明确等待，保存后同一monitor端口直接提供数据。结果页也为所选run提供曲线与Excel入口。monitor独立脚本首次产品测试暴露`ModuleNotFoundError: functions`，已增加包模式/直接脚本模式双导入并复测通过。
- 退出统一：新增`single_exit_authority_v2`；退出模块只提交触发，统一仲裁器先检查每个原因的E阶段控制权，再按规范优先级输出唯一活动原因，同时保留触发、授权、否决和冲突数量。论文失效不再被诊断层完全吞并为普通信号失效。
- 重复买卖修复：E1信号失效家族必须连续3个决策日确认；小资金卖出后执行10个交易日冷却且不允许极端分数越权。策略订单层执行同股票卖出优先去重；pending层在新卖出意图出现时取消旧买单，已有活动卖单时新买单直接过期。
- 冲突根因：旧代码会在卖出成交时登记全局20日冷却，但SCAP注册表又把`cooldown`永久禁用，造成“写入冷却、入场不执行”。现将冷却权限从E1开始启用，天数和越权规则由小资金档案唯一给出。Web原先把主动替换显示为已勾选，而资金档案实际关闭，现统一显示为关闭及重新开启条件。
- 保持不变：主动替换、亏损摊平和盈利加仓继续关闭；E2/E3/E4在E1仍为纸面触发；目标仓位和可执行仓位继续分列。高分候选存在不等于替换有正收益，不以“控制统一”为理由越过样本外准入。
- 历史产品迁移：在25号历史run下新增`holding_factor_curves/`，14只股票、1,641个持仓股票日、74个因子、121,434行、覆盖率100%；历史账本、订单和收益未回写。
- 产品实测：独立monitor验证地址`http://127.0.0.1:54911/`；`/factors`、`/factor-workbook`均HTTP 200，meta返回14只股票和74因子，序列接口正确返回；stderr为0。浏览器同时打开monitor、总因子页和`sz301381`独立页，后者显示161个交易日和12条曲线，视觉复核通过。
- Excel验收：自动工作簿970,438字节；摘要、约束、交易、卖出诊断、因子映射、14个股票页和Checks全部渲染；公式错误扫描0；摘要及`sz301381`页视觉复核通过。
- 测试证据：固定解释器Python 3.10.19；全部修改文件`py_compile`通过；统一仲裁、退出E阶段、pending原因历史、替换配对、执行规则、生命周期语义、持仓上限、Web初始化/端点/研究控制、专业monitor、因子产品集成和decision-council phase-one均通过。产品测试首次失败的独立导入问题已记录并修复，不删除失败证据。
- 上游/下游影响：数据、PIT、因子生成、综合评分、费用、T+1和历史运行不变；未来E1卖出时点与再入场行为会改变，因此必须视为新代码状态，不能与25号旧E1直接宣称因果改善。新的保存阶段会增加Excel生成时间和产物体积，但不参与当日决策。
- 剩余验证：必须做同一窗口、同一资本/因子柜/费用/PIT的旧E1与新E1受控比较，重点检查净利润、最大回撤、卖出次数、10日内重复入场、平均持有期、费用、亏损尾部和相对基准。盈利加仓和主动替换必须另立单变量实验。
- 详细冲突报告：`SCAP_CONTROL_CONFLICT_AUDIT_20260725.md`。
- 是否允许上线：否。工程控制和产品链已统一，但交易效果尚未用受控新回测证明；当前只能作为研究候选。

### CHANGE-20260725-03：SCAP特殊版四模块放权、统一动作仲裁与20日产品验收

- 对应末梢：WBS-10.05至WBS-10.08、WBS-10.14至WBS-10.16、WBS-16.03、WBS-16.08、WBS-16.13。
- 用户授权：开启主动换股、亏损摊平、盈利加仓和E2/E3/E4交易权；同时要求同一份数据的不同模块决定必须统一融合，并能判断具体模块的正负影响。
- 权限变化：`small_capital_branch`改为`scap_exit_stage=E4`，因此E1至E4退出权累计生效；主动替换、亏损摊平和盈利加仓均开启。主动替换每日最多一组；亏损摊平沿用-3%/-6%两层触发，盈利加仓新增+5%/+10%两层触发；不放松单股上限、最大层数、因子信念、趋势、成交量、现金、一手和费用约束。
- 统一出口：新增`unified_position_action_v1`，优先级为活动退出→主动替换→亏损摊平→盈利加仓→新入场→普通再平衡→持有。候选状态、订单、pending和成交账本保存`unified_action_selected/proposals/vetoed/conflict_count/contract`；同股票最终仍只允许一个方向，卖出优先。
- 归因修复：原`action_counterfactual_reward.py`把已持仓股票的买单记成`hold`，导致加仓模块无法评价。现独立记为`add`，并保存负责模块、竞争提案和被否决提案；5/10/20日成本后市场中性反事实可按`loser_averaging`、`winner_pyramiding`等模块分组。
- 实测bug一：首轮20日运行`run20260725_212745`在第11日失败，错误为`slot_feasible=0, optimizer_selected=0, registered_buy=1`。根因是新开仓六层漏斗把加仓/换股买腿也计入首次入场分子。修复后首次入场、加仓买入、替换买腿分别写`scap_registered_buy_count`、`scap_registered_add_buy_count`、`scap_registered_replacement_buy_count`，单调断言只约束首次入场链。
- 实测bug二：修复漏斗后的`run20260725_213708`完成20日且总收益3.9407%，但6组替换中5个卖腿成交、0个买腿登记；该收益被孤儿卖腿污染，明确判为无效产品结果。根因是替换选择器允许`position_state=blocked`挑战者，策略层绕过普通买入状态门、零售执行层又正确阻止买腿。
- 孤儿卖腿修复：主动替换挑战者必须处于`building/strong_building/holding/watching/adding`之一；显式`blocked/cooldown/exiting/protecting_profit`不得发起配对。专项测试新增“blocked挑战者不能创建卖腿”。
- 最终20日产品目录：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260725_215005`。20/20交易日、2025-01-02至2025-02-06、保存阶段全部完成；74因子、10只历史持仓、90个持仓股票日、6,660行逐因子分数，覆盖率100%；Excel状态`ok`。
- 最终产品结果：初始20,000元，成本后总收益3.4532%，最大回撤-2.4374%，5笔闭合交易，胜率60%，盈亏比0.8363，利润因子1.2545，已实现盈亏84.31元，期末5只；研究基准收益6.6737%，策略仍落后3.6589个百分点，`research_gate_status=blocked`。年化与Sharpe因仅20日不作决策依据。
- 模块触发：计划2组主动替换，2个卖腿和2个买腿均进入pending并全部成交，pair完整；首次入场登记8笔；亏损摊平与盈利加仓开关均为True，但本窗口`add_allowed=0`，说明条件未满足而非功能关闭。E4当前合同显示cooldown、signal failure、stale/post-entry failure、loss containment、profit giveback和hard stop全部有交易权。
- 验证：Python 3.10.19；修改文件`py_compile`通过；统一动作、退出阶段、主动替换、替换策略集成、配对执行、pending历史、执行规则、六层漏斗、候选流式汇总、Web初始化/端点、反事实奖励专项均通过。真实20日运行在两个修复后正常退出并完成保存。
- 上下游检查：不改TDX数据、PIT、74因子公式、综合评分、T+1、费用与公司行动；改变未来E4退出、替换、加仓和持仓路径，因此不能与旧E1或修复前孤儿卖腿结果直接作因果比较。Web默认E4且明确特殊版已开启每日一组配对；monitor端口54911不停止。
- 客观结论：工程放权和冲突归因完成，但经济准入未通过。20日盈利、PF>1且胜率较高仍不足以抵消样本短、超额为负、仅5笔闭合交易；下一步必须做同运行身份的模块消融（全开、去替换、去亏损摊平、去盈利加仓、E1/E2/E3/E4）以及长窗/年份切片/成本压力，才能判断每个模块的边际正负贡献。
- 是否允许上线：否；仅作为用户授权的研究特殊版。

### CHANGE-20260725-04：Web下一步180日受控基线默认值

- 对应末梢：WBS-15.10、WBS-16.13。
- 用户目标：下一步需要在Web选择的参数全部设为默认，避免非专业用户漏选或混入不同实验口径。
- 默认任务：只勾选`governance_layer_validation`；刷新页面会清除其他历史恢复任务并重新勾选该单一任务，不默认启动多任务套件。
- 默认运行身份：`small_capital_branch`、20,000元、最多5只、现金缓冲2,000元、`allow_cash`、`all_a_share_research`唯一股票池、`aggressive_profit`、E4、损失边界-0.12、`mainline_v3_cabinet_native`、`selected_factor_cabinet`。
- 可比性冻结：默认因子柜优先固定为`pruned_run20260714_184846_581132_20260715_230524`，不再让更新较晚的PIT增强研究柜自动覆盖本轮受控基线。
- 窗口：开始2025-01、结束2026-05、`long_180`默认选中并自动写入180个交易日；完整模式、PIT research、Top100月度研究基准、影子组合关闭保持不变。
- Web说明：明确这是模块消融前的“全开共同基线”，不要同时选择其他任务、股票池、影子组合或ML版本。
- 上下游影响：只改变Web初始化与默认因子柜选择顺序，不改变CLI默认、数据、PIT、因子、评分、订单、执行、费用或已保存运行；已启动的旧Web进程不会热加载，需重新启动Web后才看到新默认。
- 验证：`main_launcher_web.py`语法编译、Web V3初始化、研究参数控制、端点与提交载荷测试必须通过。
- 是否允许自动开始运行：否；默认只减少选择错误，仍需用户点击运行。

### CHANGE-20260726-01：26号E4长窗结果、仓位分母、加仓可达性与未来函数只读审计

- 对应末梢：WBS-08.07、WBS-09.04至WBS-09.08、WBS-10.05至WBS-10.16、WBS-13.07、WBS-14.06、WBS-15.08、WBS-16.08、WBS-16.13。
- 用户目标：分析26号结果，重点验证第142日后长期半空仓、目标仓位是否错误使用初始资金、补仓过慢、通用大资金参数是否污染小资金版本，以及是否存在未来函数。
- 审计对象：`run20260725_230047`，保存完成于2026-07-26 01:35；2万元、最多5只、固定现金缓冲2,000元、全A研究池、74因子柜、SCAP E4、主动替换/亏损摊平/盈利加仓开关开启。
- 窗口事实更正（2026-07-26用户确认）：实际为2025-01-02至2026-05-29共338个交易日，用户本次主动选择“跑全部”，因此338日是预期行为，不是窗口参数失效。运行元数据仍应冻结`window_mode/requested_max_days/effective_end/trading_days`，避免今后混淆全窗口和固定日数实验。
- 结果：期末27,079.88元，总收益+35.3994%，最大回撤-10.2799%，平均实际仓位57.3449%；研究基准+47.7568%，相对落后19.5308个百分点；184笔闭合交易、胜率62.50%、盈亏比1.0716、PF 1.7860；研究门禁仍为blocked。
- 第142日证据：2025-08-04当日NAV 23,801.84元、目标95%、实际63.49%、现金8,690.84元、持有5只；槽位前合格候选148只，槽位后0只，可执行目标被压回63.49%。第142日后197日平均目标86.10%、实际58.85%；172日缺口超过10个百分点，158日持有5只，其中143日同时存在超过10个百分点缺口。
- 资金分母结论：治理持仓权重、一手权重、订单目标金额均使用当日`nominal_nav=现金+持仓市值`，不是初始2万元。真实冲突是95%目标未先扣固定2,000元缓冲，以及加仓预算仍硬编码通用20%单股上限、未使用小资金档位40%上限，再叠加25%渐进调整。
- 加仓可达性：全338日实际加仓0次；第142日后914条持仓状态全部`add_allowed=False`。225条已达到-3%亏损或+5%盈利价格触发的记录中，alpha质量≥0.68为0条、因子信念≥0.60仅1条、趋势稳定≥0.40仅41条；alpha质量实际最大0.5173。属于评分尺度与AND硬门槛不匹配，不是开关未开启。
- 替换原子性新Bug：执行账本有121个替换卖腿、117个替换买腿；4组只有卖腿成交，涉及卖出成交额17,757元。买腿存在于`executable_order_plan.csv`，但注册阶段按卖出前现金做整手可负担检查而未进入pending。现有完整性审计只检查孤儿买腿，不检查孤儿卖腿，形成假通过。
- 字段语义：`target_holding_count=2`实际来自`min_holdings=2`，不是目标持仓数；需改名并单列真实目标。追仓允许不等于存在可生成订单的加仓/新开仓候选。
- 未来函数结论：T+1、执行日收盘隔离、因子时间隔离、同期限替换价值和直接未来列不入决策的专项测试通过；因子柜上游截止2024-12-31，OOS从2025-01-01开始。PIT Level 1/2仍为`research_only/formal_pass=false`，证券主表、历史成分、公司行动、交易状态、财报、估值和事件表尚未正式合格，因此只能结论“未发现直接未来函数”，不能排除存活偏差和公告时点偏差。
- 验证证据：固定解释器Python 3.10.19；`verify_no_execution_day_close_leakage.py`、`verify_governance_temporal_isolation.py`、`verify_no_future_leakage.py`、`verify_feature_leakage_audit.py`、`verify_flow_ml_pit_contracts.py`、`verify_multi_horizon_value_contract.py`、`verify_scap_runtime_identity.py`、`verify_scap_unified_action_contract.py`、`verify_replacement_pair_execution_guard.py`均退出0。专项数据核对发现现有替换测试遗漏“买腿注册前现金不足、需依赖配对卖腿回款”的场景。
- 修改范围：只新增诊断报告`outputs/20260726_scap_e4_338d_diagnosis/SCAP_E4_RESULT_DIAGNOSIS_20260726.md`并登记本WBS；未修改交易代码、配置、历史账本或结果。
- 上下游影响：本次无运行时影响。后续修复必须按“替换原子注册/双向孤儿审计→目标与现金缓冲一致→新开仓/加仓/替换槽位分离→加仓评分尺度统一→5日/20日/匹配338日全窗口”顺序，每阶段产品验证；只有日期、代码、成本、PIT、资金档和因子柜完全一致的结果才可作单变量比较。

### CHANGE-20260726-02：26号全量Excel/CSV审计、文献核验与完整整改方案

- 对应末梢：WBS-03 数据/PIT与时间可得性；WBS-04 因子柜、相关性与校准；WBS-06 SCAP仓位/加仓/替换；WBS-07 执行成本与整手；WBS-08 决策漏斗与统一动作出口；WBS-10 报告、Web与Excel产品；WBS-12 受控实验与上线准入。
- 用户授权范围：只读通读`run20260725_230047`的全部输出和Excel，检索论文、交易所规则与书籍，形成完整修改方案；本条不修改交易逻辑、不覆盖历史账本、不启动新回测。
- 运行窗口：用户明确选择“跑全部”；2025-01-02至2026-05-29，338个交易日。纠正CHANGE-20260726-01把338日解释成180日参数失效的旧结论。
- 全量盘点：176个文件，其中150 CSV、11 PNG、10 JSON、2 GIF、1 MD、1 XLSX、1 NDJSON。Excel共102页，全部渲染成功，公式错误扫描为0；150个CSV无重复整行、无数值正负无穷。
- 仓位证据：平均目标仓位86.8107%、实际57.3449%、缺口29.4659个百分点；303/338日缺口超过10个百分点；271日持有5只，其中250日仍缺口超过10个百分点。第142日净资产23,801.84元，目标95%、实际63.49%、现金8,690.84元、槽位前候选148、槽位后0。
- 资金分母复核：权重和订单金额使用当日`nominal_nav`，不是最初20,000元。2,000元固定现金缓冲对应的平均可行仓位约91.57%，有195日策略目标高于缓冲可行上限；这只能解释部分结构差，不能解释平均29.47个百分点缺口。
- 加仓可达性复核：1,578条持仓状态中`add_allowed=True`为0；450条达到价格触发，alpha质量≥0.68为0、因子信念≥0.60仅2，实际最大alpha质量0.5186。确认是评分尺度与多重硬AND冲突。
- 替换完整性复核：121组替换、238条成交腿，存在4组孤儿卖腿；现有完整性审计只统计`orphan_buy_pairs=0`而误报通过。必须改为双向审计与原子注册。
- 成本与换手：368笔成交，累计名义金额1,057,248元，为初始资金52.86倍；实际成本1,132.12元，占初始资金5.66%。最低佣金5元、市场成本2倍压力下总成本3,193.03元、净利润4,740.97元、利润因子1.474，仍盈利但成本侵蚀显著。
- 模块边际证据：反事实奖励成熟样本中，新开仓平均+0.7831%、持有+0.5637%、主动替换-0.3439%、普通再平衡-0.6879%、退出-0.8299%。主动替换虽然实现绝对盈利，但相对继续持有的机会成本为负，修复工程正确性后仍需单模块消融。
- 因子/校准：74因子中55个被冗余标记，冗余率74.32%，最大秩相关1.00，最大簇22；10日ECE 0.1147超过0.08门槛。因子熵接近1只说明声誉关闭时等权，不代表独立。逐因子导出中60个模型声誉权重为0，原始预测曲线仍非零；Web必须区分原始分、实际决策权重、关闭和缺失。
- 未来信息边界：未发现直接执行日收盘泄漏，因子时间隔离通过；但PIT L1/L2均`research_only/formal_pass=false`，正式存活偏差、历史成员、公告日和修订日风险未排除；DSR/PBO/SPA均`insufficient`。
- 新发现的产品问题：Excel卖出诊断没有MAE；日期轴显示序列号；每股页有74因子数据但图表仅Top12且未明确；覆盖率公式写死计数；`active_signal_failure_rows`错误等于全部61条主动退出；`target_holding_count=2`其实是最低持仓数；13个非适用CSV无表头；空仓日`account_effective_n=1`；Excel算术相对收益-12.3575个百分点与摘要复合主动收益-19.5308%使用同一模糊语义。
- 方案决策：唯一主目标为期末成本后净利润；利润因子作健康门槛，胜率与盈亏比不同时作硬门槛。新开仓、盈利加仓、亏损摊平、持有、退出、成对替换统一进入一个成本后净利润下置信界仲裁器；5只槽位只限制新标的，不限制已有持仓合法加仓。
- 修改顺序：阶段0报告/审计真相；阶段1原子替换；阶段2仓位/槽位/现金三口径；阶段3两条独立加仓与滚动校准；阶段4因子聚类精简与概率校准；阶段5正式PIT与过拟合审计；阶段6固定全部条件做5日构造、20日全链、匹配338日全窗口。
- 文献依据：风险约束Kelly支持显式增长—回撤权衡；基数约束组合文献支持小持仓数与交易成本联合优化；Frazzini等支持成本后异常检验；Niculescu-Mizil/Caruana支持概率校准；Harvey等、White、Bailey等支持多重检验、Reality Check与PBO；Brown等支持存活偏差控制；沪深交易所规则支持100股整手与T+1约束。
- 新增证据：
  - `outputs/20260726_scap_e4_338d_diagnosis/all_output_file_audit.csv`
  - `outputs/20260726_scap_e4_338d_diagnosis/all_output_file_audit_summary.json`
  - `outputs/20260726_scap_e4_338d_diagnosis/domain_audit.json`
  - `outputs/20260726_scap_e4_338d_diagnosis/trade_pnl_by_entry_reason.csv`
  - `outputs/20260726_scap_e4_338d_diagnosis/action_reward_by_module.csv`
  - `outputs/20260726_scap_e4_338d_diagnosis/holding_factor_curve_stats.csv`
  - `outputs/20260726_scap_e4_338d_diagnosis/workbook_audit/`
  - `outputs/20260726_scap_e4_338d_diagnosis/SCAP_E4_FULL_OUTPUT_AUDIT_AND_REMEDIATION_PLAN_20260726.md`
- 上下游影响：本轮只新增审计证据、修改诊断文字和WBS，不影响策略、候选、订单、账本、Web运行或历史结果。后续任何实现必须在上述末梢登记，并检查数据→因子→动作提案→统一仲裁→整手组合→pending→执行→账本→报告/Web/Excel全链影响。

### CHANGE-20260726-03：SCAP-E4全细节施工规格与新末梢冻结

- 用户目标：在CHANGE-20260726-02方向方案基础上，给出包含所有细节、可直接施工的完整修改方案；本条仍不修改交易代码、不启动回测。
- 新增/冻结末梢：WBS-08.12、WBS-08.13、WBS-09.10、WBS-10.17、WBS-10.18、WBS-13.12、WBS-13.13、WBS-14.14、WBS-14.15、WBS-16.14；复用既有WBS-14.12逐因子只读产品末梢。
- 目标口径：唯一主目标为期末成本后净利润；压力利润因子为健康门槛；胜率只展示，盈亏比作二级诊断，二者不再参与高仓位布尔准入。
- 决策架构：因子、生命周期、退出、加仓和替换只生成`ActionProposal`；新增统一净利润金额引擎，除硬安全退出外按同期限、同成本的净效用下置信界仲裁；整手组合优化器在现金、5只、单股上限、T+1和交易规则内选择最终动作；pending/执行只消费唯一`ActionDecision`。
- 加仓合同：盈利加仓和亏损摊平分离；原九层硬AND改为滚动分位/概率校准后的持仓支持证据+正净效用+硬风险约束；满5只不阻止已有持仓合法加仓；每类加仓单独记录分母、层数、手数和阻断原因。
- 替换合同：完整买卖对原子注册，买腿可条件使用保守卖出净回款；任一腿注册前不可行则两腿均不注册；运行完整性双向检查孤儿买卖腿，另记录卖后买失败、到期和现金重算失败。
- 仓位合同：策略希望、现金缓冲、风险上限、整手可行、订单后预计和实际仓位分列；新开仓槽位、持仓加仓权和替换配对权分离；所有闲置现金按信号、整手、缓冲、槽位、加仓权、替换失败和风险原因加总守恒。
- 因子合同：按角色/经济家族/0.90秩相关聚类，完全相关只留代表，目标12—20个有效因子；原始分、校准分、实际权重、贡献金额及active/zero_weight/disabled/missing/not_applicable/pending_pit状态分离。
- 产品合同：空模块输出稳定schema；相对基准三口径分列；Excel补MAE、日期轴、动态公式和全因子分角色图；Web增加仓位四层、现金原因、动作冲突和替换pair状态。
- 验证合同：新增统一效用、加仓可达性、退出冲突、替换原子/双向完整性、条件现金、整数手最优、槽位权分离、仓位语义/现金守恒、空仓有效N、基准语义、因子状态、空schema、Excel/Web专项测试；每阶段依次做5日构造、20日全产品链和固定条件338日消融。
- 回滚合同：统一效用、原子替换、两类加仓、整数优化、因子裁剪、动态缓冲和报告V2均使用独立开关；回滚不覆盖历史结果，任一工程门槛失败自动保持研究状态。
- 详细规格：`outputs/20260726_scap_e4_338d_diagnosis/SCAP_E4_DETAILED_IMPLEMENTATION_SPEC_20260726.md`。
- 上下游影响：本轮只有设计文档和WBS变化，无运行时影响。正式实现时必须严格按WBS-16.14顺序，每完成一个末梢先验证再进入下一末梢，禁止一次性同时放开多项交易权。
- 是否允许上线：否。绝对收益为正但显著落后研究基准，PIT未正式合格，且存在4组孤儿卖腿、加仓0可达和窗口身份未冻结问题。

### CHANGE-20260726-04：施工规格反向缺口审计

- 用户目标：检查完整修改方案本身是否仍有遗漏；本条只审计和补充设计，不修改交易代码、不启动回测。
- 审计方法：将方案逐项映射到决策数学、组合交互、订单状态机、A股日期规则、账户终止状态、公司行动、数据质量、统计实验、schema兼容、运行恢复、Web监控和资源预算，并与当前`security_trading_rules.py`、`execution_rules.py`、`pending_orders.py`、`trade_pairing.py`及runner现状交叉检查。
- 新增末梢：WBS-09.11、WBS-09.12、WBS-10.19、WBS-10.20、WBS-12.08、WBS-12.09、WBS-13.14、WBS-13.15、WBS-14.16、WBS-15.11、WBS-16.15。
- 关键纠正一：统一效用必须统一为相对“不动作”基准的增量终值；否则持有、买入、加仓、卖出和替换仍可能口径不同。整数优化还必须处理相关性、同股互斥与非线性成本，不能简单相加单动作效用。
- 关键纠正二：2025-01-02至2026-05-29的338日窗口已经用于诊断、设计和未来B0—B11选择，只能是开发/审计窗口；它可用于受控回归，但不能再提供最终样本外证据。
- 关键纠正三：当前pending已能累计部分成交数量，但缺少完整cancelled/rejected语义、跨重启幂等成交键和一致性检查点；当前板块价格限制规则也未覆盖上市初期无涨跌幅、退市整理及规则日期变更。
- 关键纠正四：期末未平仓不得为美化胜率/PF强平；公司行动须同步影响pending和替换pair；数据缺失不得静默填零；旧Web/Excel读取器必须显式处理schema迁移。
- 产品与运维补充：monitor需要心跳、当前run绑定、检查点、陈旧识别和失败原文；20日验收增加故障注入、重启重放、部分成交、跨公司行动和资源预算。
- 详细缺口报告：`outputs/20260726_scap_e4_338d_diagnosis/SCAP_E4_SPEC_GAP_AUDIT_20260726.md`；详细施工规格已追加第23—31节。
- 上下游影响：本轮仅更新设计文档与WBS，无运行时影响。后续实施时上述新增末梢必须在对应阶段先通过专项测试，再允许进入338日开发窗口比较。
- 是否允许上线：否；缺口补齐只让方案更完整，不构成代码已修复或盈利有效证据。

### CHANGE-20260726-05：SCAP-V2全模块分阶段施工与20日验收

- 用户授权：直接实现全部冻结模块；每个模块完成后执行专项bug测试和受影响回归；最终运行20日真实全链并把下一步Web选择设为默认。
- 基线保护：工作区包含大量既有未提交修改，全部视为用户现有成果；不回退、不覆盖、不批量删除。固定解释器确认Python 3.10.19。
- 阶段A基线：逐因子Web/Excel、SCAP Web、运行身份、Web初始化、交易规则、交易配对和替换现有15组专项测试全部退出0。
- WBS-10.19实现：新增`action_utility.py`，软动作统一相对`hold_cash`计算同期限人民币增量终值；缺少`comparable_expected_alpha/comparable_alpha_lcb`时标记`insufficient`并fail closed；完整买卖费用、风险金额、基准终值和动作终值分列。
- WBS-10.20实现：SCAP候选效用从无量纲“分位数减惩罚”改为`expected_net_profit_lcb`人民币金额；有界整手优化增加相关性/行业交互惩罚及审计字段，仍保持现金缓冲和正效用约束。
- WBS-10.18实现：盈利加仓和亏损摊平删除旧九层高度相关硬AND，改为独立价格层触发、横截面支持分位、正人民币效用LCB、少数退出/冷却/尾部风险/单股上限硬约束；缺失支持或收益校准不得按0.5放行。
- 本阶段验证：`verify_scap_action_utility_v2.py`、`verify_scap_stage3_candidate_utility.py`、`verify_scap_stage4_portfolio_optimizer.py`、`verify_governance_mainline_v3.py`、`verify_scap_add_reachability_v2.py`、`verify_scap_unified_action_contract.py`、`verify_decision_arbitration_contract.py`、`verify_scap_exit_contract.py`全部退出0；语法编译通过。
- 当前状态：施工中，尚未运行20日全链，尚不允许上线；下一阶段处理订单幂等、原子替换、日期有效规则和检查点恢复。
- WBS-09.11/WBS-09.12实现：`pending_orders.py`和`execution_runtime.py`新增订单注册幂等键、成交幂等键、部分成交累计、取消原因、schema版本、替换双腿原子注册、卖腿净回款条件现金及公司送股对pending数量的同步调整；任一替换腿预检查失败时两腿均不提交。
- WBS-10.19/WBS-10.20下游统一：统一动作效用、加仓效用、候选效用和整手组合优化均使用人民币成本后增量终值；相关性与同行业同时入选使用组合交互惩罚，不再把不同量纲的评分直接相加。
- WBS-10.18实现：盈利加仓和亏损摊平拆成独立价格触发、独立动作类型和独立归因；持仓数量已满只限制新标的，不剥夺已有持仓的合法加仓权；退出授权、冷却、尾部风险和单股上限仍为硬约束。
- WBS-13.14实现：`security_trading_rules.py`按交易日期、板块、ST状态和上市交易日数解释涨跌幅；有明确上市证据时覆盖科创/创业板前5个交易日无价格笼子，证据不足时标记降级而不伪造精确规则。
- WBS-09.12/WBS-13.15实现：期末未平仓不再为美化胜率/PF而虚拟强平，改为披露估计退出成本、总收益与删失状态；公司行动处理保持事件幂等并同步pending目标/剩余数量。
- WBS-15.11实现：新增原子`run_checkpoint.json`心跳/检查点和`COMPLETE.json`完成标记；monitor披露当前run、PID存活、陈旧状态、当前日期、阶段、最后错误和保存完成状态。当前恢复语义为“可审计断点”，不是未经验证的自动续跑。
- WBS-12.08/WBS-12.09实现：诊断过的338日窗口永久标记`development_audit`，不得再作为最终样本外证据；实验卫生加入重叠期限有效样本数、block bootstrap及实验族Holm校正。胜率/盈亏比只作诊断，主目标固定为成本后期末净利润，PF作健康门槛。
- WBS-14.16实现：所有空CSV/账本保持稳定表头；20日空持仓边界下逐因子Web显示“本窗口无持仓、无曲线”，不再访问空股票列表；Excel空交易/空卖出计数改为全列非空计数减表头，空分母使用显式0，消除`#DIV/0!`。
- 20日验收运行时Web默认值：唯一勾选“层验证线”；20日；2025-01至2026-05；完整模式；2万元；最多5只；2000元缓冲；允许现金；`aggressive_profit`；E4；`mainline_v3_cabinet_native`；`selected_factor_cabinet`固定`pruned_run20260714_184846_581132_20260715_230524`；只选`all_a_share_research`；关闭影子组合。
- 分阶段验证：统一效用、两类加仓、统一仲裁、退出授权、替换条件现金、pending/成交幂等、日期有效规则、期末未平仓、公司行动、时间隔离、无未来泄漏、实验卫生、checkpoint/schema、逐因子产品和Web默认初始化共22个有效验证脚本退出0；另有一次测试清单引用了不存在的旧文件名`verify_corporate_action_pipeline.py`，已改用现有`verify_corporate_actions.py`、`verify_corporate_action_ledger.py`和`verify_trade_pairing_corporate_actions.py`，三者均通过。
- 20日真实全链：修复后运行目录`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260726_130522`；2025-01-02至2025-02-06，共20/20交易日；`COMPLETE.json=complete`；130个CSV全部可读且有表头；日期唯一；NAV最大对账误差0；仓位上限、运行完整性、无无穷数、开发窗口身份及Excel自动保存均通过；进程stderr为0字节。
- 20日结果边界：本窗口20日全部空仓、0笔成交、期末净值20,000元。它证明初始化→候选→动作审计→空订单/空成交schema→账户守恒→保存→Web/Excel的工程链可靠，但没有用真实成交覆盖pending→T+1→收费→卖出；这些交易分支由专项构造测试覆盖，下一阶段180日开发窗口必须再次以真实成交复核。
- Excel产品验收：`SCAP_持仓逐因子曲线.xlsx`共6个工作表，逐表渲染成功；首次验收发现2个`#DIV/0!`、空交易数误算1、空卖出行误算2，修复并重新生成后公式错误0，Checks四项均为OK，宽表表头已加高换行。
- 浏览器产品验收：新服务端口49427；真实浏览器确认所有上述默认项；结果页自动选中`run20260726_130522`且生成逐因子/Excel入口；空持仓页面显示明确状态且控制台无页面错误；再用有持仓历史结果验证96只股票、74因子、默认Top12曲线、5类角色筛选和`weighted_factor_score`切换均能刷新。
- 性能收口：空宽账本由逐列插入改为一次`reindex`，修复pandas高度碎片化告警；修复后20日运行stderr为0。
- 上下游影响复核：数据/PIT和因子柜输入未改；动作、组合、pending、执行、账户、配对、准入、报告、monitor、Web和Excel均已按末梢验证。新逻辑仍保持无杠杆、现金非负、100股整手、T+1、日期可得性和研究/正式身份隔离。
- 当前结论：SCAP-V2工程链验收通过，但不允许实盘上线，也不能据20日空仓结果判断盈利有效。下一步为使用Web默认项先保留本20日烟雾基线，再仅把窗口切换到180日做开发验证；若180日仍大量空仓，应按`raw_signal→structural_feasible→cash_feasible→slot_feasible→optimizer_selected`漏斗定位，不应直接强制满仓。
- 验收完成后的下一步默认值：为防止用户再次误跑已经通过的20日烟雾窗口，Web已把窗口预设和只读`max_days`切换为180日；其余任务、账户、资金缓冲、股票池、控制模式、E4、策略版本、因子柜、月份、完整模式和影子组合状态全部保持20日验收口径不变。该默认只授权开发回测，不改变`development_audit`身份。

### CHANGE-20260726-06：180日运行“卡住”故障诊断

- 用户授权范围：只读诊断截图所示 Spyder/Python 未响应；本条不修改交易逻辑、运行参数、Web代码，不停止或重启任何残留进程。
- 对应末梢：WBS-01.01、WBS-01.04、WBS-15.11、WBS-16.15。
- 运行身份：交互任务`governance_layer_validation`，`all_a_share_research`，2025-01-01至2026-05-31，`max_days=180`，完整模式，74个alpha模型。
- 进度证据：临时状态`monitor_state_60788.json`最后更新于2026-07-26 14:10:38，停在`factor_source_resolved`、12%；Web健康接口仍响应，但报告`is_stale=true`、`owner_pid_alive=false`。结果目录未生成本次run目录或checkpoint，故障发生在正式逐日runner开始之前，不是180日计算缓慢。
- 进程证据：真正执行任务的父进程PID 60788已不存在；启动页PID 33788和monitor PID 44424仍存活并监听端口。现有父子结构由`main.py:launch_interactive_main_menu`只把启动页作为子进程，而`run_interactive_selection`在Spyder/IPython父进程内同步执行回测；父进程退出后两个展示进程不会自动代表回测继续。
- 系统事件证据：Windows Application Hang事件1002和WER事件1001于14:11:56记录`python.exe`停止交互并被关闭；此前同一`stock_ai`环境的`QtWebEngineProcess.exe`在`Qt6Core.dll`内连续发生`0xc0000409`崩溃。未发现资源耗尽事件2004；诊断时物理内存仍有约4.26 GiB可用，因此没有证据支持系统OOM是主因。
- 根因分层：直接中断点是Spyder/IPython宿主Python进程退出；高可信上游诱因是同一环境QtWebEngine持续崩溃造成IDE/内核不稳定；架构放大器是长回测与IDE宿主同进程、Web/monitor又与owner生命周期解耦，最终形成“网页还在且显示running，实际任务已死”的假卡住。
- 上下游影响：本次没有新结果可分析，旧20日完整结果不受影响；残留Web数据只可作为失败诊断，不得登记为180日实验结果。后续修复应隔离独立worker、让worker拥有heartbeat/checkpoint、owner死亡时Web转为failed/stale，并避免由Spyder会话承载长任务；修复后需按启动→因子解析→首日checkpoint→逐日心跳→保存→完成标记→owner异常故障注入全链验证。

### CHANGE-20260726-07：Windows进度探测自终止与Spyder宿主隔离修复

- 用户授权：修复运行后自动卡住；保持历史结果、旧进程和交易逻辑不变，并完成分层bug测试与短窗口产品验证。
- 对应末梢：WBS-01.01、WBS-01.04、WBS-15.11、WBS-16.15。
- 根因纠正：CHANGE-20260726-06识别出的Spyder宿主退出和Qt不稳定成立，但产品复现进一步定位到更直接的代码缺陷：`functions/runtime_progress.py:_pid_alive`在Windows调用`os.kill(pid, 0)`。该调用不是POSIX式无害探测，而可能通过`TerminateProcess`结束目标；当进度文件首次写入后，下一次`read_progress(owner_pid=自身PID)`会无异常、退出码0地终止worker，恰好停在`factor_source_resolved`附近。原`verify_runtime_progress_owner_isolation.py`也被同样终止并以0退出，导致假通过。
- PID修复：Windows改用`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`与`GetExitCodeProcess`只读检查，`STILL_ACTIVE=259`才视为存活；当前PID直接返回存活；POSIX继续使用`os.kill(pid, 0)`。专项测试新增真实sleep子进程，断言探测后目标仍运行，再显式结束单个测试进程。
- 宿主隔离：`main_launcher_web.py --spawn-worker`在提交后以独立`main.py --interactive-selection-file`进程执行任务，stdout/stderr写入独立日志；Spyder宿主只接收worker PID和日志路径后返回，不再同步承载长回测。启动页改为绑定worker PID，拒绝重复提交，worker无完成标记退出时显示`FAILED`及退出码/日志；worker模式完成后保留结果页，不自动关闭服务。
- 生命周期修复：`main.py`检测`_worker_delegated`后转移启动页所有权，finally不再误杀启动页；worker读取独立选择文件后只删除该单一临时文件。Web健康接口新增`launcher_pid`、`worker_pid`、`worker_exit_code`和`worker_mode`，进度页优先显示`display_status`并明确陈旧心跳/owner死亡。
- 专项验证：`verify_interactive_worker_isolation.py`确认主`main.py`宿主提交后退出、worker PID独立、启动页继续响应、worker无完成标记退出显示FAILED且给出stderr；`verify_runtime_progress_owner_isolation.py`现能真正打印PASS并证明PID探测不终止目标。语法编译通过。
- 兼容回归：`verify_web_research_runtime_controls.py`、`verify_web_endpoint_links.py`、`verify_web_v3_initialization.py`、`verify_runtime_checkpoint_and_schema_v2.py`、`verify_layer_validation_progress_reporting.py`、`verify_scap_runtime_identity.py`、`verify_scap_web_contract.py`全部退出0。
- 5日真实产品链：固定2万元、最多5只、2000元缓冲、允许现金、E4、`mainline_v3_cabinet_native`、受控74因子柜、`all_a_share_research`，2025-01窗口，5日。运行目录`results/governance/all_a_share_research/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_profit/v3/run20260726_170307`；5/5日完成，130个CSV，`COMPLETE.json=complete`，`run_checkpoint.json=100%/complete`，最后日期2025-01-08，stderr为0，进度最终为`interactive_task_suite complete 100%`。
- 结果边界：该5日链仍为工程验证且全部空仓，不提供盈利证据；它证明原死亡点之后的特征加载、29.3万行候选缓存、逐日循环、保存和完成标记均可抵达。旧180日失败运行不得与此结果作收益比较。
- 上下游影响：未修改数据、因子、动作、订单、交易、费用、账户或报告公式；只改变启动/健康探测/进度展示。下一次180日默认参数保持不变，worker进程和Web生命周期已解耦；若任务真正异常，页面现在应显示FAILED或STALE，而不是永久伪装RUNNING。

### CHANGE-20260726-08：main.py补丁标记语法故障修复

- 故障：用户于17:28后再次从Spyder运行时，`main.py`第57行报`SyntaxError`；磁盘内容存在孤立`+`以及带前导`+`的`PIPELINE_CACHE_JSON`导入行。
- 修复：只删除两处补丁标记，恢复合法的`PIPELINE_CACHE_JSON`导入；未改任何运行、策略、数据、交易或Web逻辑。
- 范围检查：扫描`main.py`、`main_launcher_web.py`和`functions/runtime_progress.py`，未发现其他同类孤立补丁标记。
- 验证：固定`stock_ai` Python 3.10.19执行三文件`py_compile`退出0；`main.py --help`成功完成导入、配置与CLI解析，不启动回测。
- 上下游影响：仅恢复入口可解释性；CHANGE-20260726-07的worker隔离、PID只读探测和5日验证证据保持有效。

### CHANGE-20260726-09：Kernel重启中断、worker回退覆盖与SCAP零买入修复

- 用户现场：Spyder暂停/终止Kernel无响应后强制重启；软件运行一段时间但没有模拟买入。
- 中断证据：运行`run20260726_173424`在2025-01-20第13/180日被强制Kernel重启终止；最后成功日期2025-01-17，checkpoint仍为`running`、12/180、6.67%，没有`COMPLETE.json`，不得作为实验结果。owner PID 70048已不存在。
- Kernel原因：Spyder保存了旧编辑缓冲区，覆盖了CHANGE-20260726-07在`main.py`中的`--spawn-worker`与`--interactive-selection-file`入口；因此17:34回测再次在Kernel内同步执行，强制重启会连同回测一起结束。已重新恢复worker启动、所有权转移、独立选择文件与宿主返回分支；`verify_interactive_worker_isolation.py`再次通过。
- 残留进程：强制重启后旧Kernel PID 67900及其conda包装PID 62784仍存活；核对新Kernel为PID 53176、包装PID 56956后，只结束两个明确旧PID。当前Kernel未触碰。
- 零买入确定性bug：SCAP候选效用依赖`comparable_expected_alpha/comparable_alpha_lcb`，但`runner.py`原先在两次`apply_mainline_v3_entry_policy`完成后才调用`attach_multi_horizon_value_contract`。选股时所有候选均为`insufficient`，`run20260726_173424`前12日2400行候选效用全部≤0、raw signal为0；这是执行顺序错误，不是市场没有股票。
- 顺序修复：V3在风险调整后、第一次只读策略评估前建立同期限收益合同；非V3仍在原下游位置建立。修复后LCB字段可被效用引擎读取，但5日`run20260726_174641`仍因全部LCB成本后为负而0成交，证明工程顺序修复有效、同时揭示风险偏好仍与“小资金、接受大回撤、期望净利润优先”冲突。
- 特殊版目标修复：统一动作效用升级为`unified_action_utility_v3`，显式分离`expected_return_point`、`expected_return_lcb`、`decision_expected_return`和`decision_return_basis`。仅`small_capital_branch`新开仓使用`point`作为收益奖励，仍扣完整往返成本和人民币风险惩罚；LCB继续保存为风险诊断。其他账户及加仓/替换默认保持LCB，不全局放松。
- 审计补强：候选门禁新增可比期限、点估计、LCB、实际决策收益、决策basis、成本、风险惩罚和最终效用字段，后续可直接解释“为何买/不买”，不再只显示模糊`rank_below_cutoff`。
- 专项验证：多期限收益、候选效用、主线V3、整手组合优化、统一动作、worker隔离及语法测试全部退出0；新增测试证明point basis可以在LCB为负时按期望成本后净利润决策，同时LCB仍独立留存。
- 5日真实交易链：`run20260726_175330`，2万元、5只、2000元缓冲、允许现金、E4、受控74因子柜、全A研究池；5/5日完成，130个CSV、`COMPLETE.json=complete`、stderr为0。候选效用正值72行，raw signal 68行，策略选中13行；T+1执行账本4笔，第4日持有2只、第5日持有4只，期末NAV 19,949元。该结果证明自动模拟买入链路恢复，不证明5日盈利。
- 上下游影响：数据、因子值、市场权限、整手、现金、T+1、费用、账户和保存规则未放松；改变的是V3收益合同建立顺序，以及小资金特殊版新开仓的风险偏好口径。180日属于开发窗口，必须重新从头运行，不能从被Kernel中断的审计checkpoint自动续跑。

### CHANGE-20260726-10：5日剩余问题审计——整手决策口径统一与授权仓位闭环

- 用户目标：对最新代码执行真实5日小窗口，检查是否仍有剩余问题；发现问题后按末梢修复、专项测试并完成从初始化到保存的产品验收。
- 对应末梢：WBS-08.08、WBS-08.13、WBS-09.02、WBS-14运行完整性、WBS-16.01、WBS-16.08、WBS-16.16。
- 旧结果证据：`results/governance/all_a_share_research/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_profit/v3/run20260726_182303`中，2025-01-02有4个`scap_optimizer_selected`但0个注册买单；2025-01-07策略授权上限50%，订单层把连续小权重升级成两笔整手后，2025-01-08实际仓位67.33%。原10项完整性自检全部通过，说明缺少授权仓位不变量。
- 根因链：SCAP优化器以一手现金/效用选择；`PortfolioConstructionCommittee`随后以连续逆波动/协方差权重重算；`policy`的漂移阈值和累计换手桶可能吞掉小权重；`execution_runtime`又把残余V3新开仓强制恢复成一手。即“选股是一手、定仓是连续、执行再变一手”，三个模块使用了不同数学单位。
- 代码修复：`policy.py`新增授权仓位内的整手子集组合搜索；当前持仓先占用仓位，剩余空间内最大化正效用组合；通过者直接以`mainline_v3_one_lot_weight`进入目标组合；离散新开仓不再被连续部分调整或连续换手桶二次缩放。现金缓冲、最多5只、40%单股上限、T+1、费用和无杠杆合同保持不变。
- 自检修复：`runtime_integrity_audit.py`新增`execution_exposure_authorization`，用今日已结算实际仓位对比上一决策日可执行授权上限。基础隔夜价格偏差容忍2个百分点；若持仓均为不可再拆整手，可容忍不超过最小持仓整手且最多10个百分点的粒度偏差，超过仍判失败。
- 回归测试：固定解释器Python 3.10.19；三个修改文件`py_compile`通过；`verify_scap_action_utility_v2.py`新增整手效用最优组合、授权上限和旧越权识别测试并全部通过；`verify_execution_rules.py`、`verify_governance_mainline_v3.py`和`verify_decision_council_phase_one.py`全部通过，`git diff --check`无格式错误。用新审计重算时，旧`run20260726_182303`仍被判失败：最大越权17.33个百分点，高于最小整手7.79个百分点。
- 真实受控5日链：命令行显式固定2025-01-01至2025-01-08、5交易日、2万元、最多5只、2000元缓冲、允许现金、`aggressive_profit`、E4、`mainline_v3_cabinet_native`、受控74因子柜、`all_a_share_research`、关闭影子/monitor。结果目录为`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260726_184415`。
- 产品验收结果：5/5日完成，`COMPLETE.json=complete`、checkpoint 100%、最后日期2025-01-08、stderr 0；131个CSV全部可读且无数值无穷；4笔买入全部由2025-01-02信号在2025-01-03按T+1成交，每笔100股；订单ID唯一、同日同股同方向无重复、pending注册键无重复、现金非负、NAV对账误差0、最多4只持仓。
- 修复效果：首日漏斗由“选中4/注册0”变为“选中4/注册4”，首日候选不再被漂移阈值吞掉；之后弱市授权50%时没有新增买单，实际仓位52.77%至53.22%来自既有四个整手的市值漂移。其最大3.22个百分点偏差低于当日最小整手约9.48个百分点，授权仓位自检按不可避免粒度通过；旧版67.33%仍失败。
- 运行入口差异：第一次CLI未显式传日期时使用了2021默认日期，与Web交互默认2025日期不一致；发现后只停止本次错误日期审计PID并以显式日期重跑。以后所有受控比较必须显式传开始/结束日期；CLI特殊版结果位于`results/decision_council/scap`，Web交互层验证结果位于`results/governance/.../ctrl_aggressive_profit`，两者路径不同但必须依赖运行身份而非目录名判断可比性。
- 剩余边界：该5日窗口仍只有买入、没有真实卖出/替换/公司行动，不能证明退出链和长期盈利；终值19,806元只说明短窗净值，不构成收益有效性证据；研究准入仍因完整公司行动账本、正式税务账本、可投资基准、独立复核和正式复现包等缺口而阻塞。
- 文件变更：`functions/decision_council/policy.py`、`functions/decision_council/runtime_integrity_audit.py`、`verify_scap_action_utility_v2.py`、`QUANT_SYSTEM_WBS.md`。

### CHANGE-20260726-11：26日晚180日退化、评分量纲污染与保存失败审计

- 用户目标：分析26日晚输出为何突然退化，逐项核对上次修改、参数、持仓、成交、退出、因子和动作标签；本条为只读诊断，不修改交易逻辑、不覆盖历史结果、不启动新回测。
- 对应末梢：WBS-04因子与校准、WBS-08.08整手组合、WBS-08决策漏斗、WBS-09执行、WBS-10报告/Web、WBS-14运行完整性、WBS-16.08/16.16受控验收。
- 审计对象：`run20260726_191810`完成2025-01-02至2025-09-25共180日逐日计算，但worker在保存`layer_validation_audit`附近死亡；checkpoint停在`saving_outputs`且无`COMPLETE.json`。其账户/订单/分月候选残片可用于诊断，但不得登记为正式完成实验。
- 可比性：与`run20260725_230047`相同前180日相比，初始2万元、最多5只、2000元缓冲、股票池、E4、损失边界、费用、策略版本和74因子柜一致；代码指纹从`c16d9a...`变为`191c3a...`，新指纹与26日18:44五日工程链一致，故不存在代码回退。
- 结果：旧代码前180日期末24,758.90元、收益+23.794%、最大回撤-10.094%；新代码期末17,934.43元、收益-10.328%、最大回撤-18.203%。新代码平均实际仓位69.862%，比旧代码高14.105个百分点，但平均持股数从4.744降至4.289，属于更少股票、更高集中暴露。
- 主根因：`mainline_v3.py`在SCAP模式把人民币`scap_candidate_utility`同时覆盖到`entry_matrix_score/final_entry_score/primary_score`。新运行入选`entry_matrix_score`均值160.34、最高372.20，旧运行为约0至1；原“评分字段相等”测试遗漏单位和范围，导致假通过。`retail_min_entry_matrix_score=0.62`也因此失去原评分门槛语义。
- 交互根因：CHANGE-05把候选目标改成人民币净利润，CHANGE-09把小资金新开仓奖励改为点估计，CHANGE-10让整手选择、授权和执行真正闭环。三者组合为“未经有效校准的收益金额替代综合评分→放宽准入→高价整手完整执行”，不是某个前端参数恢复旧值。
- 量化证据：新运行76笔闭合交易毛利润-1,367元、胜率50%，旧运行同期100笔毛利润+4,763元、胜率69%；新效用与一手金额相关系数+0.849、与实际收益率-0.281，预期收益与实际收益率-0.255，LCB与实际收益率-0.316。最高两档预期收益组合均亏损，说明本窗口的收益校准和排序方向失效。
- 持仓/退出：新入选一手金额均值3,651.82元、一手权重均值18.50%、最大35.34%，旧值分别2,844.74元、14.05%、23.00%；20笔`post_entry_failure_exit`合计-5,124元，4笔`loss_containment_exit`合计-4,168元。9月收益-11.85%，9月22至23日仍约88%仓位，退出发生在损失之后。期末仅`sz301234`和`sz001336`，其中前者浮亏约450元。
- 标签冲突：入选118个日-标的中102个为`size_style`；订单层78行冲突计数主要来自替换双腿，并非78次真实决策矛盾。`high_exposure_research_gate_pass=false`时授权目标仍可达85%至95%，替换仍可执行；期末持股2只却显示`target_holding_count=2/shortfall=0`，继续暴露字段语义错误；少持仓时协方差状态为`insufficient_covariance_symbols`而未形成统一风险总闸。
- 保存故障：逐日计算约1小时32分完成，保存阶段只留下15个顶层产物和候选分区，stderr无traceback。后续必须在保存子阶段记录原子检查点、峰值内存和顶层异常，Web在无完成标记且owner死亡时显示`FAILED during saving`。
- 修改范围：新增诊断报告`reports/SCAP_20260726_EVENING_REGRESSION_ANALYSIS.md`并登记本WBS；未修改策略、配置、数据、账本、Web或历史运行。
- 上下游处置顺序：先隔离无量纲评分与人民币效用并增加单位合同；再做滚动样本外校准准入和高价整手尺度修正；统一风险/替换授权及目标持仓字段；最后按纯函数→5日→20日→同身份180日单变量A/B验证。当前运行和当前代码均不得作为实盘候选。

### CHANGE-20260726-12：SCAP-V2 全链补充审计、概率模型与接口级整改方案

- 用户目标：继续检查未发现的薄弱点，形成不会通过模块旁路引入新矛盾的小资金特化完整方案；方案必须覆盖数学、金融、概率模型、接口、验证顺序，并审查 WBS 本身是否合适。本条只修改设计报告和 WBS，不修改交易逻辑、不运行新回测。
- 对应末梢：新增/修订 WBS-00.08、05.09/05.10、06.10/06.11、08.08/08.14/08.15、09.13、10.15/10.17/10.20/10.21、11.04/11.07/11.08、14.17/14.18、15.12、16.17/16.18；原 2.2 和 2.4 的状态陈述同步纠正。
- 新 P0 发现一：`entry_calibration._fallback_frame` 在 `sample_count=0` 时仍生成概率和期望边际，`small_capital_aggressive` 又仅以非空值认定 calibrated，导致启发式先验获得交易权；标签从决策日候选收盘而不是下一事实可成交开盘起算，和执行合同不一致。
- 新 P0 发现二：滚动校准的 `expected_edge` 已扣 `cost_buffer`，动作效用和替换链又扣一次逐腿费用；同一交易存在成本重复扣除风险。以后标签保存 gross/cost/net 三列，动作优化只消费一种明确口径。
- 新 P0 发现三：`decision_arbitration` 当前仍以 `exit > replacement > loser_add > winner_add > new_entry > rebalance > hold` 固定优先级选动作，而且主要在订单形成后归因；它不是 WBS 原宣称的统一净效用决策器。
- 新 P0 发现四：当前存在 `mainline_v3.select_scap_one_lot_portfolio`、`policy._select_scap_discrete_entries` 和连续组合分配器多个权威入口；替换又在组合分配后直接把持仓目标置零、挑战者置为一手，绕过组合相关性、论点集中度和统一暴露授权。
- 新 P0 发现五：高仓位门禁主要控制补仓，无法统一约束新入场、加仓和替换；生命周期加仓预算仍引用通用 20% 单股上限而非小资金档位 40% 上限，说明同一风险合同被多模块私有重算。
- 新 P0 发现六：整手优化器虽支持相关矩阵，但主调用未传入，候选也缺稳定行业/论点键；目标函数还把人民币效用与 `0.05 ×` 无量纲现金碎片直接相减。保存端则在内存中同时构造多张大型审计表后统一写盘，使一个附属审计失败能够失去整次完成标记。
- 新 P1 发现：重叠 10 日标签和同日横截面被当独立样本，Wilson 区间有效样本虚高；缺少预测反向/漂移自动撤权；按绝对人民币效用取 Top15 偏向高价整手；60 日原始协方差可能奇异；替换条件现金可能重复扣当前保留；102/118 入选日-标的集中于 `size_style` 而无论点族上限；目标持仓数字段仍混用“希望/可行/已选”语义。
- 概率合同：收盘决策的 H 日净回报从下一事实可成交开盘起算；按决策日期聚类估计有效样本，胜率使用 Beta-Binomial 后验，收益使用经验贝叶斯收缩和日期块 bootstrap；稳健边际为 `posterior_mean - kappa × clustered_se`，`kappa` 只能作为预登记风险偏好做 0.5/1/1.96 对照，不能在同窗口择优。
- 金融合同：每个动作相对正确的“不动作”基准生成同执行起点、同期限的增量财富情景；费用逐腿只扣一次；硬安全退出先满足，其他动作由单一整数优化器联合选择。目标按字典序先最大化稳健成本后净利润，再控制压力损失、集中和换手，最后才减少无效现金碎片，避免“既要又要”权重混战。
- 小资金特化：保留 2 万元、一手、最多 5 只、40% 单股上限、2000 元基线缓冲、允许现金和较高回撤容忍；利用小资金容量优势做精确整手联合搜索，但不把高价一手自动当成更强 alpha。高回撤偏好只降低稳健惩罚系数，不关闭模型撤权、T+1、现金、库存、PIT、压力损失和论点集中硬约束。
- 接口合同：新增 `ScoreContract`、`ForecastDistribution`、`ActionProposal`、`ExposureAuthorization`、唯一 `ActionPlan` 和 `CashReservationLedger`。评分/概率/收益率/人民币增量财富不可复用字段；提案无下单权；执行层只接受带运行身份、决策日期、计划 ID、幂等键和现金保留证明的 ActionPlan。
- 防回归迁移顺序：先冻结 26 日同口径黄金回放，再双写单位合同；之后修校准和标签；再影子生成提案；然后切换唯一整数优化器；再切换现金/执行账本和统一风险授权；最后流式原子保存/Web。每阶段都要求旧路径与新路径差异账、性质测试、专项回归、5 日构造链和 20 日产品链，禁止一次性替换全链。
- WBS 结论：WBS-00 至 WBS-16 的父级分层和上游/下游方向适合继续使用；问题不在 WBS 形式，而在部分“设计冻结候选”被写成已实现事实、末梢缺少单位/权限/唯一出口合同。本次已用状态化措辞纠正，并增加唯一动作出口、现金保留、产物 DAG 和性质测试末梢。
- 完整方案：`reports/SCAP_V2_FULL_REMEDIATION_SPEC_20260726.md`。当前建议不是继续跑长窗，而是先完成 Phase 0 黄金回放与 Phase 1 单位合同；在评分量纲污染和先验伪校准未修复前，任何新长窗收益都不可解释。

### CHANGE-20260726-13：SCAP-V2 全模块实施与20日产品验收（进行中）

- 用户授权：按 WBS-16.18 直接实施全部模块；每模块、每阶段完成 bug 测试；代码完成后运行20日小资金真实窗口，从初始化到保存、Web/Excel全链验收。
- 施工边界：工作树进入本阶段前已有大量用户/历史修改和未跟踪研究文件；本阶段只修改 SCAP-V2 对应文件，不重置、不覆盖无关变更、不删除任何文件。
- Phase 0 环境：固定解释器 `C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe` 为 Python 3.10.19。
- Phase 0 修改前基线：`verify_mainline_v3_single_score_chain.py`、`verify_multi_horizon_value_contract.py`、`verify_scap_action_utility_v2.py`、`verify_scap_unified_action_contract.py`、`verify_pending_order_idempotency_v2.py`、`verify_runtime_checkpoint_and_schema_v2.py` 均退出0；`verify_scap_fullchain_run_v2.py`因缺少必需的 `--run-dir` 参数退出2，属于调用方式错误而非代码回归，留待最终20日run生成后以实际目录执行。
- Phase 1 单位合同：新增 `scap_v2_contracts.py`，实现 `ScoreContract`、`ForecastDistribution`、`ActionProposal`、`ExposureAuthorization`、`ActionPlan` 和评分范围运行时校验；`mainline_v3.py`恢复0—1排名分数权威，人民币效用仅写入独立 `scap_decision_utility_amount`，不再覆盖 `entry_matrix_score/final_entry_score/primary_score`。
- Phase 1 验证：相关文件 `py_compile` 退出0；新增 `verify_scap_v2_property_contracts.py`证明人民币金额不能进入评分、prior-only不能获得交易权、SCAP效用大于1时评分仍保持0—1；`verify_governance_mainline_v3.py`和`verify_mainline_v3_single_score_chain.py`回归均退出0。
- Phase 2 校准/成本：`entry_calibration.py`改为在决策后的下一观测开盘记录入场价，再从该事实入场点计算成熟收益；校准输出显式 `effective_sample_size`、`prior_only/calibrated`、`forecast_authority_weight`、`gross_only`和价格基准。预测 edge 不再扣固定成本缓冲，fallback亏损幅度也不再混入成本；费用只由具体整手动作效用扣一次。
- Phase 2 交易权：`small_capital_aggressive.py`只允许显式 `calibrated` 且 authority>0 的预测取得收益交易权；`action_utility.py`对 prior-only、insufficient、drifted 等非校准状态均将正效用封顶为0。旧测试补入显式校准状态，避免测试继续奖励隐式伪校准。
- Phase 2 验证：相关文件 `py_compile` 退出0；`verify_scap_v2_property_contracts.py`新增下一开盘标签与零样本禁权测试；`verify_scap_action_utility_v2.py`、`verify_multi_horizon_value_contract.py`、`verify_no_execution_day_close_leakage.py`和`verify_governance_temporal_isolation.py`均退出0。
- Phase 3 唯一动作计划：新增 `integer_action_optimizer.py`，以稳健人民币净利润→压力损失/成本→剩余现金的字典序做最多5只的有界穷举，约束同股方向、替换双腿原子性、总暴露、压力预算和主论点集中；`mainline_v3.py`撤销第一次整手组合求解，改为评分/效用/资金效率/论点族 Pareto 并集的最多15个候选缩减。
- Phase 3 最终权威：`policy.py`的离散入口改为调用唯一整数优化器；连续分配完成后按优化器选中的一手权重回写，不再二次自行选子集。所有新入场、两类加仓、主动替换和硬退出最终统一形成 `ActionProposal`，由一个 `ActionPlan`筛选后才保留订单；订单新增plan/proposal ID和合同版本。`DecisionContext/engine/runner`补入NAV、现金缓冲、单股上限和压力预算接口。
- Phase 3 捕获并修复的bug：32日集成测试在校准历史开始成熟时发现 `effective_sample_size` 来源选择提前读取尚未建立列导致 `KeyError`；已改为先计算 exact/alpha 可用掩码再一次性填充各统计字段。
- Phase 3 验证：新增性质测试验证候选顺序置换不改变计划、论点族与暴露约束有效；相关文件 `py_compile` 退出0；`verify_scap_v2_property_contracts.py`、`verify_scap_action_utility_v2.py`、`verify_scap_unified_action_contract.py`、`verify_decision_arbitration_contract.py`、`verify_decision_council_phase_one.py`（32日并完成保存）、`verify_governance_mainline_v3.py`和`verify_active_replacement_policy_integration.py`均退出0。
- Phase 4 现金/执行：新增 `cash_reservation_ledger.py`，以reservation ID逐单幂等保留/释放/排除自身并支持替换条件卖出净回款；`execution_runtime.py`不再维护匿名 `reserved_cash` 累加值，替换现金检查明确排除本买腿自身保留，订单/pending/成交贯穿 ActionPlan、proposal和reservation ID。
- Phase 4 执行权限：`retail_execution.py`对已由 ActionPlan 选中的订单只复核价格、状态、现金缓冲、整手、单股和暴露等事实硬约束，不再二次读取软评分否决；`pending_orders.py`稳定schema增加 ActionPlan 和现金保留字段。
- Phase 4 验证：相关文件 `py_compile` 退出0；性质测试证明重复reserve不重复占款且替换买腿条件现金只排除自身一次；`verify_pending_order_idempotency_v2.py`、`verify_replacement_pair_execution_guard.py`、`verify_active_replacement_policy_integration.py`、`verify_execution_rules.py`和`verify_v3_retail_audit_score_gate.py`均退出0。
- Phase 5 原子保存：`outputs.py`的CSV和文本改为同目录临时文件完整写入后 `os.replace` 原子替换；新增 `artifact_manifest.py`，逐阶段记录 `core_complete/audit_complete/web_complete`、当前stage、owner、错误和逐产物状态。`runner.py`在核心账本写完即保留core完成证据，附属审计逐件登记；保存异常会写 `save_failed` checkpoint和原始异常，不再停留在永久`saving_outputs`。
- Phase 5 Web：`main_launcher_web.py`结果发现和详情API读取artifact manifest，展示保存状态/阶段；只有manifest但尚未生成交易对的失败/部分run也能出现在结果列表并披露core/audit/web完成度和错误，不再由空白页面代表运行中。
- Phase 5 验证：相关文件 `py_compile` 退出0；`verify_runtime_checkpoint_and_schema_v2.py`新增故障注入，证明审计失败后core完成证据保留且无临时文件残留；`verify_governance_research_reports.py`、`verify_web_endpoint_links.py`、`verify_web_research_runtime_controls.py`和`verify_scap_web_contract.py`均退出0。
- Phase 6 风险/遗漏收口：SCAP加仓预算读取小资金40%单股上限；60日协方差使用70%样本+30%对角收缩并传入唯一整数优化器；正相关交互惩罚以人民币稳健利润比例计入；旧诊断优化器移除人民币与无量纲碎片直接相减，现金碎片只作次级tie-break且相同效用优先少花钱。高仓位研究门禁失败时，新入场、两类加仓和替换共享60%授权上限。
- Phase 6 模型撤权：校准历史达到最低有效样本后计算样本外Spearman rank IC和校准斜率；任一方向不正即标记`drifted`并把forecast authority降为0，性质测试用完全反向预测验证熔断。
- Phase 6 回归中发现并修复：两个旧SCAP测试仍断言换股/加仓关闭或默认缺状态即校准，已更新为当前E4显式授权和显式校准合同；`register_orders`测试桩无capital_profile导致现金账本初始化失败，改为兼容空profile；候选漏斗摘要对缺少新SCAP列的旧/非SCAP输入直接索引报`KeyError`，改为稳定零列兼容。
- Phase 6 验证范围：SCAP阶段0—7、评分/概率/动作性质、两类加仓、退出、准入、执行规则、板块/日期/费用、pending幂等和原因历史、原子替换、期末持仓、公司行动、估值日期、部分安全减仓、PIT/时间隔离/无执行日收盘泄漏、实验身份、checkpoint、因子Web/Excel、六层漏斗、研究门禁、worker隔离和两次32日保存集成链均退出0。

### CHANGE-20260726-14：Web端发起20日小窗口全流程复验（已完成）

- 用户授权：从Web端口开始发起20日小窗口实验，持续到结果保存完成。
- 对应末梢：WBS-01.01/WBS-01.04 Web启动与worker隔离，WBS-14.16稳定空产品，WBS-15.11进度与故障披露，WBS-16.18端到端产品验收。
- 固定边界：沿用SCAP-V2小资金口径（2万元、最多5只、2000元现金缓冲、允许现金、`aggressive_profit`、E4、固定74因子柜、`all_a_share_research`、关闭影子组合）；只把Web窗口明确设为20日。本次是工程复验，不据短窗收益判断策略盈利。
- 启动前检查：固定解释器 `C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe` 返回 Python 3.10.19；不覆盖或删除历史run；现有59482端口是历史逐因子产品页，不作为任务启动页。
- 验收条件：必须由Web表单提交并产生独立worker；逐日checkpoint达到20/20；`COMPLETE.json`、artifact manifest、核心CSV、Excel/因子产品和Web结果详情均可读取；任何保存失败或只有部分产物的run不得登记为完成。
- 2026-07-27启动停滞诊断：63837端口启动后约52分钟仍显示idle；健康接口为`worker_pid=null`、进度`0%/no task has reported progress yet`，启动器CPU仅累计约17秒。根因不是回测缓慢，而是上一轮操作在Web表单提交前被中断，只启动了服务、未创建worker；此前未把界面展示给用户也属于操作交付缺陷。
- 补提交证据：真实浏览器把“验证窗口预设”从180日切换为20日，页面确认`max_days=20`后点击“运行所选任务”；63837随后创建独立worker PID 68356并进入逐日处理，页面已显式展示给用户。用户后续要求不把该新run作为当前阻塞步骤，故不停止worker，让其自行完成。
- 历史保存故障复核：`run20260726_223741`确实在20/20后因高频逐产物刷新`artifact_manifest.json`触发Windows `os.replace` WinError 5，checkpoint=`failed/save_failed`、`core_complete=true`、`audit_complete=false`、无完成标记；系统未假报成功。
- 修复落地复核：`runner.py`已把manifest从逐CSV刷新降低为保存阶段级更新；`artifact_manifest.py`对原子替换最多重试8次并线性退避，观测附件持续被占用时不再向上抛异常反杀已保存核心经济账本，后续checkpoint/阶段更新会再次尝试写入。`verify_runtime_checkpoint_and_schema_v2.py`再次退出0，覆盖快速原子更新、稳定空schema和manifest核心完成保持。
- 修复后全链证据：`run20260726_224726`为独立20日重跑，2025-01-02至2025-02-06，checkpoint与`COMPLETE.json`均为complete，manifest=`core_complete/audit_complete/web_complete=true`；130个CSV全部可读、有表头、无0字节、无`.tmp`残留，NAV对账误差0，因子Excel产品状态ok。`verify_scap_fullchain_run_v2.py --expected-days 20`全部退出0。
- 结果边界：该20日重跑0笔成交、0持仓、期末现金20,000元；原因是有效决策日期样本门槛30日高于20日窗口，不是下单链卡死。它证明初始化、空动作账本、账户守恒、保存、manifest及Excel/Web产品链，不构成盈利或真实成交链证据。
- 沟通故障结论：用户看到“20/20后没有动静”一部分来自第一次真实保存失败，另一部分来自修复后成功结果未及时回传；后者是任务交付/状态沟通中断，不是`run20260726_224726`继续卡住。

### CHANGE-20260727-01：前台命令窗口、Ctrl+C中断与92日低仓位/补仓回归审计

- 用户现场：27号180日任务在90多个交易日暂停；后台worker没有可见命令窗口，无法确认错误或用键盘中断；结果相较26日上午明显更少买入，补仓近似消失，怀疑购买因子与状态机链路再次脱节。
- 运行身份与终止事实：`run20260727_001335`，固定2万元、最多5只、2000元缓冲、`aggressive_profit`、E4、`mainline_v3_cabinet_native`、固定74因子柜、全A研究池；checkpoint停在92/180、最后完成日2025-05-23、owner PID 24740已不存在、无完成标记。该run仅用于中途诊断，不登记为正式收益结果。
- 量化事实：现场93个图表点中55日零仓位，平均实际仓位10.94%、最高39.27%；最后NAV 18,641.91元、现金12,723.91元、3只持仓、实际仓位31.7457%。92日流式候选中49日无原始正效用信号、49日无Pareto选中；14,957行显示`mainline_v3_rank_below_cutoff`，645行confirmed。
- 根因一：校准器从可交易窗口起点冷启动，30个有效样本叠加10日标签成熟导致前43个交易日完全不买；相同决策日可能因回测起点不同而改变交易权，必须补PIT warm-up或独立冷启动身份，不能只缩短样本门槛。
- 根因二：新开仓读取小资金`scap_candidate_reward_basis=point`，但`position_lifecycle.py`的补仓效用未传该口径而使用默认`lcb`；同一aggressive身份风险偏好分裂。
- 根因三：当前不是一次联合动作优化。`policy._select_scap_discrete_entries`先做一次整数选股，连续分配器再形成目标权重，`_apply_unique_action_plan`对订单做第二次整数过滤；补仓只有在连续分配先产生正权重差时才成为提案。此前Phase 3“唯一优化器已落地”的记录超前于真实代码。
- 过严链：两类补仓同时硬AND触发幅度、持有支持分位、趋势/尾部风险、LCB正净效用、生命周期状态和连续分配正权重差，违反WBS-10.18；2025-05-23三个持仓分别被未到亏损间距、支持不足和退出状态阻止。
- 仓位语义：无正效用信号时策略期望仓位被设为当前实际仓位，使31.7457%实际仓位显示为目标已达、缺口0，违反WBS-08.07；必须分列战略风险预算、信号期望、整手可执行和实际仓位。
- 可观测性修改：`main_launcher_web.py`在Windows默认以`CREATE_NEW_CONSOLE`启动独立worker，stdout/stderr保持无缓冲显示，窗口内Ctrl+C直接到worker；环境变量`TDX_WEB_VISIBLE_WORKER_CONSOLE=0`仅供自动化切回后台日志模式。健康和进度API披露`visible_interruptible/background_logged`。
- 中断修改：`runner.py`捕获`KeyboardInterrupt`并写`status=interrupted/stage=keyboard_interrupt`、最后完成日和原始原因；`main.py`把全局进度写为interrupted并以退出码130结束；live monitor不再把中断显示成“回测完成”。不支持从该审计checkpoint恢复交易状态，重新运行仍须新run身份。
- 影响链：本次代码修改只影响WBS-01/15/16的进程窗口、退出状态和监控语义，不改变数据、评分、交易权、仓位、补仓、订单、费用、账户或报告公式。策略根因只形成审计与后续整改顺序，未与可观测性补丁混成收益实验。
- 详细报告：`reports/SCAP_20260727_MODULE_FLOW_AND_REGRESSION_AUDIT.md`。
- 验证证据：`py_compile main.py main_launcher_web.py functions/decision_council/runner.py verify_runtime_checkpoint_and_schema_v2.py verify_interactive_worker_isolation.py`退出0；`verify_runtime_checkpoint_and_schema_v2.py`退出0并新增interrupted checkpoint非stale断言；`verify_web_research_runtime_controls.py`退出0；可见console默认/后台覆盖两个纯函数断言均通过；`verify_interactive_worker_isolation.py`退出0，证明独立worker、Spyder宿主退出、launcher存活及后台诊断路径未回归。未在本轮启动新的策略回测。
- 后续门禁：策略端下一步必须先做校准warm-up起点不变性、补仓ActionProposal可达性和单日整数优化调用恰为一次的专项测试，再做匹配日期A/B，禁止直接重跑180日混合版本。

### CHANGE-20260727-02：SCAP-V3激进小资金精简链、模块消融与防回归方案

- 用户目标：形成一套面向2万元账户、追求成本后期末净利润的激进小资金完整方案；明确模块保留、降权、撤权、消融顺序和以后避免跨模块回归的方法。
- 对应末梢：WBS-06.12、WBS-08.16、WBS-10.22、WBS-16.20；承接CHANGE-20260727-01暴露的校准冷启动、风险偏好分裂、两次优化、补仓不可达和仓位语义循环问题。
- 方案身份：新增隔离研究身份`small_capital_aggressive_profit_v3_lean`与`control_mode=aggressive_lean`；不覆盖26日或27日既有身份，不把中断run或不同代码状态结果当作受控对照。
- 唯一权威链：PIT数据/可投事实→ScoreContract→带warm-up的ForecastDistribution→账户与持仓快照→所有动作ActionProposal→一次ExposureAuthorization→一次IntegerActionOptimizer→一个ActionPlan→现金保留账本→只复核事实硬约束的执行层→成交/持仓/NAV/诊断账本。
- 模块撤权：`_select_scap_discrete_entries`、SCAP连续分配器、`entry_confirmed/add_allowed/force_deploy`、执行后的软否决和按动作私有point/LCB口径均不得再独立决定订单；旧函数保留为`legacy_shadow_only`用于对账，不物理删除。
- 激进初始参数：本金20,000元、最多5只/软目标4只、现金缓冲1,000元、单股硬上限40%/30%起软惩罚、正常/弱势/高风险战略暴露预算90%/65%/35%、统一10日动作效用、`kappa=0.50`；赢家补仓最多两层，输家摊平与主动替换初始关闭。
- 校准与风险：交易窗口前至少252个交易日PIT warm-up，只训练不下单且不计入NAV；有效样本连续收缩而不是越过单一门槛跳变；统一使用`mu_shrunk - 0.50 * cluster_se`；协方差优先收缩估计，不足时回退主题/单股上限。
- 消融顺序：先完成C0-C7正确性消融，再依次B0基础入场/持有/灾难退出、B1赢家补仓、B2软退出、B3原子替换、B4输家补仓、B5市场覆盖；每次只改变一个经济开关。资金使用参数按缓冲2000→1000、软持股5→4、软单股25%→30%、暴露85%→90%逐项比较。
- 验证窗口：5日构造场景、60日工程冒烟、多个互不重叠180日开发切片、既有338日仅作污染回顾、最后冻结60日前向纸面窗口；同时执行成本倍增、延迟/滑点压力、区块bootstrap和多重试验修正。
- 防回归控制：WBS末梢必须记录owner/reader/writer/status；自动生成实际调用图并与WBS比对；每次改动设置change budget；加入黄金回放、起点不变、候选置换、一次优化、现金/NAV守恒、动作可达性等测试；所有产物固化代码、参数、数据、因子柜、成本、PIT与run身份。
- 上下游影响：上游增加warm-up数据读取但不改变交易区间；中游统一预测与动作合同并撤销重复交易权；下游订单、现金、成交、持仓、NAV和报告均以唯一ActionPlan ID贯穿，报告拆分战略预算、信号支持、整数可执行、计划和实际暴露。
- 研究依据：参考风险约束Kelly、协方差收缩、含交易成本的无交易区间、概率校准、PBO/DSR/Reality Check和stationary bootstrap；这些文献只约束设计原则，不构成A股样本外盈利证明。
- 详细设计：`reports/SCAP_V3_AGGRESSIVE_LEAN_FULL_PLAN_20260727.md`。
- 本次操作边界：仅新增完整设计报告和WBS提案末梢，没有修改评分、交易、补仓、退出、订单、费用或会计代码，没有启动新回测；WBS-06.12/WBS-08.16/WBS-10.22/WBS-16.20维持`proposed`，必须按构建阶段验收后才可转为`implemented/verified`。
- 是否允许上线：否。只有C0-C7全部通过、B0工程基线可复现，且后续单变量经济消融与冻结前向窗口满足预登记准入时，才可申请研究候选资格。

### CHANGE-20260727-03：SCAP-V3 Lean阶段A-B——身份隔离、合同升级、PIT warm-up与统一风险口径

- 对应末梢：WBS-06.12、WBS-10.22；状态由`proposed`推进到`implemented`，尚待20日产品链验证后转`verified`。
- 身份与参数：新增`small_capital_lean`资金档位和`aggressive_lean`控制模式，固定2万元、1,000元缓冲、5只硬上限/4只软目标、40%硬上限/30%软惩罚、10日预测、`kappa=0.50`、赢家加仓开、输家摊平和替换关；Web默认选择新身份，旧`aggressive_profit`保持兼容。
- warm-up：`RollingEntryCalibrator.warmup_from_feature_history()`只读取交易开始日前预载PIT特征，使用下一观察开盘和在交易开始前已完全成熟的10日收盘标签；记录样本、会话数、最后标签日和score列manifest，不更新现金、持仓、订单、成交或NAV。
- 校准数学：桶统计由硬30样本切换改为`n_eff/(n_eff+40)`连续向全局统计收缩；全局成熟样本仍须达到80才获得交易权；输出cluster SE、shrunk mean、`shrunk mean-0.50×SE`和漂移连续计数，负向证据连续三次才撤权。
- 统一口径：`action_utility.py`新增`shrunk_point_minus_0.50_cluster_se`口径，`position_lifecycle.py`补仓读取与开仓相同的资金档位口径，不再固定私有LCB。
- 合同：SCAP合同版本升级为`scap_v3_lean_contracts_v1`；ExposureAuthorization新增实际现金与三层暴露输入，ActionPlan新增plan ID并强制`optimizer_invocation_count==1`。
- 静态审查：固定解释器Python 3.10.19；相关14个Python文件`py_compile`通过；代码检索确认Lean入口、warm-up、身份、Web选项和一次优化字段均可达，旧`_select_scap_discrete_entries`仍只存在于旧模式路径。
- 运行测试：`verify_scap_v2_property_contracts.py`、`verify_scap_action_utility_v2.py`、`verify_scap_unified_action_contract.py`、`verify_scap_add_reachability_v2.py`、`verify_governance_temporal_isolation.py`全部退出0；测试同步更新为连续三次负向评估后撤权。
- 本阶段未运行策略回测；下一阶段必须让Lean在`policy.decide()`入口直接绕过旧整数选择和连续分配，再验证动作提案可达性和优化器现金单调性。

### CHANGE-20260727-04：SCAP-V3 Lean阶段C-D——统一动作提案与单次整数手数优化

- 对应末梢：WBS-08.16、WBS-10.22；代码状态`implemented`，专项性质测试`verified`，仍待真实20日产品链验证。
- 新模块：新增`functions/decision_council/scap_v3_lean.py`，集中生成新开仓、赢家加仓、实验性输家加仓及硬/软退出ActionProposal；所有提案统一10日、同一人民币增量财富合同，不直接生成订单。
- 权威切换：`RulesBasedPresidentPolicy.decide()`检测`control_mode=aggressive_lean`后立即进入Lean链，旧`_select_scap_discrete_entries`、连续`PortfolioConstructionCommittee`和旧`_apply_unique_action_plan`均不执行；旧模式路径未删除。
- 整数域：新开仓为同股1至可行最大手数的互斥备选；优化器新增同股多lot备选不可累计断言、实际现金扣1,000元缓冲约束、订单后单股40%约束和当前权重输入。
- 风险模型：有协方差时以70%样本矩阵+30%对角矩阵收缩；无可用矩阵时明确记录`fallback_thesis_caps`并使用论点族、单股和组合压力上限，不以零矩阵放行。
- 五层仓位前三层：授权记录`strategic_exposure_budget`、`signal_supported_exposure`和`integer_feasible_exposure`；ActionPlan记录`planned_exposure`，并计算signal/lot cash drag，禁止“无信号时目标=实际”循环。
- 静态审查：相关合同、优化器、提案工厂、policy和新验证脚本`py_compile`通过；检索确认Lean实盘入口位于旧选择器之前，`scap_v3_lean.py`只存在一次`optimize_action_proposals()`调用。
- 专项测试：新增`verify_scap_v3_lean_chain.py`并退出0，验证每个decision恰好一次优化/一个Plan、同股lot备选互斥、赢家补仓不依赖`add_allowed`可达、输家补仓默认关闭、现金下降买入手数不增加、旧选择器被替换为抛错桩时Lean仍成功、三层暴露次序可对账。
- 下一阶段：验证ActionPlan到现金保留、pending、事实执行、成交、持仓和NAV的唯一ID贯穿；任何Plan后软评分读取必须被静态门禁阻断。

### CHANGE-20260727-05：SCAP-V3 Lean阶段E——现金保留、pending、事实执行与ID贯穿复验

- 对应末梢：WBS-09现金/订单、WBS-11执行、WBS-14审计链；本阶段复用既有V2已实现模块，不重写会计和成交引擎，状态保持`verified`并增加Lean兼容证据。
- 静态复审：`action_plan_id/action_proposal_id/action_plan_selected`从policy订单进入`execution_runtime.py`并写入pending/执行负载；`cash_reservation_id`由逐单幂等账本生成、保留、释放和替换买腿排除自身；`pending_orders.py`固定schema保存全部ID。
- Plan后权限：`retail_execution.py`先复核现金缓冲、整手、单股上限和目标暴露等事实约束；识别有效ActionPlan后直接采用计划手数，不再读取`entry_confirmed`、`primary_score`、`scap_candidate_utility`或`add_allowed`重新评分。
- 专项测试：`verify_pending_order_idempotency_v2.py`、`verify_replacement_pair_execution_guard.py`、`verify_execution_rules.py`、`verify_v3_retail_audit_score_gate.py`、`verify_active_replacement_policy_integration.py`全部退出0，覆盖重复注册、部分成交重放、替换卖腿失败、费用/涨跌停、V3不重复矩阵分数门槛和pair lineage。
- 客观边界：以上证明合同和构造场景成立，尚未证明Lean真实日循环能够从Plan完成成交并保存；该证据留给最终20日全流程实验。

### CHANGE-20260727-06：SCAP-V3 Lean阶段F——旧暴露门禁撤权、五层仓位与静态权威图

- 对应末梢：WBS-08.16、WBS-16.20；状态`implemented`，静态与Web专项验证通过，等待20日run产物验证。
- 捕获的残留bug：runner在进入Lean policy之前仍把`entry_confirmed|add_allowed`计数用于可行增量，并可能用旧SCAP目标公式把目标回写到实际仓位；高暴露研究门禁还可能把Lean统一压到60%，与90%/65%/35%战略预算和“软证据不得硬否决”合同冲突。
- 修复：旧`build_scap_exposure_targets`与60%高暴露门禁只保留给`aggressive_profit`兼容路径；`aggressive_lean`按正常/弱势/高风险读取90%/65%/35%战略预算并只与事实safety cap取小，不使用force-deploy或旧信号计数获得买权。
- 仓位审计：Lean逐日输出`strategic_exposure_budget`、`signal_supported_exposure`、`integer_feasible_exposure`、`planned_exposure`和`actual_exposure`，另列signal cash drag、lot cash drag和execution drag；Web实时页新增前四项显示。
- 自动静态门禁：新增`verify_scap_v3_lean_static_authority.py`，AST/源码检查Lean模块只有一个优化调用点、policy在旧选择器前返回、ActionPlan执行分支不读取四类软字段、pending schema保留plan/proposal/reservation ID、四层计划前暴露均存在。
- 验证：相关文件`py_compile`通过；静态权威门禁、`verify_web_research_runtime_controls.py`和`verify_web_endpoint_links.py`全部退出0。
- 下一阶段：运行完整回归集并修复兼容性问题；通过后才能启动20日Web/worker产品实验。

### CHANGE-20260727-07：SCAP-V3 Lean阶段G——代码级全回归与20日启动准入

- 对应末梢：WBS-06.12、WBS-08.16、WBS-10.22、WBS-16.20；代码与构造测试状态`verified`，产品run状态仍待验证。
- 静态复审结论：Lean实盘链只有一个proposal factory、一个ExposureAuthorization、一个optimizer调用点和一个ActionPlan；旧SCAP选择/连续分配/二次计划只在兼容路径，执行分支无软评分二次否决；未发现Lean对`entry_confirmed/add_allowed/force_deploy`的交易权依赖。
- 全回归：`verify_governance_mainline_v3.py`、`verify_mainline_v3_single_score_chain.py`、SCAP stage1/3/4/5、`verify_governance_v3_lifecycle_math.py`、runtime identity、checkpoint/schema、experiment hygiene、Lean chain、Lean static authority、interactive worker isolation共13个脚本全部退出0。
- 覆盖：评分单写入、整手和现金缓冲、退出阶段、生命周期数学、运行身份、Ctrl+C checkpoint、原子保存、实验污染、多手互斥、赢家补仓可达、一次优化、旧路径绕过和worker故障披露。
- 20日准入：允许启动独立`small_capital_lean + aggressive_lean`工程产品run；该run只验证从初始化到保存的全链和真实动作可达性，20日收益不得作为盈利准入结论。

### CHANGE-20260727-08：SCAP-V3 Lean首个20日run第1日失败与诊断合同修复

- 失败run：`run20260727_013153`，可见命令窗口PID 47368，20日配置、E4、全A研究池、固定74因子柜、关闭影子组合；checkpoint在2025-01-02后写`status=failed/current_day=1/error=KeyError: unresolved_safety_exposure`，未生成完成标记，不作为结果。
- 根因：Lean正确绕过连续分配器后，runner监控/会计层仍直接索引三个原由旧分配器产生的诊断字段；属于跨模块输出合同遗漏，不是选股、行情或成交错误。
- 修复：Lean diagnostics显式提供`unresolved_safety_exposure=0`、`planned_safety_sell_weight=0`和`constraint_cash_reserve=1000`；这些是监控/会计兼容字段，不恢复旧分配器交易权。
- 验证：相关文件`py_compile`通过；Lean chain新增三字段合同断言并退出0；静态权威图仍退出0，确认修复没有引入第二优化器或旧选择器。
- 处理：失败目录与checkpoint原样保留；允许以新run身份重新启动相同20日配置。

### CHANGE-20260727-09：SCAP-V3 Lean首个完整20日保存成功但warm-up输入不足

- 完整run：`run20260727_013349`，20/20、2025-01-02至2025-02-06、checkpoint/COMPLETE/manifest均complete，`core/audit/web_complete=true`；109个CSV可读有表头、NAV误差0、持仓上限和数值有限性通过，因子Excel成功保存。
- 经济链失败：0提案、0订单、0成交、0仓位、期末20,000元；不能把保存成功解释为策略成功。
- 根因证据：environment manifest的Lean warm-up虽有1,280行，但只有32个独立会话，低于80会话全局交易权门槛；上游`run_governance_backtest`仍只按旧`GOVERNANCE_PRELOAD_CALENDAR_DAYS`加载短历史，未满足WBS-06.12的252交易日目标。
- 修复：`aggressive_lean`专属预载至少420个日历日，warm-up继续截取252个交易会话；manifest状态新增`insufficient_sessions`，独立会话少于`min(252,80)`时runner在交易循环前fail closed，不再允许“完整保存但必然零交易”的伪验收。
- 验证：相关文件`py_compile`通过；Lean chain新增120交易日合成历史，验证至少80独立会话、最后标签严格早于trade_start并退出0；时间隔离测试退出0。
- 处理：`run20260727_013349`保留为保存链成功/经济链失败证据；允许再次以新身份运行相同20日产品链，最终验收必须同时要求非零ActionProposal，订单/成交则按正效用与事实可行性解释，不强制制造交易。

### CHANGE-20260727-10：SCAP-V3 Lean充分warm-up后的多手最低佣金单位修复

- 充分warm-up run：`run20260727_014037`，254独立会话、10,160成熟行、最后标签2024-12-31；20/20和全部109 CSV/Excel/manifest保存验证通过，但仍为0提案/0订单/0成交。
- 分布证据：4,000条候选中3,408条一手事实可行；10日点预测最大约0.2939%、统一激进口径最大约0.1253%，但一手候选效用最大仍为-0.8749元。说明已不再是校准无权，而是一手最低佣金后没有正效用。
- 捕获的单位bug：提案工厂在生成2—4手备选前先用一手负效用删除股票；即使进入多手备选，也把包含买卖最低佣金的一手效用按手数线性相乘，相当于每手重复支付最低佣金，违反“整张订单只扣一次完整费用”。
- 修复：先读取正的统一10日预期收益，再为每个1—4手方案按总股数调用`round_trip_cost_amount`一次；分别计算点预测成本后利润和统一稳健利润，风险/集中惩罚按明确单位加入；同股lot方案仍互斥，负稳健利润仍不会被优化器选中。
- 验证：`py_compile`通过；Lean chain新增“一手净效用为负、合并多手后因最低佣金摊薄而正”的构造场景，确认选中多手且稳健利润为正；动作效用全套回归退出0。
- 处理：`run20260727_014037`保留为warm-up和保存成功、经济提案失败证据；下一run为单位修复后的最终20日验收。

### CHANGE-20260727-11：SCAP-V3 Lean多手修复后1月20日窗口验收

- run：`run20260727_014851`，2025-01-02至2025-02-06，20/20 complete，109个CSV、manifest三层完成、Excel和全链验证全部通过。
- 行为变化：总ActionProposal由上一版0增至47，证明多手成本修复使提案工厂可达；20日每日优化器调用总计20，保持每日恰好一次。
- 订单边界：47个提案仅在最后一日出现，统一稳健成本后利润仍均不为正，因此ActionPlan选择0、订单/成交/持仓0。不得为了覆盖成交而放行负净效用。
- 工程验收判断：初始化、warm-up、候选、proposal、一次优化、空计划、逐日checkpoint和全保存均通过；真实订单/成交分支仍未由本窗口覆盖。
- 后续窗口选择：为测试执行链，可使用既有受污染诊断中已知存在正提案的2025年3月作为“交易活跃工程窗口”；该选择明确属于构造/开发测试，不得作为收益或样本外证据。

### CHANGE-20260727-12：SCAP-V3 Lean 3月工程窗与warm-up评分器同源修复

- 工程run：`run20260727_015628`，2025-03-03至2025-03-28，20/20及全保存验证通过；269个提案分布于2日，20次优化，但0选中/0订单/0成交。
- 根因：warm-up使用`ret_20`单代理分数，正式日使用74因子柜ScoreContract；校准样本和购买候选并非同一预测器，导致桶映射退化到不匹配的全局先验，违反WBS-06.12与WBS-10.22的模块输入同源要求。
- 修复：Lean因子柜生成缓存的起点由trade_start前移到完整preload起点；warm-up接收当前factor cabinet `model_feature_map`列，在每个历史截面逐列排名后取均值形成`factor_cabinet_rank_mean`，manifest记录实际列数和身份；旧控制模式继续使用原缓存窗口。
- 验证：相关文件`py_compile`通过；Lean合成测试验证因子列评分身份、独立会话和标签截止；`verify_factor_cabinet_cache_window.py`退出0。
- 边界：因子排名均值是同一柜体的PIT代理，但不是正式ScoreContract公式的完整逐角色复刻；本阶段把它作为warm-up同源最小实现并在manifest披露，后续可用历史ScoreContract快照替换。下一次20日只用于验证该链接是否产生可比较提案和完整产品。

### CHANGE-20260727-13：Lean历史因子缓存缺口与物化准入

- 失败run：`run20260727_020400`在checkpoint创建前退出；同步1日复现得到`FileNotFoundError: factor_cabinet feature cache is required but missing or stale`。
- 具体缺口：现有74因子缓存不覆盖Lean所需的2024-01-08至2025-03-03 warm-up区间；系统正确fail closed，未回退到legacy或现场隐式重算，PIT/因子身份未被静默改变。
- 处理方案：先以独立`--factor-cabinet-feature-cache`任务物化固定因子柜在2024-01-08至2025-03-28的候选特征并验证manifest，再允许重新启动20日；缓存属于同一因子柜输入扩展，不改变策略参数。
- 验证边界：缓存任务完成前不得把`run20260727_020400`算作策略失败或产品run。

### CHANGE-20260727-14：Lean历史因子柜缓存完整物化与窗口核验

- 对应末梢：WBS-06.12、WBS-08.16、WBS-16.20；本记录承接CHANGE-20260727-13的缓存准入。
- 执行动作：在独立可见命令窗口运行固定因子柜缓存任务，解释器为`C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe`，范围为2024-01-08至2025-03-28，因子源`selected_factor_cabinet`，固定柜体`pruned_run20260714_184846_581132_20260715_230524`；进程PID 50492，全程可由键盘`Ctrl+C`中断。
- 运行监控：任务从2026-07-27 02:06:26运行至03:14，按固定45日历日批次持续刷新临时分片；监控期间CPU时间持续增长、进程始终响应，工作集约2.3至5.0GB，未发现假死、异常退出或无界内存增长。
- 物化结果：生成`factor_cabinet_features_20240108_20250328.manifest.json`及10个partitioned parquet分片；manifest记录`date_min=2024-01-08`、`date_max=2025-03-28`、`row_count=1,820,684`、`symbol_count=6,427`、`factor_count=74`、`chunk_count=10`、`storage_layout=partitioned_parquet_directory`。
- 输入身份：manifest的`cabinet_manifest_hash=b8dd096a6706b63e6e960d01e23fa647763b7cd5113ace055db58e2395788b90`，与固定因子柜运行身份绑定；输入特征文件存在并记录大小与mtime，不允许静默切换柜体或退回`ret_20`代理。
- 静态/运行验证：PowerShell逐项读取manifest和分片目录，确认10个分片、目标日期与74因子；`verify_factor_cabinet_cache_window.py`退出0并打印`[PASS] factor cabinet cache respects the bounded observed governance window`。
- 上下游影响：上游只扩展同一固定因子柜的历史观测窗口，不修改因子公式、PIT模式、成本或策略参数；下游允许重新启动`small_capital_lean + aggressive_lean`的20日全流程实验，并要求warm-up身份明确为`factor_cabinet_rank_mean`。
- 准入结论：缓存物化准入通过；允许启动最终20日工程产品run。缓存成功不等同于策略盈利或交易准入，最终仍需检查proposal、唯一optimizer、ActionPlan、订单、成交、持仓、NAV和保存链。

### CHANGE-20260727-15：因子同源20日run保存阶段标量/序列契约失败

- 失败run：`run20260727_031510`，独立可见PowerShell窗口PID 74032、Python PID 69940；配置为`small_capital_lean + aggressive_lean + E4 + all_a_share_research + fixed 74-factor cabinet`。
- 计算完整性：20/20交易日全部完成，日期2025-03-03至2025-03-28，运行身份哈希`64157724dff973840ac887247fea4ed1f01439b03ac37aa18dfa9571cf3e8a2c`全程不变，日循环error为空。
- 保存失败：核心ledger已经保存，进入`quality_reports`后抛出`AttributeError: 'numpy.float64' object has no attribute 'fillna'`；checkpoint正确写为`status=failed/stage=save_failed/current_day=20`，artifact manifest记录`core_complete=true/audit_complete=false/web_complete=false`。
- 客观判定：该run证明因子缓存、warm-up和20日决策循环可运行，但不满足“从开始到完整保存”的验收，不得冒充成功run；失败属于报表模块在缺列/退化输入下混用标量与Series的接口契约，不是策略收益结论。
- 诊断动作：通过artifact manifest把故障定位到`build_governance_quality_reports()`或其紧后监控输入段；下一run增加控制台transcript保留逐层quality stage与完整traceback，定位后做最小修复、静态检查、构造回归和重新20日全流程。

### CHANGE-20260727-16：Lean ActionPlan到风险贡献报告的权重字段适配修复

- 精确复现：`run20260727_032455`使用同一20日配置与可见窗口，完整transcript保存为`results/scap_v3_lean_console_20260727_0325.log`；traceback定位到`quality_reports.py:1188 build_risk_contribution_ledger()`。
- 根因：旧理想计划输出`ideal_weight`，Lean唯一ActionPlan输出`target_weight`；质量报告直接`data.get("ideal_weight")`，缺列后`pd.to_numeric()`得到`numpy.float64`标量，再调用Series方法`.fillna()`导致保存失败。该问题是明确的跨模块字段名链接错误。
- 修复：风险贡献报告优先读取`ideal_weight`，不存在时使用Lean的`target_weight`，两者都不存在时创建与输入DataFrame同索引的零Series；symbol缺省也改为同索引Series。报告适配不修改ActionPlan、订单、成交、成本或策略评分。
- 静态检查：`quality_reports.py`与`verify_scap_v3_lean_chain.py`的`py_compile`退出0；人工复核确认Series缺省索引与输入计划一致，没有把报告字段重新接回策略决策权。
- 构造回归：Lean计划只含`decision_date/symbol/target_weight/action_plan_id`，两只股票权重0.30与0.35；风险贡献报告成功生成且输出权重合计0.65。`verify_scap_v3_lean_chain.py`全部10项通过。
- 准入：允许重新执行最终20日全流程；必须完整通过quality reports、额外CSV、summary、Excel、manifest和全链验证后才算完成。

### CHANGE-20260727-17：旧入场状态机在ActionPlan后的隐藏软否决清除

- 发现证据：完整run `run20260727_033302`已通过20日和109个CSV全链验证，并产生7条ActionPlan订单；其中`sz001226`已被唯一优化器选中2手，但携带旧`position_state=blocked/entry_size_tier=blocked`，零售执行层将其改成0手，最终仅6笔成交。`governance_retail_execution_diagnostics.csv`明确记录`retail_block_reason=position_state`。
- 根因：Lean提案权威已不使用旧`entry_confirmed/entry_size_tier`，但position lifecycle仍根据这些旧软分数生成`position_state=blocked`；retail adapter在ActionPlan之后再次读取该派生状态，形成隐藏的第二次软评分否决。这正是购买因子、购买状态机与执行模块链接不一致。
- 修复一：Lean提案工厂在优化前吸收真正的事实状态，`cooldown/exiting/protecting_profit/exit_state`作为硬否决；旧的普通`blocked`不作为事实禁令。
- 修复二：零售执行识别有效`action_plan_selected + action_plan_id`后，不再用携带的旧`blocked`重否决；仍保留现金缓冲、整手、单股上限、目标暴露与实际市场权限等事实检查。
- 权限边界：修改只删除Plan后的旧软门槛，不允许负稳健利润、不取消冷却/退出事实、不绕过现金、T+1、涨跌停、停牌、仓位和成本约束。
- 静态与运行测试：相关三文件`py_compile`退出0；Lean chain新增“旧blocked状态不能否决已授权Plan”行为测试并全部11项通过；静态权威测试、执行规则测试全部通过。
- 验收要求：由于本次修改会改变真实成交数量，`run20260727_033302`保留为发现证据，不能作为最终代码状态的产品验收；必须重新运行同一20日窗口，并要求`ActionPlan selected`到事实订单不存在`position_state`软否决。

### CHANGE-20260727-18：ActionPlan→pending→fill血缘值丢失与验收器强化

- 发现run：`run20260727_034356`完整20日、109 CSV、Excel、三层manifest和原全链测试通过；状态机软否决为0，5条选中动作全部形成5笔成交。但逐值审计发现`executable_order_plan`中的`action_plan_id/action_proposal_id`在`pending_order_ledger`和`governance_execution_ledger`均为空，`cash_reservation_id`也为空。
- 根因一：`execution_runtime.register_orders()`构造pending payload时没有复制四个ActionPlan字段和reservation字段，虽然pending schema预先存在这些列，故此前“列存在”静态测试产生假通过。
- 根因二：成交payload中ActionPlan字段重复声明，且`cash_reservation_id`先读正常字段、后被不存在的`_cash_reservation_id`覆盖为空。
- 修复：注册payload显式复制`action_plan_id/action_proposal_id/action_plan_selected/action_plan_contract`，并把`_cash_reservation_id`或已有reservation写入pending；成交payload删除重复键，直接从pending的正式`cash_reservation_id`读取。
- 防回归：pending幂等测试改为写入非空plan/proposal/reservation并断言实际值保留；静态权威测试检查注册函数确实复制字段，而不是只检查schema；全链验收器从`executable_order_plan`的选中键反向join pending与fill，防止空`action_plan_selected`造成空集合假通过。
- 测试：四文件`py_compile`通过；静态权威测试与pending原子/幂等/部分成交测试全部通过。此前`run20260727_034356`保留为“经济链完整、审计血缘失败”证据，不得作为最终代码状态验收。
- 最终准入：必须再运行相同20日窗口，要求每个实际注册/成交的选中动作均有非空plan、proposal和cash reservation ID，全链验收器新断言通过。

### CHANGE-20260727-19：SCAP-V3 Lean最终20日全流程、非空血缘与经济结果验收

- 最终run：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1500/v3/run20260727_035455`；独立可见PowerShell窗口PID 12832、Python PID 73172，支持`Ctrl+C`；完整控制台transcript为`results/scap_v3_lean_final_lineage_20260727.log`。
- 运行身份：2025-03-03至2025-03-28共20个交易日，`runtime_identity_hash=e91a418dbebee42f5fb1f16b8ebaacf37873c6f80ba1d122871bef4a17804ffb`；固定74因子柜、全A研究池、2万元Lean档、E4、research PIT。
- 完整保存：checkpoint=`complete`，artifact manifest=`complete`，`core_complete/audit_complete/web_complete=true`，error为空；109个CSV均可读且有表头，持仓逐因子Excel成功保存。
- 权威链计数：20日合计9,337个ActionProposal；严格20次optimizer invocation、20个ActionPlan；5个选中动作、5条订单、5笔filled买入；旧`position_state`软否决0。
- 血缘：5条selected pending与5条selected fill的`action_plan_id/action_proposal_id/cash_reservation_id`全部非空，registration key和fill ID均唯一；全链验收器从选中计划反向join实际ledger，防止空值假通过。
- 事实约束：最大持仓3只（上限5），最低现金7,163.50元（高于1,000元缓冲），最大单股账户权重31.0833%（低于40%硬上限），最大实际暴露64.7109%，NAV对账最大误差0，无无限数值。
- 经济结果：初始20,000元，期末19,224.503671元，20日成本后收益-3.8774816%，最大回撤-5.295696%，平均实际暴露54.2948%，期末3只持仓、0笔闭合交易；research gate正确为`blocked`。该短窗证明工程链和购买可达性，不证明盈利准入。
- 单变量对账：与只差血缘修复的`run20260727_034356`逐日NAV、现金和持仓数最大差异均为0，确认血缘修复没有改变经济行为。
- 最终全链验证：completion、20日、checkpoint、109 CSV、日唯一性、NAV、暴露、持仓、11项runtime integrity、fill幂等、pending幂等、非空pending/fill血缘、无旧状态机软否决、有限数值、development标签和Excel全部PASS。
- 最终代码回归：相关文件`py_compile`通过，`git diff --check`通过；Lean chain、静态权威、pending原子/幂等、因子缓存窗口，以及mainline V3、单分数链、生命周期数学、行动效用、统一行动、补仓可达、时间隔离、替换执行、零售评分、实验卫生、checkpoint/schema、worker隔离共12组广义回归全部退出0。
- 准入结论：工程验收通过，研究盈利准入不通过。允许作为`development_audit`继续扩大预注册滚动样本；禁止根据本20日亏损窗口临时调参，也禁止将其宣传为已盈利策略。

### CHANGE-20260727-20：分层消融入口Lean预载合同漂移与跨年度缓存链接修复

- 对应末梢：WBS-06.12、WBS-08.16、WBS-10.22、WBS-16.20；上游为交互任务`governance_layer_validation`和固定74因子柜，下游为Lean warm-up、唯一ActionPlan、180日治理循环与完整保存链。
- 失败证据：用户启动的`run20260727_070919`在交易循环前fail closed；warm-up仅有32个独立会话、1,280个成熟行，状态为`insufficient_sessions`。日志中的特征过滤起点为2024-11-02，证明实验入口仍硬编码60日预载，未继承主治理入口已实施的Lean 420日合同。
- 根因：`functions/decision_council/runner.py`的主入口已对`aggressive_lean`使用至少420日历日，但`run_governance_experiments.py::_load_governance_features()`独立写死60日；同一产品档位在两个入口产生不同模块输入，是入口参数漂移，不是策略自然保守或数据本身缺失。
- 修复一：在runner新增唯一函数`governance_preload_calendar_days()`，主治理入口与治理实验入口共同调用；Lean至少420日，其他控制模式保持配置值。实验进度现在同时披露交易窗口、特征窗口和实际预载天数，便于命令窗口直接审计。
- 修复二：实验入口把同一个`load_start`传给基础parquet、legacy候选缓存和固定因子柜缓存，避免“基础特征已预载、候选因子仍从交易起点开始”的隐性错位。
- 后续缺陷预防：真实420日窗口跨越2024/2025缓存边界，而缓存查找器此前只接受单个文件覆盖全窗。新增同一柜体hash、同一输入指纹、完整列合同下的相邻缓存贪心覆盖与拼接；存在日期重叠时按`date/symbol`去重，不允许跨柜体、过期指纹或缺列缓存混合。
- 静态与构造验证：相关五文件`py_compile`退出0；`verify_governance_experiment_lean_preload.py`确认两个入口共享420日合同且不再含60日硬编码；`verify_factor_cabinet_cache_stitching.py`确认相邻跨年度缓存可组成连续窗口。
- 真实输入只读核验：固定柜体`pruned_run20260714_184846_581132_20260715_230524`在2023-11-08至2025-09-25窗口找到两段同hash缓存：2021-01-01至2024-12-31、2025-01-01至2026-05-31；未新建、覆盖或删除缓存。
- 当前状态：代码层首个报错已修复，原失败run保留为入口漂移证据。下一步必须先跑专项/宽回归，再以同一交互配置重跑，确认warm-up达到ready并继续检查日循环、报告和保存阶段是否暴露新的链接错误。

### CHANGE-20260727-21：分层消融真实跨年冒烟与180日重跑准入

- 回归阶段：13项专项/宽回归全部退出0，覆盖统一预载、跨缓存拼接、bounded window、Web/CLI入口一致性、分层验证因子源、进度、信号报告、worker隔离、Lean唯一优化器和ActionPlan权威。测试替身曾因未接收新增`governance_control_mode`关键字失败，已同步接口后整组重跑通过；该失败属于测试夹具漂移，不是生产日循环错误。
- 真实跨年读取：在固定74因子柜的2024-12-30至2025-01-03边界读取24,900行、76列（date/symbol加74因子），`date/symbol`重复为0，证明两段真实物化缓存可无缝链接。
- 可见进程：新增通用`tools/run_interactive_selection_visible.ps1`，固定调用`C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe -u main.py --interactive-selection-file ...`，使用独立可见PowerShell、transcript和末尾退出码；运行中可直接按`Ctrl+C`，失败窗口保留错误。不得把该脚本改成后台静默吞错。
- 1日真实Web路径run：`results/governance/all_a_share_research/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_lean/v3/run20260727_072020`；配置与用户失败run同源，仅把`max_days`缩为1用于放行测试。
- 冒烟结果：特征预载起点为2023-11-08；warm-up=`ready`，10,160成熟行、254独立会话、74因子、最后标签2024-12-31且早于2025-01-02交易起点。1/1日完成，148个顶层文件，checkpoint和`COMPLETE.json`均complete，runtime error为空，进度100%。
- 资源证据：冒烟进程CPU持续增长、始终Responding；工作集峰值约4.35GB后回落至约1.8GB。说明扩大预载显著增加内存，但未观察到无界增长或假死；180日必须保持full档且不得并行启动另一个重型因子任务。
- 准入：原`insufficient_sessions`已由真实入口证伪并修复；缓存、日循环和保存链也已贯通。允许启动用户原配置的180日完整历史复核，继续以checkpoint、进度文件、可见窗口和最终artifact manifest监控后续缺陷。

### CHANGE-20260727-22：180日全流程结果、风险上限退出断链与长路径兼容修复

- 180日run：`results/governance/all_a_share_research/governance_layer_validation/cab_c6dae8d4d69c/small_capital_branch/ctrl_aggressive_lean/v3/run20260727_072414`；独立可见PowerShell父PID 52356、Python PID 66040，2025-01-02至2025-09-25共180日。
- 计算/保存结果：180/180日循环完成；checkpoint、`COMPLETE.json`、artifact manifest均complete，`core/audit/web_complete=true`，error为空；150个顶层产物，holding factor Excel成功生成。预载峰值工作集约4GB，日循环约1.0至1.5GB，进程始终Responding且CPU持续增长。
- 全链通过项：180日和日期唯一、NAV对账误差0、持仓上限、target exposure边界、fill/order幂等、8条selected pending与8条selected fill的plan/proposal/reservation血缘、旧position-state软否决0、有限数值、development标签和因子Excel均通过。
- 新缺陷一：运行完整性11项中`execution_exposure_authorization`失败。具体为2025-01-06风险上限由85%降到35%后，实际约81%仓位继续持有；共6个越权日，最大超额46.1019个百分点。首日买入本身在当日85%授权内，问题是“上限下降→退出”链接缺失，不是优化器首日买超。
- 根因与修复：Lean旧逻辑只把`hard_freeze`用于禁止新增，未在当前暴露高于新`risk_exposure_ceiling`时生成退出提案，同时错误报告`unresolved_safety_exposure=0`。新增按`comparable_expected_alpha`从弱到强的事实型`exposure_cap_safety_exit`，以整只持仓退出直到下一交易日可回到授权上限；提案进入同一个唯一优化器并作为强制事实动作，不恢复任何旧软评分买入门槛。diagnostics现在记录实际计划减仓权重和仍无法解决的暴露。
- 新缺陷二：130个CSV中最长的`governance_failure_lab_cost_capacity_trade_reconstruction.csv`普通读取失败；实验run基础目录长202字符，完整文件长264字符。写入层使用Windows扩展路径所以能保存，但普通Pandas/用户软件不一定能打开。
- 路径修复：治理实验入口的`aggressive_profit/aggressive_lean`现与主治理入口统一为短根`GOVERNANCE_OUTPUT_DIR/scap/{factor_label}/{exit_stage}_l{loss_bp}`；完整universe、variant、capital profile、control和代码身份继续写入manifest，不靠深目录表达身份。
- 防回归：Lean chain新增“0.60当前暴露、0.35新上限”场景，确认唯一ActionPlan包含`safety_exit`、planned exposure不高于0.35、planned/unresolved safety字段正确；短路径静态测试、输出长度测试及入口/预载/缓存测试通过。`verify_governance_runtime_integrity.py`旧夹具缺少新增暴露审计输入列，已补齐同一接口后需重跑。
- 客观判定：`run20260727_072414`证明180日计算与保存稳定，但全链完整性不通过，不能作为最终产品验收或收益依据。修复会改变1月风险期真实交易，必须至少重跑覆盖2025-01-06上限下降的20日窗口并要求runtime integrity全绿；禁止只改报告把越权日隐藏。

### CHANGE-20260727-23：安全退出后Lean购买漏斗仍读取旧状态机的断链修复

- 失败run：短路径修复后的`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1500/v3/run20260727_082046`，20日目标窗口在第8日fail closed；checkpoint=`failed`，最后成功日期2025-01-13前，错误为`raw_signal=0 ... optimizer_selected=0, registered_buy=2`。
- 排查结论：安全退出已使原持仓退出并释放现金；随后Lean唯一优化器按自身正收益/硬事实合同选择了2个新入场订单。但候选漏斗的raw/structural/cash/slot/optimizer计数仍来自旧`entry_confirmed/add_allowed`状态机，registered buy来自新ActionPlan订单，导致同一行混用两套购买权威。不是安全卖出被错误映射成buy，而是购买端审计继续引用已降级为shadow的旧状态机。
- 修复：Lean提案工厂在唯一权威链内记录五级购买计数：正收益原始信号、硬结构可行、现金可行、slot可行、优化器选中；全部按distinct symbol计数，lot备选不重复膨胀。runner在`aggressive_lean`漏斗中只消费这些Lean计数；旧`aggressive_profit`与其他模式保持原计数。
- 权限边界：此次修改只统一审计输入源，不增加或删除任何提案、订单或成交，不恢复`entry_confirmed`软门槛，也不把卖出混入购买漏斗。单调断言继续fail closed，registered entry buy仍必须是optimizer selected entry的子集。
- 防回归：Lean chain新增五级计数单调断言；下一步执行语法、Lean/漏斗/权威回归后，从同一2025-01 20日窗口重新运行。`run20260727_082046`保留为购买状态机双权威证据，不得作为策略结果。

### CHANGE-20260727-24：购买漏斗修复后20日全链与安全退出语义收口

- 最终经济链run：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1500/v3/run20260727_082633`；2025-01-02至2025-02-06共20日，固定74因子柜、全A研究池、2万元Lean、E4、research PIT、shadow off。
- 完整保存：20/20、checkpoint/COMPLETE/artifact manifest均complete，150个顶层产物；130个CSV全部普通路径可读且有表头，证明短SCAP根修复了264字符文件不可读问题；holding factor Excel成功。
- 全链：11项runtime integrity全绿，暴露授权越权日由原6日降为0；NAV误差0、最大持仓4/5、fill和pending幂等；7条selected pending与7条selected fill血缘完整，旧position state软否决0；Lean五级购买漏斗逐级单调。
- 行为证据：9笔成交=7买+2卖；首日4个new entry，次日1个`winner_add`真实补仓，2025-01-06上限降至35%后在2025-01-07成交2个`safety_exit`，随后2025-01-13新ActionPlan在次日成交2个new entry。证明购买、补仓、风险退出和退出后再入场都可达。
- 经济结果：20,000元至20,269.149981元，成本后+1.34575%，最大回撤-2.85119%，平均暴露51.1727%，最大暴露80.7752%，最低现金3,769.74元。仅为开发窗口，不构成盈利/实盘准入；不得据此临时调参。
- warm-up：`ready`，10,160成熟行、254独立会话、74个因子列、最后标签2024-12-31严格早于交易起点。
- 语义尾项：值级审计发现两个事实安全退出的`unified_action_selected=safety_exit`正确，但order reason仍写`normal_sell`，会污染按卖出原因归因。policy已改为安全退出固定`reason=safety_deleveraging`；该改动不改变side、数量、价格、成本、选择或NAV，只收口原因标签。Lean回归新增“安全提案→sell side→safety_deleveraging”断言，需通过语法与行为测试后交付。

### CHANGE-20260727-25：最终代码态20日全流程与安全退出原因验收

- 最终run：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1500/v3/run20260727_083759`；独立可见PowerShell父PID 30420、Python PID 67412，支持`Ctrl+C`，transcript为`reports/layer_validation_20d_final_20260727.log`。
- 配置：2025-01-01至2026-05-31请求窗、`max_days=20`，实际2025-01-02至2025-02-06；full档、shadow off、全A研究池、2万元Lean、E4/-15%、mainline V3 cabinet native、research PIT、固定74因子柜。
- 完整保存：20/20，checkpoint/COMPLETE/artifact manifest均complete，error为空，150个顶层产物；130个CSV全部普通路径可读且有表头，Excel成功。
- 全链：completion、日数、日期唯一、NAV误差0、target exposure、持仓上限、11项runtime integrity、fill/order幂等、7条selected pending/fill非空血缘、旧状态软否决0、有限数值、development标签全部PASS。
- 安全退出值级证据：2025-01-06决策在2025-01-07成交`sh603091` 100股与`sz001226` 200股，两者`side=sell`、`unified_action_selected=safety_exit`、`reason=safety_deleveraging`；暴露授权越权日0。
- 单变量对账：与仅差原因标签的`run20260727_082633`逐日`nominal_nav/cash/actual_exposure/holding_count`最大差异全部0，确认语义修复没有改变经济行为。
- 最终回归：相关核心文件`py_compile`通过；Lean chain、静态权威、运行完整性、退出合同、五组候选漏斗/统一动作、统一预载、跨年缓存、短路径、入口一致性、worker隔离共14组退出0。
- 交付判定：本轮工程bug修复与20日全流程验收通过；180日旧代码run的完整性失败已明确隔离，不能作结果引用。最终20日为开发工程证据，收益+1.34575%不构成盈利准入或实盘授权。

### CHANGE-20260727-26：小资金黄金版本复原初期代码快照分支

- 用户目标：在继续分析27日晚间长窗口结果前，先把当前“小资金黄金版本复原初期”代码态冻结到独立GitHub分支，保留可回退、可比较的工程基线。
- 分支：`codex/scap-golden-restore-initial-20260727`，基于`main@56908d7`创建；提交范围为当前源代码、模块、验证脚本、WBS与正式设计/审计文档。
- 范围边界：不提交`data/`、`outputs/`、`results/`、`runs/`、回测产物目录、临时stdout/stderr和生成型报告目录；这些文件不是代码基线且可能包含数GB数据。
- 上游/下游影响：本项只做版本冻结，不改变因子、候选、购买状态机、补仓、退出、执行、会计或报告公式；后续normal档位诊断必须以该分支代码态和明确run身份为依据。
- 验证要求：提交前执行`git diff --check`、核心变更文件`py_compile`及与最终20日验收相匹配的专项回归；推送后核对远端分支与提交哈希。
- 发布记录：快照提交`3bcb747b254b2fdec503350221bdb0dfe4ac80a2`已与远端同名分支核对一致；用户随后明确授权合并主干，采用从`main@56908d7`到快照分支的快进合并，合并前再次确认未跟踪运行产物不在提交范围。
- 准入语义：该分支是开发复原基线，不等同于盈利准入或实盘授权；任何后续参数/逻辑修正必须另立WBS变更并使用受控窗口重验。

### CHANGE-20260727-27：27日晚间180日run第130日normal仓位约56%诊断

- 诊断对象：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260727_213603`；完成时间2026-07-27 22:51，`COMPLETE.json=complete`，实际180个交易日，最后日期2025-09-25。该run为`aggressive_lean`、2万元、最多5只、E4、止损-12%、固定74因子柜；不是普通保守策略。
- 第130个交易日：2025-07-17，`risk_level=normal`、`structural_regime_level=bull`、4只持仓；实际暴露56.4659%。真正的安全/授权链为`raw_safety_exposure_cap=100%`、`safety_exposure_cap=100%`、`exposure_cap=90%`、`strategic_exposure_budget=90%`、`effective_target_exposure_cap=90%`，因此不存在“normal状态被安全模块硬压到50%”。
- 字段语义：页面/日表的`target_exposure=56.4659%`来自Lean唯一ActionPlan的`planned_exposure`，表示“优化器本日选完动作后的计划仓位”，不是风险上限。当天没有选中买单，计划仓位自然等于实际仓位；把它理解为“仓位上限”会得到错误结论。
- 购买漏斗：同日Lean权威诊断有197个正收益原始信号、168个结构可行、168个现金可行、168个slot可行；信号支持暴露64.3602%、整数可行暴露64.3602%，但唯一优化器从419个动作提案中选择0个、拒绝419个，`solver_status=optimal_bounded_exhaustive`。因此50%附近停滞发生在“整数ActionPlan约束选择”，不是因子无信号、现金不足、安全上限或normal状态。
- 接线缺陷一：`runner.py`在调用Lean唯一优化器前仍用旧`_scap_entry_stage_counts(candidates)`驱动`_authorize_exposure_by_regime()`和`decide_exposure_catchup()`；同一日旧口径记录raw/structural/cash/slot全0、`too_few_confirmed_entries`、`insufficient_confirmed_entries`和旧授权55%，而Lean权威口径为197/168/168/168。Lean随后把真实战略上限改回90%，所以该断链主要污染页面、追仓诊断和旧授权字段，但造成“有168个候选却显示0个”的自相矛盾。
- 接线缺陷二：`integer_action_optimizer.py`把所有当前持仓和新候选按`thesis_by_symbol`重新计数，并硬要求每个论点族不超过2只；`scap_v3_lean.py`传入的是当日动态`cabinet_entry_thesis`，而生命周期账本保存的是买入时锁定的`entry_thesis`。2025-07-17生命周期账本为3只`size_style`加1只`momentum`，已是继承性超限；当前代码没有“既有超限不得恶化、但允许其他论点新增”的过渡规则，且没有把419条拒绝原因保存成正式产物。结合单股权重均低于40%、4/5槽位、现金约43.5%、90%风险上限、单笔压力预算和单买不产生相关性交互惩罚，论点族硬约束/持仓论点口径漂移是当天全部可行买单归零的唯一剩余硬约束，属于高置信根因；由于拒绝明细未落盘，不能伪称已有逐提案直接证据。
- 影响链：上游为cabinet动态经济族、生命周期锁定论点和候选是否包含全部持仓；中游为Lean提案、`current_lots`、论点族计数和唯一整数优化器；下游为买入/补仓可达性、`planned_exposure`、页面目标仓位、追仓原因和候选漏斗。安全退出、T+1、现金非负、费用、PIT和真实90%上限本次未发现异常。
- 建议修复合同：持仓约束使用锁定`entry_thesis`，新候选使用当日候选论点；若组合已有同族超限，只禁止继续增加该族，允许不恶化现状的其他论点买入或减仓方案；所有活跃持仓必须独立于候选当日一手字段进入`current_lots/current_symbols`；Lean模式下授权、追仓、日表和Web只消费Lean五级漏斗；`target_exposure`在Web明确标为“计划后仓位”，把`effective_target_exposure_cap`保留为“授权上限”；优化器按原因保存每个拒绝提案。
- 当前处置：本项只做只读诊断和WBS登记，没有修改交易逻辑，也没有用历史结果临时调参。修复必须新增专项性质测试（继承性论点超限、动态论点漂移、4/5槽位仍可买其他族、拒绝原因守恒、Lean计数单一权威），再跑20日工程窗和覆盖2025-07-17的受控窗口。

### CHANGE-20260727-28：180日结果复盘与SCAP-V3.1黄金复原提升方案

- 对应叶节点：WBS-05.09、WBS-07.07、WBS-08.15、WBS-10.20、WBS-11.07、WBS-13.03、WBS-14.11、WBS-16.20；完整方案见`reports/SCAP_V3_1_GOLDEN_RESTORE_IMPROVEMENT_PLAN_20260727.md`。
- 受控基线：仅分析`run20260727_213603`，不与不同代码态、费用、缓冲、PIT或因子柜的run伪作单变量比较。180日收益+12.7988%、最大回撤-10.1305%、平均暴露61.9834%，基准+32.2809%，已投入资金收益+22.2659%且仍落后基准约7.54个百分点。
- 盈利质量：7笔闭合交易、PF 1.6142、已实现利润577.95元；单笔利润硬止盈贡献1,057.93元，去除此笔后其余闭合交易约亏480元。终值利润约78%来自5只未平仓浮盈，且前两只贡献约75%的未平仓浮盈，当前盈利高度删失和集中。
- 买入链：35,499个Lean原始信号、26,091个结构/现金/slot可行、仅12个优化器新入场；172/180日有slot可行候选但无新入场，162/180日计划仓位等于实际仓位。`scap_profit_summary`却记录optimizer-selected样本0，证明选择血缘未进入利润审计。
- 状态机证据：同日配对失败实验中，L0到L1当前角色确认在5/10/20日分别产生约-0.64%/-0.86%/-3.58%增量；L1到L2主入场Top3部分恢复收益。该证据为关联性而非因果，但足以要求把L1硬门单独消融，而不是继续默认越严格越好。
- 补仓/退出：8笔赢家加仓10日平均收益+0.89%、超额+3.20%、盈亏比2.05，但20日转为负，故保留加仓并增加10日独立复核；亏损摊平和主动替换无新正证据，继续关闭。两笔损失退出后10/20日平均反弹约9.99%/22.75%，应消融普通损失确认与分批退出；利润硬止盈本窗有效，保留。
- 新P0费用缺陷：候选和成本压力使用5元最低佣金，实际执行账本消费全局`MINIMUM_COMMISSION=0`，27笔成交佣金合计仅25.23元，多笔低于5元；候选目标、成交账本和结果不在同一成本口径。
- 新P0产品输入缺陷：`small_capital_lean`档位声明1,000元缓冲，Web输入默认2,000元并显式覆盖；本run identity确认为2,000元。页面档位说明与实际输入不同，额外冻结约5%初始资本。
- 推荐版本：`small_capital_aggressive_profit_v3_1_golden_restore`。首轮只实施统一资金/费用事实源、Lean漏斗与拒绝血缘、论点族非恶化、完整持仓集合、L1角色确认硬门转软惩罚和Web三种仓位语义；保留90/65/35风险预算、赢家加仓、E4、T+1/PIT/现金/无杠杆等硬约束，不恢复亏损摊平或主动替换。
- 消融顺序：B0当前基线；B1统一5元佣金与1,000元缓冲；B2只修Lean审计；B3论点族非恶化；B4角色确认软化；B5经济族归一；B6加仓10日复核；B7普通损失退出确认/分批。禁止多模块同时开启后宣称单变量提升。
- 验收：先20日工程窗，再定点覆盖2025-07-17，再同一180日B0-B7，最后预登记滚动和留出窗；要求11/11完整性、费用逐笔一致、拒绝原因100%、selected cohort非0、越权/负现金/超持仓为0，经济侧以成本后终值利润为主、PF≥1.15、60日滚动胜率>50%、闭合交易≥30，并完成PBO/DSR/SPA。
- 当前状态：本变更只新增分析与设计文档，没有修改交易代码或参数；现有run仍为`development_audit`且research gate blocked。

### CHANGE-20260727-29：SCAP-V3.1完整数学、金融、代码映射与需求论证

- 对应叶节点：WBS-01.06、WBS-04.01—05.10、WBS-06.10—06.12、WBS-07.07—07.08、WBS-08.07—08.17、WBS-09.05—09.14、WBS-10.17—10.22、WBS-11.07—11.09、WBS-13.03—13.15、WBS-14.03—14.18、WBS-15.01—15.13、WBS-16.19—16.21；完整设计见`reports/SCAP_V3_1_GOLDEN_RESTORE_FULL_MODEL_SPEC_20260727.md`。
- 代码映射复核修正上一轮的过度归因：V3 Lean在`policy._decide_scap_v3_lean`中已绕过旧连续分配并由`build_lean_decision`调用一次整数优化器；双优化问题主要仍属于旧`aggressive_profit`链。旧`entry_confirmed`仍影响诊断和生命周期字段，但Lean新开仓硬否决未直接消费该角色矩阵，所以“角色确认造成全部不买”只保留为待消融假设。
- 新P0漏斗缺陷：`scap_v3_lean.py`把`lean_slot_feasible_entry_count`直接赋为与现金可行相同的`proposal_entry_symbols`数量，没有扣除真实已有持仓、条件退出释放槽位或区分加仓；此前“172/180日slot可行”不能作为真实槽位证据。
- 新P0风险量纲缺陷：`runner._rolling_candidate_covariance`输出收益协方差，Lean再次收缩后传给`integer_action_optimizer`，后者按相关系数公式读取并乘人民币利润；协方差与相关性单位混用会使交互风险惩罚失真。新增WBS-11.09要求显式风险单位合同和唯一收缩入口。
- 费用结论细化：`scap_candidate_minimum_commission=5`只进入部分候选费用率诊断和压力准入；人民币动作效用的`round_trip_cost_amount`仍消费全局`MINIMUM_COMMISSION=0`，实际成交也沿用全局配置。问题是同名费用参数未形成唯一经济事实，而非简单的“优化器5元、执行0元”。新增WBS-09.14要求统一不可变费用profile。
- WBS状态校正：`runner._high_exposure_research_gate`当前代码已不再以胜率或盈亏比硬否决，WBS-11.04改为“部分实现”；压力利润和模型权威仍需进入唯一准入合同。新增WBS-08.17明确Lean档位1,000元缓冲与Web继承规则，避免旧`small_capital_branch`的2,000元口径覆盖Lean。
- 完整模型：给出终端净利润、整数手/现金/持仓约束、家族—角色评分、滚动校准与收缩均值、逐腿费用、同基准增量财富、整数ActionPlan、协方差/CVaR、盈利加仓、普通/灾难退出、基准和过拟合检验公式；所有软动作统一比较同期限成本后人民币增量财富。
- 推荐施工：Phase 0—3先修运行身份、费用、slot漏斗、拒绝血缘、协方差量纲和论点非恶化，保持90/65/35风险预算、1,000元缓冲、最多5只、单股40%、赢家加仓、E4和市场硬约束；亏损摊平与主动替换继续关闭。之后才逐项消融角色软证据、赢家加仓和退出。
- 验收：每阶段先不运行主流程的静态/调用图检查和性质测试，再做20日Web启动—可见worker—Ctrl+C退出码130/checkpoint—恢复—成交—保存全链；经济结论依次使用同口径180日开发窗、滚动块和未触碰留出/前瞻纸面证据。20日只证明工程链，不证明盈利。
- 当前状态：只新增设计文档并更新WBS，未修改任何交易代码、配置参数或历史run；`run20260727_213603`继续标记`development_audit/research gate blocked`。

### CHANGE-20260727-30：V3.1优化器严格度反方审计与激进交易权修订

- 对应叶节点：WBS-06.11、WBS-07.07、WBS-08.03、WBS-08.10—08.18、WBS-10.20—10.22、WBS-11.07—11.10、WBS-14.17、WBS-16.17、WBS-16.21—16.22；修订文档仍为`reports/SCAP_V3_1_GOLDEN_RESTORE_FULL_MODEL_SPEC_20260727.md`。
- 只读严格度证据：180日平均每日约355.11个动作提案，但162日一个动作也未选，172日没有新入场；25日实际持仓少于4只，其中20日同时存在当前口径的现金可行正信号却没有新入场。由于现有slot计数错误和拒绝原因笼统，这不能直接归因某个约束，但足以否定“修完风险和审计自然就会变激进”的假设。
- 反方结论：上一版方案部分偏严。若所有交易都要求A级`mu-0.50SE`权威、同论点硬2只，并在修正协方差后同时叠加CVaR/相关/风险罚分，优化器仍可能长期选择现金，甚至比当前更少买。
- 修订交易权：新增A/B/C/D四层。A要求全局有效样本至少80、至少60个独立交易日、rank IC/斜率为正并使用0.50SE；B要求有效样本30—79、至少20个独立日、方向/漂移不负，使用0.25SE且每只只允许一手、B层总暴露不超40%；C不得使用伪概率，只消费独立PIT因子族Top分位成本后回退分布，全组合最多一个一手；B+C探索合计不超55%；负IC、负校准斜率、漂移或成本后负价差为D，无交易权。
- 修订集中约束：同论点2只改为软上限，第3只支付人民币集中风险CE，3只为硬上限；既有超限只禁止继续恶化，不阻止其他族买入和降低集中。
- 修订风险惩罚：同一ActionPlan只允许CVaR、协方差边际波动CE或保守硬上限中的一种主风险表达，禁止重复扣减。风险模型修复与激进交易权必须在同一阶段验收，避免只修风险导致再次保守化。
- 新增liveness合同：normal/bull、持仓少于4只、无安全冻结，且至少一个A/B一手提案成本后决策效用为正、现金/槽位/单股/硬论点/压力约束均有slack时，空新入场计划属于优化器性质测试失败。这不是强制满仓，而是要求正效用可行计划支配零效用现金计划。
- 当前状态：仅修改方案与WBS，没有修改代码、参数或历史run。需用户确认后才进入Phase 0—3A代码实现。

### CHANGE-20260728-31：SCAP-V3.1黄金复原实施（阶段0—6）

- 对应叶节点：WBS-06.11、WBS-07.07、WBS-08.17—08.18、WBS-09.14、WBS-10.20—10.22、WBS-11.07—11.10、WBS-14.17、WBS-16.21—16.22。
- 阶段0基线：解释器`stock_ai Python 3.10.19`；改动前`verify_scap_v3_lean_chain.py`、`verify_scap_v3_lean_static_authority.py`、`verify_scap_action_utility_v2.py`、`verify_scap_v2_property_contracts.py`、`verify_scap_web_contract.py`全部通过。工作树中既有未跟踪报告产物均未删除、未覆盖。
- 阶段1资金/费用事实源：`small_capital_lean`固定声明`execution_cost_profile_id=cn_a_share_retail_min5_v1`、1,000元现金缓冲和5元最低佣金；新增`cost_kwargs_from_profile`，贯通候选往返费用、订单模拟、成交重算、条件卖出现金和零手适配；Web缓冲输入改为留空继承档位，避免2,000元静默覆盖。首次测试捕获配置常量定义顺序导致的`NameError`，修正后语法检查、Lean链、Web合同和执行规则通过。
- 阶段2—3A交易权/优化器：新增`scap_v31_authority.py`，实现A/B/C/D权威、A的0.50SE、B的0.25SE与一手限制、C仅消费PIT可比收益回退且最多一只、D无交易权；校准器新增独立会话数。优化器增加B不超40%、B+C不超55%、论点软2/硬3和既有超限非恶化；持仓使用生命周期锁定`entry_thesis`，新候选使用当日`cabinet_entry_thesis`。
- 风险单位：保留`runner`唯一70/30协方差收缩，移除Lean二次收缩；优化器改用`w'Σw`日波动与人民币边际CE，不再把协方差当相关系数乘利润。计划内不再重复扣相关惩罚；CVaR保留为压力硬预算和披露，不再次从目标扣除。
- 漏斗/血缘/liveness：slot计数现在扣除真实持仓槽位；拒绝结果区分硬否决、无授权、非正利润、Pareto缩减、现金、单股、暴露、压力、槽位、论点硬上限、替代手数和组合支配，并进入安全决策账本；候选审计新增权威层/原因/合同。normal或bull、持仓少于软目标、无冻结且存在全部硬约束可行的正效用A/B一手提案时，空买入计划触发运行时错误。
- 阶段5赢家加仓：生命周期保存最后一次加仓日期和股数；10日后若加仓成本后LCB不正或买入论点支持衰减达到0.20，则阻止继续叠加层。亏损摊平和主动替换继续关闭。
- 阶段6退出：修复Lean此前未消费自身`scap_loss_stop=-15%`/E4的模式分支错误；`aggressive_lean`现在与专用档位一致。普通信号/论点失败仍使用既有多日确认，灾难/安全退出仍为硬退出。
- 阶段验证：新增`verify_scap_v31_golden_restore.py`，覆盖唯一档位费用、A/B/C/D、一手权、论点超限非恶化和逐提案拒绝原因；原Lean链、静态权威、动作效用、性质合同均通过。`verify_decision_council_phase_one.py`完成32日模拟、93个保存帧与最终保存并通过，证明通用治理链未被破坏。
- 上下游影响：上游为档位、滚动校准、PIT可比收益和生命周期锁定论点；中游为Lean提案、整数计划和单一风险CE；下游为订单、成交、候选审计、漏斗、监控和保存产物。历史run不回写，20日全流程将生成新run身份，不能与旧run伪作单变量结果。
- 当前状态：代码阶段实现和模块回归完成；尚待本变更后续条目记录20日从启动到保存的全流程产物、完整性检查和实际交易/严格度观测。
- 20日第一次全链发现：`run20260728_002018`完成20日、3笔买入且逐笔最低佣金5元，但成交账本的权威层为空；根因是`pending_orders.PENDING_ORDER_COLUMNS`未包含V3.1权威字段。补充固定schema、注册和静态合同后，`run20260728_003148`证明成交权威血缘完整，但同时暴露C层上限只统计当日提案、未统计既有持仓，导致跨日累积3个C层仓位和83.62%暴露。
- 严格度批判修订：原方案“C最多1只”在本窗2400个C、仅1个A、0个B的证据下会造成约30%单仓现金陷阱，确实不符合激进小资金目标；改为C最多2只，但B+C计划暴露仍不超过55%，C/B买入权威层锁入生命周期并占用以后各日预算，只有A层允许赢家加仓。该调整提高探索广度而不恢复无约束满仓。
- 最终20日验收：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1500/v3/run20260728_004239`，`COMPLETE.json=status=complete`，20交易日，最后日期2025-02-06，runtime identity=`8426e62bf43a14b858cad49f830dee1c30e94c1e58fbb632170258a78a3fc26e`。初始20,000元，最终20,736.31元（+3.6815%，仅工程观察），2笔C层一手买入，逐笔佣金5元，最终2只持仓、实际暴露56.73%（计划55%后受成交价/市值漂移影响），最低现金8,972.31元；负现金日、超过5只日、liveness失败日、权威血缘缺失均为0。
- 完整性证据：`governance_runtime_integrity_audit.csv`的成交状态、股数守恒、信号先于成交、T+1、订单唯一、账户NAV调节、持仓上限、执行暴露授权、持仓状态/评分覆盖全部通过；118个扩展帧、摘要、诊断图、manifest和完成标记均保存。研究门仍为blocked，20日没有闭合卖出，故不得把+3.68%解释为统计盈利证明。
- 最终测试：`verify_scap_v31_golden_restore.py`、Lean链、静态权威、动作效用、V2性质、Web、执行规则、实验追踪、32日决策委员会保存测试全部通过；`verify_interactive_worker_isolation.py`证明独立可见worker/失败透传，`verify_runtime_checkpoint_and_schema_v2.py`证明Ctrl+C保留非陈旧checkpoint；`git diff --check`通过。stderr仅有常量输入Spearman不可定义告警，无异常堆栈。

### CHANGE-20260728-32：修复第35日SCAP-V3.1 liveness误报

- 失败证据：用户180日运行`run20260728_071206`在第35日失败，checkpoint为`status=failed`、最后处理日期2025-02-27、runtime identity=`6d49f04cb7a7d7696df09a3c3e7a2725609c291d6c7918d07acf0511c8151ac6`。当日候选审计有180个A层、21个C层，3只既有持仓，旧liveness因61个A/B一手提案通过其近似前置检查而抛错。
- 根因：`scap_v3_lean.py`的liveness近似检查只覆盖提案毛效用、现金、槽位、单股、总暴露和压力预算，没有消费唯一优化器最终使用的协方差边际风险CE、论点硬上限、强制动作及组合替代关系。因此“单提案前置可行”被错误等同于“完整ActionPlan中的买入方案严格支配持币方案”。
- 修复：`integer_action_optimizer.py`在同一次穷举中分别记录最佳含买入方案和最佳不买方案的完整词典序目标，输出`best_feasible_buy_robust_objective`、`best_feasible_nonbuy_robust_objective`和`buy_plan_dominates_nonbuy`；不增加第二次优化器调用。liveness仅在市场/持仓前置条件成立且完整含买入方案严格支配最佳不买方案时才要求实际选中买入。
- 审计语义：保留`scap_v31_liveness_preconditions`以显示旧近似条件，新增`scap_v31_exact_buy_plan_dominance`和两类完整组合目标；这不是关闭liveness，而是把性质断言接到唯一优化器的精确可行域和目标上。
- 专项测试：`verify_scap_v31_golden_restore.py`新增高协方差场景，证明单提案人民币效用为正但协方差CE后买入组合不占优时应合法持币；专项、Lean链、V2性质、`py_compile`及`git diff --check`通过。
- 覆盖复跑：同失败配置`small_capital_lean`、E4、止损-12%、同74因子柜，从2025-01-01运行36日并保存为`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260728_072645`。`COMPLETE.json=status=complete`，成功越过原第35日并完成2025-02-28；第35日记录`liveness_preconditions=True`、`exact_buy_plan_dominance=False`、`liveness_required=False`、`liveness_pass=True`，没有吞掉真正支配关系错误。
- 复跑完整性：36日最终NAV 23,443元、3只持仓、4笔成交；负现金日和超过5只持仓日均为0。成交状态、股数守恒、信号先于成交、T+1、订单唯一、账户NAV、持仓上限、授权暴露及持仓状态/评分覆盖全部通过。该收益仅为工程复现观察，不构成正式盈利证据。

### CHANGE-20260728-33：180日结果与第99日前后仓位断链只读诊断

- 对应叶节点：WBS-07.07、WBS-08.09、WBS-08.17至08.18、WBS-10.20至10.22、WBS-11.07至11.10、WBS-14.09、WBS-14.17、WBS-16.21至16.22。本条只做证据复核和修复设计，不修改交易代码、参数或历史run。
- 复核对象：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260728_122828`，`COMPLETE.json=status=complete`，180个交易日，2025-01-02至2025-09-25，runtime identity=`8a0267d0f119ab11c78f47a80cee652cc9223482c8c1f5e30cb1d80cd9a26c2c`。该运行与此前E4/-12%/同74因子柜配置一致，但代码指纹和运行身份必须以本run为准。
- 结果概览：期末NAV 21,525.21元，账户收益+7.6261%，年化波动24.2645%，Sharpe 0.5516，最大回撤-20.3094%，平均实际仓位34.1094%。同期研究基准收益+32.2809%，账户超额-20.4713%；按有效投入资金口径收益+13.6335%，相对基准仍为-11.1011%。共7笔买入成交（含一次加仓）、5笔闭合交易、胜率40%、收益因子1.899、期末1只未平仓；样本远低于30笔准入要求，研究门与生产门均blocked，不得用正收益或PF单独证明策略有效。
- 第99日前后字段还原：用户观察的19.46%实际仓位精确对应2025-06-03（保存序列第98行；界面日序可能存在一日展示偏移）。当天安全风险为NORMAL、仓位上限85%，实际仓位19.4644%，战略期望仓位85%，真实现金比例80.5356%。保存账本写目标持仓2、实际1、缺1只，但Lean真实配置为最低持仓0、软目标4、硬上限5；runner的`profile.get("min_holdings", 2) or 2`又把合法0错误回退为2。保存账本还同时写`target_exposure=0`和`exposure_gap=65.5356%`：前者是ActionPlan的`planned_exposure`，后者是战略期望85%减实际19.46%，两字段并非同一目标口径。
- 优化器空计划会计Bug：`integer_action_optimizer._empty_plan()`把`projected_exposure`固定写为0，并把`projected_cash`写成`nav_amount * risk_exposure_ceiling`，没有继承事实`current_exposure/current_cash`。因此当天虽不是优化器漏掉可行买单，优化器仍生成了错误的“空动作后账户状态”；runner再把该值覆盖成`target_exposure`，直接制造0%目标仓位。修复时空计划必须是恒等变换：计划后持仓、现金、暴露和压力状态等于动作前事实状态。
- 实时监控Bug：`runner._build_live_monitor_state()`未发送持仓目标、缺口、`idle_cash_ratio`和`defensive_eligible_count`，Web以`|| 0`回退，因而界面错误显示目标持仓0、闲置现金0%。同时Web把`diagnostics.target_exposure`标为“目标仓位”，但Lean在runner中把它覆盖为ActionPlan计划后仓位；`exposure_gap`仍来自战略目标，形成0%目标与65.54%缺口并存。修复后页面应分别显示最低0、软目标4、硬上限5，软目标缺口3，以及真实闲置现金约80.54%，不得继续把保存账本中的错误回退值2称为配置目标。
- 非优化器漏单证据：2025-06-03/04的候选漏斗均是入场确认0、raw/structural/cash/slot/optimizer-selected均为0；ActionPlan收到的买入提案数为0。因此当天“无补仓”发生在整数仓位优化器之前，不能归因于优化器忽略了可行正效用买单。监控中的候选预览只是排序候选，不等于有交易权的候选；当前预览又未显示A/B/C/D层、人民币效用和精确拦截层，容易被误读为“有候补但优化器不买”。
- P0模块链接冲突：`mainline_v3.apply_mainline_v3_entry_policy()`先调用`attach_scap_candidate_utility()`并要求人民币效用大于0，之后runner才调用`attach_scap_v31_authority()`。`build_incremental_action_utility()`对任何非`calibrated`状态执行`incremental=min(incremental, 0)`；一旦滚动校准drift/prior-only，Pareto前置层便清空全部候选。后置C层虽按设计应使用独立PIT可比收益LCB回退，但已经没有正效用候选可进入优化器，故C层在最需要回退时失效。
- P0证据：2025-05-13至2025-09-25连续97个交易日A/B/C全部为0、约200个候选全部为D；同一窗口也连续97日raw signal为0。最后一次买入成交为2025-04-11，余下115个交易日再无买入。全180日中108日raw signal为0、108日优化器选中入场为0、54日`target_exposure=0`但`desired_exposure_target>0`。这不是正常的下跌后缓慢再平衡，而是前置效用/权限链发生长期全局熔断。
- P0校准对象错配风险：暖启动候选排序使用74个因子柜列的横截面平均排名，但`RollingEntryCalibrator`的方向检验固定计算历史`expected_return_5d`与10日实际收益的rank IC/回归斜率；A/B权限随后使用该方向检验。也就是说，因子柜负责选样本，而另一个旧预测字段负责决定整柜是否有交易权，未证明两者是同一预测对象。这会把旧预测字段的负方向错误扩散为全部74因子候选的D级全局否决。
- 错过反转的事后诊断：2025-06-03 Top10排序候选未来10日平均+4.7681%、80%为正，未来20日平均+7.3979%、100%为正；2025-06-04 Top10未来10日平均+2.5726%、70%为正，未来20日平均+5.8014%、100%为正。对所有“raw signal=0且仓位缺口>30%”日期的每日Top3，共324个重叠观察，未来10日平均+3.3129%、72.84%为正，未来20日平均+6.7438%、75.62%为正。该证据包含跨日重叠、幸存窗口和事后标签，只证明当前全局熔断错过了大量上涨路径，不能直接视作可实现收益。
- 风险层评价：180日安全状态中NORMAL 167日、HIGH 9日、WARNING 4日；97日全D冻结远长于风险状态本身。4月高风险在4月14日结束，但权限/效用链从5月13日起冻结至终点，说明“风险恢复慢”不是安全状态机滞后，而是买入校准与回退权限没有恢复通路。风险上限85%只是可用预算，不应被展示成必须满仓；但在NORMAL、现金80%、持仓不足、PIT正LCB候选存在时长期零提案不符合激进小资金定义。
- 建议修复顺序：第一，监控拆为`risk_exposure_cap`、`strategic_desired_exposure`、`optimizer_planned_exposure`、`actual_exposure`四字段，所有缺口由同口径显式计算，并把保存账本字段直接注入实时状态；第二，A/B/C/D权威判定必须先于Pareto缩减，候选人民币效用使用已选权威层的决策收益，C层不得继承A/B校准状态的非calibrated截断；第三，方向检验改为与实际因子柜预测身份一致的PIT分数/收益对，不允许用旧`expected_return_5d`否决因子柜；第四，增加“连续N日全D”“NORMAL且现金>50%、缺仓且零提案”“回退层有正LCB却raw=0”运行时告警，但不强制买入；第五，使用同一run身份做20/60/180日消融：现状、仅修监控、仅修权限顺序、再修校准对象，禁止同时放松风险上限或退出规则。
- 验收条件：静态调用图证明校准证据→权威层→层内人民币效用→Pareto→唯一整数优化器的单向顺序；性质测试证明A/B漂移时C层正PIT-LCB的一手候选仍能形成提案、负LCB仍被拒绝；监控快照与保存CSV逐字段相等；20日工程链通过后，180日中不得再出现未解释的连续20日NORMAL/高现金/缺仓/全D，且所有空买入日必须有可归因的层级拒绝分布。经济效果仍需未触碰留出期验证。
- 是否允许上线：否。当前180日结果适合定位Bug，不适合证明“小资金黄金版”恢复；在上述P0链路和监控口径修复、单变量消融及留出验证完成前，不建议合并为生产策略。

### CHANGE-20260728-34：SCAP-V3.1仓位恢复完整修改整理方案

- 对应叶节点：WBS-00.07、WBS-06.11、WBS-07.07、WBS-08.09、WBS-08.17至08.18、WBS-09.14、WBS-10.20至10.22、WBS-11.07至11.10、WBS-14.09、WBS-14.17、WBS-16.17、WBS-16.21至16.22。
- 完整方案：新增`reports/SCAP_V3_1_POSITION_RECOVERY_FULL_REMEDIATION_PLAN_20260728.md`，以`run20260728_122828`为唯一诊断基线，整合空计划会计、六层仓位、实时监控、同身份校准、A/B/C/D前置权威、C级独立回退、恢复状态机、买入软硬门、Pareto、整数优化器、补仓和赢家加仓。
- 核心纠偏：空ActionPlan必须是账户事实的恒等变换；因子柜ScoreContract必须同时支配warm-up、方向、斜率和漂移；权威层必须在效用和Pareto之前判定；C层使用独立PIT可比收益LCB，不继承A/B的非calibrated截断；不允许旧`expected_return_5d`否决整个74因子柜。
- 持仓语义纠偏：Lean明确为最低持仓0、软目标4、硬上限5；禁止runner用`or`把合法0回退成2。实时和保存账本分别输出三层数量，持仓不足按软目标计算，但软目标不构成强制购买负效用候选的命令。
- 激进边界：继续固定2万元、1,000元缓冲、5元最低佣金、5只硬上限、40%单股硬上限、90/65/35战略风险预算、T+1、PIT、E4和-12%灾难损失线；保留赢家加仓，亏损摊平和主动替换继续关闭。激进由分层正效用候选可达性和受控恢复实现，不靠强制满仓。
- 数学合同：正式拆分`risk_exposure_cap`、`strategic_desired_exposure`、`signal_supported_exposure`、`integer_feasible_exposure`、`optimizer_planned_exposure`和`actual_exposure`；所有拖累由相邻层差额计算。分层人民币增量财富为`notional × tier_return - exact_roundtrip_cost - nonduplicated_soft_CE`，协方差CE只表达组合边际风险，CVaR只作压力硬约束。
- 恢复设计：提出20/60/252独立成熟会话三尺度；连续3次负向更新撤A、连续2次非负成熟更新恢复B作为预登记起点，A/B失权期间C仍独立。参数必须通过滚动块和留出期验证，禁止在同一180日窗口反复调优。
- 实施顺序：Phase 0冻结基线；Phase 1空计划和监控；Phase 2校准对象同源；Phase 3权威前置/C回退；Phase 4快速恢复/有界软证据；Phase 5补仓、赢家加仓和优化器；之后依次做5日、Ctrl+C、checkpoint恢复、20日全链、60日恢复窗、180日B0—B6单变量消融和未触碰留出。
- 不变量验收：Phase 1不得改变任何订单、成交、现金和NAV；每阶段先做静态调用图、`py_compile`和合成性质测试，再运行产品链。最终要求空计划恒等、监控/CSV一致、漏斗单调、拒绝守恒、一次优化、现金/股数/T+1/费用/持仓上限完整通过。
- 行为验收：NORMAL且现金超过50%、持仓不足并存在正C-LCB时，不得连续10日`raw=0`；连续全D必须由同身份负校准或无正回退解释；目标0%与正仓位缺口不得再并存。平均仓位和交易数只做诊断，不设机械最低值，防止为通过测试强制交易。
- 当前动作：本条仅冻结修改方案并更新WBS，没有修改Python交易逻辑、配置、参数或历史run，没有启动新回测。
- 是否允许上线：否。必须完成Phase 0至5、20/60/180日验证和留出期准入后再评估。

### CHANGE-20260728-35：SCAP-V3.1仓位恢复模块实施与分阶段验证

- 对应叶节点：WBS-07.07、WBS-08.09、WBS-08.17至08.18、WBS-10.20至10.22、WBS-11.07至11.10、WBS-14.09、WBS-14.17、WBS-16.21至16.22。
- Phase 0：冻结`run20260728_122828`为只读诊断基线；确认解释器为Python 3.10.19；不覆盖既有结果和用户未提交修改。
- Phase 1：`integer_action_optimizer._empty_plan()`改为保持当前手数、当前权重、真实现金和真实仓位；Lean持仓合同显式拆为最低0、软目标4、硬上限5；保存账本和实时监控拆分风险上限、战略期望、优化器计划与实际仓位，并显示真实闲置现金。
- Phase 2：`RollingEntryCalibrator`的方向、斜率与漂移统一使用实际因子柜分数身份；新调度行持久化`calibration_forecast_score`和分数合同；旧内存测试历史仅在缺少新字段时使用明确标注的兼容迁移；增加三次负向锁存和两次非负更新恢复状态。
- Phase 3：A/B/C/D权限移到人民币效用和Pareto缩减之前；A/B使用校准收益，C独立使用正PIT同类因子LCB，不继承A/B的非calibrated截断；效用仍扣除精确往返费用和非重复软风险金额；Pareto并集为每个权限层保留代表候选，最终交易权仍只属于唯一整数ActionPlan优化器。
- Phase 4：保存账本、候选漏斗和实时监控增加C级正回退候选数、连续全D日数、NORMAL高现金零提案日数及5日黄色/10日红色诊断告警；告警不绕过现金、整手、T+1、单股、压力和风险上限。
- 分阶段静态/构造验证：`py_compile`通过；`verify_scap_v31_position_recovery.py`验证空计划恒等、0/4/5持仓语义和漂移状态下正PIT-LCB仍形成正人民币效用；`verify_scap_v31_golden_restore.py`、Lean链、V2性质、静态唯一权限、Web合同、执行规则和实验追踪全部通过。
- 上下游影响复核：输入数据和74因子柜未改；修改覆盖校准→权限→人民币效用→Pareto→唯一优化器→账本→实时监控链；未放松硬风险上限、T+1、整手、费用、现金缓冲、单股上限、止损或退出合同。
- 当前状态：代码阶段已通过，20交易日全流程运行与保存验收待执行；在CHANGE-20260728-36记录真实运行证据。仍不允许据此上线或宣称盈利有效。

### CHANGE-20260728-36：SCAP-V3.1仓位恢复最终20日全链验收

- 最终验收运行：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260728_223123`；固定2万元、`small_capital_lean`、`aggressive_lean`、E4、-12%灾难止损、74因子柜`pruned_run20260714_184846_581132_20260715_230524`、关闭影子组合；`COMPLETE.json=status=complete`，runtime identity=`e1e11512833d5a1a452ca66bf0eae4db4548dcbdb72d70f527a171cd697d6d7b`。
- 发现并闭环的保存层Bug：第一次完整运行`run20260728_220812`确认交易链成功，但后处理`reconcile_funnel_daily()`的固定列合同裁掉新增liveness字段；修复`candidate_funnel_audit.py`并增加保存列回归测试后，从头复跑最终运行，未回填或篡改第一次历史结果。
- 全流程结果：20个唯一交易日，2025-01-02至2025-02-06；第13日开始形成2只真实持仓；2笔买入均为filled、各100股，信号日2025-01-17、成交日2025-01-20；T+1/时序违规0，负现金日0，最低现金10,064.86元，最大持仓2只，未超过5只硬上限。
- 仓位语义验收：全部20日持仓合同均为最低0、软目标4、硬上限5；`target_exposure=0`且`desired_exposure_target>0`的矛盾行数为0；无raw提案日的`optimizer_planned_exposure`与`actual_exposure`最大绝对差为0，证明空ActionPlan保持事实账户。
- 权限与活性验收：20日累计raw/structural/cash/slot/optimizer-selected/registered-buy/executed-buy分别为3981/3391/3391/3391/2/2/2；单日C级正PIT回退候选最多201，全D最长0日，NORMAL高现金零提案最长0日，20日告警均为none；新增四个liveness字段同时存在于仓位账本和最终候选漏斗CSV。
- 完整性验收：`governance_runtime_integrity_audit.csv`共11项全部通过，覆盖成交状态、股数守恒、信号先于成交、执行时序、订单唯一、替换pair、账户NAV、持仓上限、执行权限、持仓状态和持仓评分；130个CSV全部可读取且有表头；stderr为0字节；最终回归脚本8组全部通过，`git diff --check`通过。
- 经济结果边界：期末NAV 20,223.86元，窗口收益+1.1193%，平均实际仓位19.8128%；同期研究基准+6.6737%，仍显著落后。窗口只有2笔买入、无闭合卖出，不能证明收益、补仓或退出策略有效；本次仅证明原“全D/零提案/错误0目标仓位”工程断链已修复。
- 是否允许上线：否。20日工程验收通过，但经济准入仍blocked；下一步应使用冻结代码做60日恢复窗、180日同身份对照和未触碰留出期验证，重点检查长期optimizer-selected比例、真实补仓/卖出闭环、回撤与相对基准，不得根据本20日结果继续调参后声称样本外有效。

### CHANGE-20260729-01：SCAP-V3.1 180日结果、两股集中、回撤与退出链只读审计

- 用户目标与操作边界：分析29号完成的180日运行，逐项核对A/B/C/D、整数优化器、40%单股上限、持仓广度、目标仓位、补仓、强制卖出、换手成本和巨额回撤；本条仅执行只读结果/代码/WBS审计并形成修订方案，不修改Python交易逻辑、配置、参数、历史run或数据，不启动新回测。
- 唯一诊断对象：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260728_232206`，2026-07-28启动、2026-07-29完成，180个唯一交易日，截止2025-09-25；2万元、`small_capital_lean`、`aggressive_lean`、E4、74因子柜`pruned_run20260714_184846_581132_20260715_230524`，runtime identity=`8d67e75161f890a714979ce9e2e3695dfc8b72aeea5e2729e091a166763f85ee`。
- 经济结果：期末NAV倍数0.879009，累计收益-12.0991%，年化-16.6026%，年化波动23.7446%，Sharpe=-0.6399，最大回撤-18.7463%；同期研究基准+32.2809%，基准超额-24.5745%。平均实际仓位45.4979%，但投入资金收益-26.9879%，说明失败不只是现金拖累，已投入部分本身也显著亏损。
- 两股直接约束链：180日持仓数分布为0只13日、1只5日、2只162日，从未超过2只；最大单股账户权重36.8167%，未越过40%单股硬上限，故不存在“40%被程序误当持仓数”的直接证据。真正绑定约束是`config.py`的`scap_tier_c_max_names=2`与`scap_exploration_exposure_cap=0.55`：本次候选权限累计A=1400、B=0、C=34655、D=44，A只存在于最初7日且正稳健利润提案未通过，此后可交易入口几乎全部为C；因此原本用于探索的“C最多2只”事实等价为“全组合最多2只”。WBS-08.18叶子仍写“C最多一个”，而后续变更与代码已经改为两个，文档和实现状态不一致。
- 仓位目标失效：战略期望仓位均值83.5%，实际均值45.5%，平均缺口38.05个百分点，173/180日缺口超过30个百分点；信号支持和整数可行仓位均值均为62.19%，优化器计划均值仅45.79%。WBS-08.17的软目标4只不是优化目标或部署义务，WBS-16.22又明确反对机械满仓；`integer_action_optimizer`的字典序只最大化稳健人民币利润、期望利润并最小化下行与成本，注释明确“不以多花资金作为tie-break”，没有仓位缺口惩罚、现金机会成本或广度奖励。因此页面“目标83.5%”只是预算/诊断量，并不会驱动购买达到该仓位。
- 评分到优化器的量纲扭曲：C级候选效用近似`U_i=L_i×LCB_i-Cost_i-CE_i`，其中`L_i`为一手名义金额。全部C候选中，效用与因子柜主评分Spearman相关仅0.00477，与一手所需现金相关0.72718，与可比alpha LCB相关0.62774；9笔买入的候选主排名平均约142/200。C级LCB在单日约200个候选中通常只有1至12个不同值，粗粒度LCB乘一手金额后，高价整手被系统性奖励。该问题属于WBS-07/08因子排名到WBS-10.20人民币效用的模块链接错误：绝对人民币利润适合比较“既定资本预算下的组合终值”，不适合在硬名称上限下直接充当候选优先级。
- A/B/C/D审计：A要求成熟样本、正方向与较强置信边界，B允许较短样本但限制一手/暴露，C使用独立PIT可比收益正LCB作回退，D禁止交易；设计意图本是“证据强度决定授权和尺寸”。本run中B完全缺席、A只在冷启动头部出现、C成为唯一生产入口，权限层从尺寸控制退化为全组合硬数量控制；而liveness仅检查A/B正提案，两个C持仓加大量现金不会触发失败。
- 补仓不可达：9笔买入全部以C级进入；`scap_v3_lean.py`的赢家加仓要求原始`entry_authority_tier=="A"`，C持仓即使盈利也不能加仓或晋级，因此配置显示赢家加仓开启但实际路径为零。该实现与WBS-10.18“盈利加仓独立可达”的目标冲突，也是本run没有任何add订单的直接原因。
- 回撤归因：2025-05-27账户单日约-11.97%，`sz301538`单股约-32.87%并贡献约-2539元，几乎独自造成当日损失；2025-04-07账户约-9.97%，两只创业板持仓分别约-16.54%和-20.01%，当日约48.53%总仓位的相关集中暴露共同造成冲击。当前每名压力预算为`NAV×40%单股上限×40%冲击=16% NAV`，在数学上明确容忍单股造成约16%账户压力损失；若产品不能接受约10%至12%单日回撤，则“40%单股上限+两股组合”与风险目标本身不相容。
- 退出与换手：16笔成交为9买7卖，成交名义额77,389元，总显式成本136.82元；4笔灾难止损、1笔盈利硬止盈、2笔风险降仓，显式费用不是亏损主因，主要问题是路径、集中和卖后再买。HIGH风险下仓位上限降至35%时，每只均只有100股，安全层只能整只卖出并过度降仓；代码没有风险状态滞回、无交易带或同一风险事件的再入冷却，随后又允许新C候选买入，形成“强制卖出→次日/短期补入”的事实换仓。
- 卖出反事实：四笔-12%收盘触发、下一可交易日开盘执行的灾难止损标的，在退出后20个交易日的原始价格收益分别约+30.04%、+21.03%、+0.83%、+6.55%；两笔安全降仓标的退出后20日约+11.29%、+4.79%。这是包含事后标签的描述性证据，只能证明固定阈值在该窗口明显顺周期，不能证明取消止损后的完整策略一定盈利。当前“避免损失”报告又把负贡献截为0，无法显示卖出后的错失收益，评价口径存在单边偏差。-12%只是收盘触发器，不是成交价保证；隔夜跳空使实际闭合亏损可达约-13.5%至-20.9%。
- 保留边界：继续保留唯一整数优化器作为整手、现金缓冲、T+1、交易许可、最多5只、单股硬上限、订单互斥、替换原子性和精确费用的执行可行性求解器；保留PIT时序、唯一ActionPlan、会计恒等、风险仓位上限和灾难退出接口。优化器不是应整体删除，而是不得继续同时充当因子排序器、仓位意愿生成器和C级全组合数量闸门。
- 建议消融顺序：B0冻结本run；B1仅取消C级两只硬上限并把A/B/C改为初始尺寸/折扣而非全组合名称限制；B2在B1上把绝对一手人民币效用改为单位资本净边际价值后再做全预算组合终值优化，并加入正候选容量下的软仓位缺口/现金机会成本；B3加入跨因子池/论点族的软广度奖励或槽位保留，仍不得强买负效用候选；B4把风险降仓改为滞回带、持续确认、边际风险贡献卖出和同一风险事件再入冷却；B5单独消融固定-12%止损，比较灾难阈值、波动/市场相对阈值、分段确认与利润保护；B6允许C持仓按入场后证据晋级或受控赢家加仓。每步只改一个合同，保持日期、资本、因子柜、成本、PIT和代码身份可比。
- 建议目标函数：硬约束仅保留事实不可违反项；在正边际价值候选集合中，以`max[Σ q_i L_i μ_i - TC(q) - λ_risk×CVaR(q) - λ_corr×CorrPenalty(q) - λ_gap×NAV×(E*−E(q))_+ + λ_breadth×Breadth(q)]`或等价字典序求解，其中`q_i`为整数手数，`E*=min(风险上限, 正效用且可负担容量)`；仓位缺口与广度为软项，不能绕过负收益、现金、T+1、单股和压力硬约束。候选入口必须先按独立股票池保留主排名，再把人民币终值用于组合分配，禁止以一手价格替代alpha排序。
- 验证指标：除净收益/最大回撤外，必须同时登记最差单日、平均/中位持仓数、Top1/Top2权重、实际与战略仓位缺口、闲置现金机会成本、候选主排名保持度、池/论点覆盖、换手及双边成本、风险事件卖出后再入次数、赢家捕获、profit factor、平均盈亏比和有符号卖出反事实。执行20/60/180日同身份消融后，再用未触碰留出期确认；本180日结果及本方案均不构成上线或盈利证明。
- 是否允许上线：否。本run证明工程链可运行并完整保存，但经济行为不符合“激进小资金、多池分散、目标仓位有恢复力、赢家可加仓”的合同；在C级数量闸门、目标函数、风险卖出滞回、止损与赢家晋级完成单变量消融前，不应合并为生产策略。

### CHANGE-20260729-02：SCAP-V3.2激进小资金完整修改、消融与遗漏复核方案

- 用户目标与操作边界：根据29号运行、既有SCAP报告、金融模型、数学模型和实际代码逻辑形成可施工的完整修改方案，并在方案完成后反向检查遗漏；本条只新增设计报告和WBS登记，不修改策略、配置、执行、会计、Web代码或历史run，不启动新回测。
- 对应叶节点：WBS-00.07、WBS-04.01至04.08、WBS-05.09至05.10、WBS-06.10至06.12、WBS-07.07至07.08、WBS-08.17至08.18、WBS-09.13至09.14、WBS-10.18至10.22、WBS-11.07至11.10、WBS-13.03至13.15、WBS-14.09至14.18、WBS-15.12至15.13、WBS-16.17至16.22。
- 完整方案：新增`reports/SCAP_V3_2_AGGRESSIVE_SMALL_CAPITAL_FULL_REMEDIATION_PLAN_20260729.md`，以`run20260728_232206`为诊断基线，定义20,000元、1,000元缓冲、最低0/软目标4/硬上限5、NORMAL 85%战略期望、40%单股灾难硬限、20%至25%正常软集中、允许现金、赢家加仓开启、亏损摊平和主动替换关闭的激进小资金产品合同。
- 权限纠偏：A/B/C/D只承担可靠度折扣和最大初始手数，取消C级最多两只和B+C 55%硬暴露；C保留一手起步和更高不确定性CE，但可以与其他正C共同占用最多5个总槽位；持仓保存入场权限并使用当日PIT证据计算当前权限，允许C至B至A晋级，避免赢家加仓永久不可达。
- 排序与优化纠偏：因子柜主评分按独立池/论点族保序，先使用单位资本稳健净价值消除高价整手偏置，再由唯一整数ActionPlan用绝对人民币增量终值联合分配；目标在稳健财富近优集合内软缩小正可行仓位缺口并奖励跨池广度，负边际价值候选不因缺仓或广度被强买。
- 仓位与风险纠偏：继续使用风险上限、战略期望、信号支持、整手可行、计划和实际六层仓位，定义`E*=min(risk,desired,signal,lot)`；现金机会成本仅在正可行容量存在时启用。40%只保留为灾难硬限，正常通过凸软集中、收缩协方差、CVaR、同论点和跳空/停牌/跌停压力控制单名风险。
- 退出与换手纠偏：风险状态引入持续确认、上下边界滞回、无交易带和`risk_episode_id`；同一风险事件未恢复时不得把安全卖出槽位立即补回。普通退出相对继续持有计算同期限成本后增量财富，灾难事实退出独立；固定-12%、更深灾难线、波动/市场相对确认和仅事实灾难作为互斥消融，退出反事实改为可正可负。
- 施工与消融：Phase 0至7依次覆盖冻结、合同/监控、权限拆分、池保序/高价修复、仓位/广度、风险滞回、赢家加仓/退出、保存/中断恢复；B0至B6坚持单变量推进。每阶段先WBS和静态调用图，再`py_compile`、性质测试、专项回归；之后依次5日工程、Ctrl+C、20日全链、60日恢复、180日同身份消融和未触碰留出期一次验证。
- 反向遗漏复核：方案逐项检查并闭环重新过严、机械满仓、分散稀释alpha、高价一手偏置、仓位提高导致回撤、风险卖出退化换仓、一手不可拆、加仓与槽位冲突、PIT泄漏、跨池同股重复、历史股票池幸存者偏差、企业行为价格跳变、窗口反复调参、费用重复、基准/风险状态混淆、中断恢复回归和全市场枚举资源退化；明确剩余不可消除风险包括因子柜可能无样本外alpha、整手离散、涨跌停/停牌/跳空、3至5只仍集中和样本交易数不足。
- 当前状态与上线结论：`SCAP-V3.2-aggressive-small-capital-proposed`仅为完整设计提案。当前未实施、未回测、不得覆盖V3.1身份、不得合并为生产策略或宣称盈利/黄金版恢复。

### CHANGE-20260729-03：SCAP-V3.2全模块实施、缺陷闭环与180日全链验收

- 用户授权与目标：按CHANGE-20260729-02完整方案实施全部模块；每阶段执行静态代码审查和bug测试；最终运行2025年起180交易日窗口，从特征加载、PIT/预热、逐日决策、整数ActionPlan、订单执行、持仓生命周期到账本/报告/工作簿保存全流程验证，并分析结果。
- 对应叶节点：WBS-00.07、WBS-04.01至04.08、WBS-05.09至05.10、WBS-06.10至06.12、WBS-07.07至07.08、WBS-08.17至08.18、WBS-09.13至09.14、WBS-10.18至10.22、WBS-11.07至11.10、WBS-13.03至13.15、WBS-14.09至14.18、WBS-15.12至15.13、WBS-16.17至16.22。
- 实施身份：`small_capital_aggressive_profit_v3_2`、`scap_v3_2_contracts_v1`、`aggressive_lean`、E4、20,000元、1,000元现金缓冲、100股整手、最少0/软目标4/硬上限5、NORMAL目标85%、单名25%软上限/40%硬上限、赢家加仓开启、亏损摊平与主动替换关闭。
- 配置/合同层：`config.py`和`scap_v2_contracts.py`新增V3.2产品、成本、候选池、权限折扣、仓位缺口、广度、集中度、风险episode和退出字段；A/B/C/D改为证据折扣和初始手数控制，不再用C级形成两股或55%全组合硬上限。
- 候选/评分层：`scap_v3_lean.py`按`cabinet_entry_thesis`保存独立池主评分和排名，跨池同股去重但保留memberships；`ActionProposal`登记pool、primary score/rank、单位资本稳健回报和权限惩罚，Pareto约简不再由一手绝对价格替代因子排序。
- 优化/仓位层：`integer_action_optimizer.py`保留唯一整数ActionPlan；整手、现金、T+1、最多5名、40%单名、压力预算和交易许可为硬约束；只在正权限折扣后稳健收益集合中使用部署缺口、广度、25%凸集中惩罚和收缩协方差风险软项；空计划保持事实持仓、现金和暴露。
- 风险/退出/补仓层：`position_lifecycle.py`、`small_capital_aggressive.py`、`scap_v3_lean.py`与授权链加入-18%自适应灾难底线、两日确认、较早利润保护、1.5%安全无交易带、风险持续确认、3日重入冷却和可正可负卖出反事实；C持仓可凭真实持有期证据生成B尺寸赢家补仓，亏损加仓和替换保持关闭。
- 执行/会计/保存层：`pending_orders.py`、`retail_execution.py`、`execution_runtime.py`、`functions/execution/*`与`runner.py`统一真实费用身份、计划/proposal/现金预留lineage、下一交易日成交和账户对账；候选分块读取使用`low_memory=False`消除dtype警告；console/checkpoint/失败窗口/键盘中断能力保留。
- 运行期缺陷1：满5名组合的事实退出未在同一ActionPlan释放槽位，引发漏斗非单调。新增`_available_slots_after_exits`，完整退出在原子计划内释放一个名称槽。
- 运行期缺陷2：2025-04-29已持有`sz300899`但无当日特征行，运行完整性缺少持仓状态。新增`_carried_unobserved_position_states`，沿用最近已知估值并登记`carried_forward_missing_current_feature`、来源日期和估值来源，同时禁止陈旧状态生成交易。
- 运行期缺陷3：生命周期允许加仓后，提案层又重复要求A/B，且`add_layer=2`被误当第二次加仓、`position_unrealized_return`未被读取，造成赢家加仓事实不可达。删除重复权限门槛，统一层编号为`add_layer-2`并按`net_unrealized_return→position_unrealized_return→unrealized_return`读取。
- 槽位补充验证：新增“满5名时对已有名称加仓不消耗第六槽位”性质测试；目标手数从1增至2、活跃名称仍为5。
- 25日链路证明：`run20260729_114214`完成25日、stderr 0；相对补仓字段修复前，相同前25日新增5个winner-add提案，证明真实生产候选链已接通，但该短窗未选择补仓，不作为经济证据。
- 最终运行身份：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260729_115619`；2025-01-02至2025-09-25，180日，74因子柜`pruned_run20260714_184846_581132_20260715_230524`，runtime identity=`82c7f08d95d0c9092d23a43ece7f0081097960c76f24284adb03d6055dfc3719`，影子组合关闭。
- 全链证据：checkpoint与`COMPLETE.json`均为complete，stderr 0字节；130个CSV全部可读并有表头；180日唯一；NAV独立重建最大误差0；仓位/持仓数有界；21个入选买单及成交lineage完整；无无限数值；持仓逐因子Excel成功保存；`git diff --check`通过。
- 回归证据：`verify_scap_v32_aggressive_contracts.py`9项、Lean chain 12项、静态单一权限6项、V3.1恢复4项、add可达7项、持仓硬上限、候选漏斗、流式汇总、输出韧性、执行规则和退出合同全部通过；180日`verify_scap_fullchain_run_v2.py`与运行完整性审计通过。
- 经济结果：最终净值1.296451、累计+29.6451%、年化+44.1254%、波动28.6507%、Sharpe 1.4242、最大回撤-18.2957%、平均实际仓位75.5322%、投入资金收益+44.8544%、闭合14笔、胜率71.43%、PF 1.4576、显式成本255.57元；同期研究基准+32.2809%，几何终值相对基准-1.9926%。
- 激进小资金行为验收：持仓分布0/2/3/4/5名分别13/4/1/28/134日；预热后平均实际仓位81.4120%、相对85%目标平均缺口3.9350个百分点，167日中134日为5名，故不再属于“长期两股、目标不驱动部署”的过严版本。
- 第99日复核：2025-06-04 desired=85%、executable=85%、actual=75.4888%、缺口9.5112%、持仓5名、目标4名、不足0、合格候选15；未catch-up原因为`gap_below_trigger`，不再存在“目标0但缺口很大”的字段/逻辑矛盾。
- 补仓与回撤：真实执行2次winner-add；`sz301300`加仓后于安全退出闭合亏损394.94元，`sz300899`加仓后期末200股未实现盈利1,501.01元。2025-04-07账户单日-13.8506%，五名共同下跌；`sz301300`前一日账户权重29.87%、当日-16.66%、贡献-4.98个百分点，其中新增一手诊断约增加2.49个百分点损失。名称分散达到5只仍未消除共同风格跳跌。
- 退出反事实：9笔利润硬止盈已实现+3,119.76元且signed benefit为正；2笔安全降仓已实现-95.28元，到后续20日末signed benefit=-1,966.79元，表明安全卖出仍有反弹机会成本，必须通过冻结参数后的隔离消融验证，不能在本窗口继续追涨调参。
- 对比边界：旧`run20260728_232206`与V3.2同时改变权限、候选、目标函数、风险和退出，只能作综合诊断；补仓字段接通前`run20260729_103208`的+43.35%与最终+29.65%主要由winner-add可达造成路径分叉，可作强诊断但不是独立样本外因果证明。
- 结果报告：`reports/SCAP_V3_2_180D_RESULT_ANALYSIS_20260729.md`记录完整模块映射、公式、缺陷、验证、仓位、回撤、补仓、退出、比较边界和遗漏复核。
- 最终状态：工程全链验收通过，激进小资金仓位与广度行为恢复；但相对基准为负、闭合交易少于30、买卖期望/单名风险贡献/利润回吐等研究矩阵仍有失败，PIT公司行为、税务、可投资基准、独立复核与正式复现包不完整。`research_gate_status=blocked`，禁止上线。

### CHANGE-20260729-04：SCAP-V3.2“次黄金版本”GitHub分支固化与主干合并

- 用户授权：把当前完成180日全链验收的代码作为“次黄金版本”建立独立GitHub分支、提交并推送，然后合并至远端主干。
- 发布分支：`codex/scap-v32-secondary-golden-20260729`；目标主干：`main`；远端：`origin`。
- 发布范围：全部当前已跟踪源码修改、`functions/decision_council/scap_v31_authority.py`、V3.1/V3.2专项验证脚本、V3.1/V3.2正式模型/修复/结果报告以及本WBS。
- 明确排除：未跟踪的`codex_smoke_*`目录、临时验证目录、stdout/stderr运行日志、长路径测试目录及其他历史临时产物；这些文件不属于可维护源码快照，不得使用`git add -A`误上传。
- 合并门槛：沿用CHANGE-20260729-03的180日全链验证和跨模块回归证据；提交前再次执行`git diff --check`并核对暂存文件清单，推送分支后以非快进合并或等价可审计方式合并`main`并推送。
- 版本语义：“次黄金版本”只表示当前工程恢复节点的源码标签，不改变`research_gate_status=blocked`、禁止上线和不得宣称样本外盈利的结论。
- 实际发布证据：版本提交`faaad58e8498698484b6202616f5d5c24464f865`已推送至`origin/codex/scap-v32-secondary-golden-20260729`；GitHub PR #7（`https://github.com/ZiyiiiiiiiiiiiiiiiiiiiiiiiiiiiZiyi/tdx_modular_quant_project_v2_all_instruments/pull/7`）状态为MERGED；远端`main`合并提交为`db2ed82b33fb8fa7ae0ae06cc76d4d1895994f10`，且已验证`faaad58`为该主干提交祖先；版本分支保留，未删除。

### CHANGE-20260729-05：29日180日全输出审计、治理日期预检纠偏与启动页产品合同修正

- 用户问题：逐项分析29日最终运行全部输出，从模块、代码逻辑、金融公式和数学公式判断正负影响；同时解释并处理启动页请求`2024-01`至`2026-05`时的`pit_membership_coverage_outside_requested_window`阻止。
- 对应WBS影响链：WBS-00运行身份与变更控制 → WBS-02 PIT/可投资宇宙 → WBS-04因子柜与角色 → WBS-05入口确认 → WBS-07仓位授权 → WBS-08整数ActionPlan → WBS-09风险/协方差 → WBS-10退出/补仓 → WBS-11执行费用 → WBS-13研究门/失败实验室 → WBS-14归因/基准 → WBS-15 Web预检与产品展示 → WBS-16保存/完整性。日期修复只改变Web任务准入，不改变历史run的评分、成交、账户或报告数值。
- 最终run事实：继续以`run20260729_115619`为唯一审计对象；2025-01-02至2025-09-25、180日、2万元、74因子固定柜、`runtime_identity=82c7f08d95d0c9092d23a43ece7f0081097960c76f24284adb03d6055dfc3719`。130个CSV均可读有表头；空表被明确区分为不适用、未触发或证据缺失，不把“文件存在”当作统计证据。
- 综合判断：工程全链为正；预热后81.41%平均仓位、134/167日5名持仓证明长期两股和目标仓位0问题已修复；绝对收益+29.65%为正，但对预登记Top-100月调基准的几何终值相对收益-1.99%为负；最大回撤-18.30%、入口角色边际、因子数值冗余、亏损/安全退出反弹机会成本、风险报表断链和正式PIT/过拟合门为负。
- 数学口径缺陷：研究门按样本数加权得到10日买入期望+1.7706%，验证矩阵对18笔普通买入组与2笔赢家加仓组做分组等权后得到-1.5030%；后者不是总体逐笔期望。`benchmark_excess_return=-10.8351%`是逐日算术主动收益复利，几何终值相对收益为`1.296451/1.322809-1=-1.9926%`；两者必须分名展示。此记录只标记后续修正要求，本次不改历史报告公式。
- 风险根因：2025-04-07五名持仓共同下跌造成账户-13.8506%，不是两股集中或单一股票40%超限；5只名称没有消除共同小盘/反转风格暴露。协方差增量惩罚对2万元账户金额较弱，且旧`risk_contribution_ledger`未完整展示V3.2优化器实际使用的收缩协方差，后续必须统一事前/事后风险账本。
- 日期阻止根因：特征覆盖2018-01-02至2026-06-05，2026-05有效截止正确归一为2026-05-29；A500 PIT成员manifest只覆盖2025-01-02至2026-05-29。旧`main_launcher_web._governance_preflight()`无视宇宙身份，无条件要求A500成员覆盖，错误阻止`all_a_share_research`的2024起点；runner本来只在`require_constituents and not allow_fallback`时消费该输入。
- 日期修复：Web预检现在从`universe_registry`读取所选宇宙合同，仅严格指数成员宇宙校验PIT成员时间覆盖；全A研究、ETF研究及允许fallback宇宙返回`constituent_status=not_required`。这没有倒填2024年A500成员；严格A500请求2024起点仍正确阻止。
- 启动页合同修正：发现页面错误显示“主动换仓已开启”，而`small_capital_lean`实际为主动换仓关闭、亏损摊平关闭、赢家加仓开启。页面改成只读展示真实资金档案；只修正说明，不改变交易参数和29日结果。
- 参数解释边界：`monthly_ml_weight_cap=0.20`只对`mainline_v3_monthly_lgbm_hybrid`生效；29日最终run为`mainline_v3_cabinet_native`，8个monthly-LGBM表为仅表头、不适用。快速因子审判7000不直接改变本次治理回测。`research_max_runtime_seconds=1800000`若按秒解释约20.83天；30分钟应使用1800。
- 验证证据：`C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe --version`为3.10.19；`py_compile main_launcher_web.py verify_web_governance_preflight.py verify_scap_web_contract.py`通过；`verify_web_governance_preflight.py`验证全A 2024-01至2026-05通过、严格A500同窗口阻止、严格A500短截断窗口通过；`verify_pit_membership_manifest_coverage.py`通过；`verify_scap_web_contract.py`验证产品合同展示；`git diff --check`通过。
- 完整报告：`reports/SCAP_V3_2_180D_ALL_OUTPUT_AUDIT_AND_DATE_FIX_20260729.md`记录绩效、仓位、优化器、权限、候选漏斗、因子、消融、补仓、退出、回撤、费用、PIT、研究门、130个CSV分类、启动页参数和日期修复。
- 当前状态：日期预检误阻止已修复；严格指数的真实历史缺口仍被保护。29日工程与激进小资金行为基本通过，但风险分散、相对基准、退出质量、正式PIT、过拟合和冲击校准仍失败，继续`research_gate_status=blocked`并禁止上线。

### CHANGE-20260729-06：SCAP-V3.2批判性模块复核与下一阶段完整提升计划（仅分析，不改代码）

- 用户边界：从模块、代码逻辑、金融公式和数学公式逐项判断正负影响，形成下一阶段完整提升方案；本阶段禁止修改策略、参数和执行代码。
- 本次操作：只读核对`config.py`、`scap_v3_lean.py`、`scap_v31_authority.py`、`small_capital_aggressive.py`、`position_lifecycle.py`、`integer_action_optimizer.py`、`exposure_catchup.py`、`quality_reports.py`、`runner_summary.py`及`run20260729_115619`既有输出；只新增分析文档和本WBS记录，未改交易代码、未运行回测。
- WBS影响链：WBS-00冻结身份 → WBS-02时间/PIT → WBS-04因子经验去冗余 → WBS-05入口角色消融 → WBS-06 A/B/C/D连续可信度 → WBS-07唯一仓位状态机与catch-up → WBS-08整数ActionPlan/广度 → WBS-09协方差/压力风险 → WBS-10补仓/退出 → WBS-11费用容量 → WBS-13研究门/过拟合 → WBS-14基准与指标 → WBS-16全链验收。
- 总体复核：当前版本不是过度保守版；预热后平均仓位81.41%、134/167日持有5只，工程和激进小资金行为为正。主要负面已经转为因子数值冗余、入口角色负边际、共同风格风险、亏损/安全退出反弹机会成本、研究报表公式冲突和正式PIT/过拟合证据不足。
- 新发现1（广度目标错位）：整数优化器的广度为`min(active_symbols,4)+min(active_pools,3)`，而产品硬上限为5只；第5只股票和第4个及更多池不增加广度奖励。它不是两股硬限制，但在近似稳健价值方案之间会偏向4只/3池，后续应在近最优正净价值集合内对齐5只和至少3个经验簇，禁止用广度复活负净价值。
- 新发现2（止损边界语义）：当前自适应亏损线为`min(-18%, -(12%+8%*tail))`；当`tail<=0.75`时结果固定为-18%，当尾部风险更高时反而可能放宽到-20%。因此大部分区间并不自适应，且尾部风险方向可疑；再叠加2日确认可能放大急跌后的卖低。后续必须拆分立即灾难线、波动软线和尾部风险组合降仓，利润硬止盈作为正面对照保留。
- 新发现3（权限与目标函数）：B级权限180日为0；A使用`point-0.50SE`、B使用`point-0.25SE`，不确定性折扣的等级单调性不直观。建议先审计状态不可达原因，再比较连续可信度LCB，等级仅控制初始手数。优化器同时存在30%以上局部集中惩罚和25%以上组合集中惩罚，后续需统一量纲；Pareto约简24个候选必须保存支配证据。
- 新发现4（测量冲突）：买入总体期望在研究门使用样本数加权+1.7706%，验证矩阵使用reason组等权-1.5030%；终值几何相对基准-1.9926%与逐日算术主动收益复利-10.8351%也被相近字段名混用。第一阶段必须只修测量语义，不能带交易改动。
- 完整施工顺序：Phase 0测量/风险账本 → Phase 1因子经验簇去冗余 → Phase 2入口角色消融 → Phase 3权限连续化 → Phase 4广度/优化器 → Phase 5协方差/压力风险 → Phase 6 catch-up → Phase 7退出 → Phase 8赢家加仓 → Phase 9可选月度ML → Phase 10未触碰留出验收。每阶段保持单变量，依次静态调用图、语法、性质、20日工程窗、180日同身份配对、多窗口/成本压力和一次性留出。
- 小资金预登记建议：NORMAL希望仓位85%、允许78%至87%的平均验收区间；中位持仓4至5只、5只日占比至少65%；1,000元现金缓冲、40%单名硬上限、25%单名软目标、Top-2软目标55%、单经验簇软目标45%；无正净价值时允许现金；主动替换和亏损摊平继续关闭。
- 经济/风险门建议：Top-100几何终值相对收益为正、60日滚动胜率至少55%、最大回撤不高于20%且目标16%至18%、PF至少1.30、闭合交易至少30；普通买入与赢家加仓分开计算；亏损/安全退出signed benefit不得系统性为负；有效单名风险贡献不高于35%、共同小盘压力损失不高于10%至12%。
- 反向遗漏复核：方案不会用强制5只或机械满仓恢复激进度；风险改造针对共同风格而非全面降仓；主动换仓继续关闭；已覆盖整手、最低佣金、缓冲、高价不可买、T+1、涨跌停、停牌、印花税和非线性费用。最大剩余风险为交易样本不足、2025开发窗反复使用、因子选择过拟合、2026是否仍属未触碰留出不确定和正式PIT不完整。
- 完整方案：`reports/SCAP_V3_2_CRITICAL_MODULE_AUDIT_AND_IMPROVEMENT_PLAN_20260729.md`。
- 当前状态：方案已完成并做反向过严/机械满仓/高换手/小资金遗漏检查；本阶段没有实施授权，所有交易代码和参数保持不变，`research_gate_status=blocked`与禁止上线结论不变。

### CHANGE-20260729-07：持仓上限非永久5只的资本规模自适应重审（仅分析，不改代码）

- 用户纠偏：不会永久只使用5只股票上限；要求重新从模块、代码逻辑、金融公式和数学公式审计正负影响，并给出能够适配未来不同资金规模的完整提升方案。本阶段禁止修改代码。
- 本次操作：只读审计启动页资金覆盖、`BACKTEST_CAPITAL_PROFILES`、runner的`top_n`/holding target、候选池、A/B/C/D手数、整数优化器组合枚举、广度、Top-5风险、有效持仓数、市场状态、catch-up、执行费用和ML诊断；只新增方案文档和本WBS记录，未修改策略/参数/执行代码，未运行回测。
- 核心纠正：29日`max_positions=5`只属于2万元固定run身份；预热后134/167日持有5只证明旧两股限制已解除，但不能证明5只是经济最优，也不能外推到10万、100万或1000万。上一记录中“4至5只、5只日占比65%”只保留为当前2万元固定5只专项验收，不再作为永久产品门。
- 启动页/身份缺陷：页面初始资金和最多持仓显式默认20,000/5，切换100万或1000万档案时没有发现同步清空覆盖值的处理；`0=不限制`在配置层转为`None`，mainline runner又可能回落到`GOVERNANCE_DEFAULT_TOP_N=20`。未来必须分离`user_position_cap`、`economic_position_cap`、`risk_position_cap/floor`和`search_position_cap`，计算上限不得冒充金融上限。
- 内生持仓数模型：引入整数手`q_i`和名称变量`y_i`，`K=sum(y_i)`由成本后稳健alpha、固定佣金、整手、流动性容量、风险降低和运营成本共同决定；只在新增名称的`ΔJ=LCB价值-固定成本+风险降低-运营成本>0`时扩展。用户上限为空时不参与约束，不能暗回5或20。
- 资金/费用规模化：可投资预算为`A=NAV*E_risk-B_cash`；现金缓冲应为绝对底线、NAV比例、pending费用和压力保证金的最大值；候选除一手可买外还需满足最低佣金占比形成的经济最小订单。实际持仓数不要求随资金机械单调，但同候选/同风险下提高现金不能缩小可行解集合。
- 单名上限规模化：当前25%软/40%硬在2万元、5只附近有解释，但对20只大组合过松。建议按`w_equal=E/K*`定义`w_soft=min(abs_soft,γ_s*w_equal)`、`w_hard=min(abs_disaster,γ_h*w_equal)`；若一手权重超过硬线则该股票对该资金规模不可买，不为其放宽整个组合。
- 广度/股票池缺陷：当前`min(active_symbols,4)+min(active_pools,3)`不奖励第5只及更多名称/第4个及更多池；每池Top-M=8、每thesis硬上限3、优化器候选24也只适配小K。未来在财富目标的epsilon近最优集合中最大化`N_eff/K`、归一熵和独立经验簇比例；候选预算与每论点数量按可行K和池数缩放，保留每池代表。
- 权限规模缺陷：A/B/C最大2/1/1手只适配微型账户；大账户会严重低仓，高价股一手又可能过大。权限应输出资本/风险尺寸倍率，基础手数由目标权重、ADV容量、风险预算和一手资金计算；B级不可达问题继续作为独立诊断。
- 求解器规模缺陷：当前对最多24候选枚举`sum(C(M,k))`；K=5约5.5万组合尚可，K接近20时趋近`2^24`，不能靠提高max_positions扩容。方案规定小K保留精确枚举，中K使用MILP/MIQP/branch-and-bound，大K使用连续风险优化、整手投影和局部交换，并保存最优性gap；求解资源身份与金融产品身份分列。
- 风险/报告规模缺陷：Top-5权重在5只组合中等于总股票仓位，在20只组合中才代表头部；catch-up的“Top-5风险>80%且风险股票少于8”与5只档案天然冲突；`effective_n_required=min(global 5,max_positions)`令大组合仍只要求5。未来以`N_eff/K`、风险HHI、头部20%权重/风险贡献和经验簇压力作为主门，Top-1/3/5只保留描述用途。
- 市场状态纠偏：现有bull/rebound/neutral/weak/bear/crisis定义25/25/20/16/15/8个最大持仓，但mainline V3未显式覆盖时使用默认Top-20。未来市场状态调整风险预算、仓位和alpha门槛，不直接固定K；危机不能通过减少名称机械提高集中度。
- 补仓/退出/再平衡规模化：赢家加仓按剩余单名、簇风险和现金预算计算手数，不用固定绝对手数；自适应亏损线负号/`min`问题继续列为高优先级；微型账户可关闭主动替换，但资金扩大后的维护再平衡必须与机会换仓分开，按组合换手预算和成本后边际收益决定，不永久沿用“每日一对/零对”常数。
- 多资本消融：未来固定同一因子柜、PIT、日期、信号和成本身份，对20k/50k/100k/500k/1m/10m分别运行自动K，并以固定5/10/20/30作对照；比较终值、几何相对基准、回撤、压力损失、实际/有效K、标准化分散、费用冲击、容量、未使用正alpha、求解时间和最优性gap。固定K只作因果对照，不作推荐值。
- 实施顺序：Phase 0身份/界面语义 → Phase 1规模无关报表 → Phase 2可扩展求解器 → Phase 3内生K/动态单名上限 → Phase 4候选池规模化 → Phase 5因子去冗余 → Phase 6入口/权限 → Phase 7风险/状态 → Phase 8 catch-up/补仓/维护再平衡 → Phase 9退出 → Phase 10 ML → Phase 11多资本全链验收。
- 通用硬门：无杠杆、现金/整手可行、不可交易不得成交、负成本后稳健价值不得由缺仓复活、用户明确上限不得突破、单名灾难/组合压力边界和完整lineage；永久门中明确删除“永远5只、软目标4、Top-5≤80%、至少8个风险股票、A/B/C=2/1/1手、每论点3只、候选24”。
- 完整方案：`reports/SCAP_CAPITAL_SCALABLE_MODULE_AUDIT_AND_PLAN_20260729.md`。
- 当前状态：已完成资本规模扩展性反向审查；当前2万元5只run保留为固定基线，未来主模型建议自动K并允许可选用户护栏。本阶段未实施任何交易代码改动，`research_gate_status=blocked`与禁止上线结论不变。

### CHANGE-20260729-08：资本规模自适应全模块实施与20日全链验收（已完成）

- 用户授权：实施CHANGE-20260729-07的全部资本规模自适应模块；每个模块完成后进行静态代码契约审查和专项bug测试；最终运行20日小窗口，从特征加载、PIT/预热、候选、决策、整数计划、订单、T+1成交、费用、账户到全部保存产物进行全链验证。
- 冻结基线：分支`main`，起始HEAD=`7c7850347f19ca99f9698590bc48cca5ca7bd2d4`；保留此前日期预检和Web合同的未提交修改以及全部用户/历史未跟踪产物，不执行批量删除或覆盖。
- 实施影响链：WBS-00身份/变更控制 → WBS-04因子/候选规模 → WBS-05入口 → WBS-06权限尺寸 → WBS-07动态仓位/持仓数 → WBS-08可扩展整数优化器 → WBS-09规模无关风险 → WBS-10补仓/退出/再平衡 → WBS-11费用/容量 → WBS-13规模化研究门 → WBS-14报告指标 → WBS-15启动页覆盖语义 → WBS-16全链保存。
- 阶段门：每阶段先检查调用图和字段单调性，再`py_compile`、专项性质/回归脚本；只有当前阶段通过才进入下一阶段。最终20日运行不得替代多资本经济验证，只证明新架构从开始到保存可运行。
- 当前状态：代码实施与20日工程验收已完成；尚未形成跨资本规模或长期经济结论，旧`run20260729_115619`继续作为2万元固定5只基线。
- Phase 1身份/界面完成：新增`capital_scaling.py`纯合同，分离`fixed/auto`、配置上限、经济上限与搜索上限；机构档案默认auto，当前三个2万元档案继续fixed=5以保留基线；用户覆盖0登记为`posauto`。启动页资金/持仓覆盖默认留空，0改为“资金/整手/成本自动上限”，不再宣称无限。
- Phase 1静态/测试证据：`py_compile config.py main_launcher_web.py capital_scaling.py verify_capital_scaling_contract.py`通过；专项测试验证固定5基线、0→auto、提高现金不缩小经济可行上限、5→20时动态单名软硬上限下降、候选预算随K增加、Web无20,000/5残留覆盖；既有`verify_scap_web_contract.py`通过；`git diff --check`通过。
- Phase 2候选/权限/尺寸完成：runner逐日生成`PositionCapacity`，fixed档案保留原上限，auto档案按当前持仓、可用现金、安全仓位、一手金额、最低佣金经济订单和独立搜索上限得到当日`effective_position_cap`；当前持仓永不因现金不足被自动上限倒逼成非法状态。auto模式单名软/硬上限按`E/K`缩放；A/B/C最大初始手数按目标资本与一手金额乘1.00/0.60/0.35倍率，fixed模式保留2/1/1；SCAP提案、两次入口策略和DecisionContext消费同一日K/单名上限。
- Phase 2静态/测试证据：`py_compile runner.py scap_v31_authority.py scap_v3_lean.py capital_scaling.py`通过；`verify_capital_scaling_contract.py`新增固定2手与auto目标资本20手性质；`verify_scap_v31_golden_restore.py`和`verify_scap_v32_aggressive_contracts.py`全部通过。
- Phase 3优化器/广度完成：K<=8且约简候选<=24继续精确穷举并声明`optimal_bounded_exhaustive`；更大K使用有界beam搜索，替换买卖对作为原子unit，声明`feasible_bounded_beam_search`并记录beam宽度/候选数/是否证明最优。广度删除固定4名/3池，改为名称容量比例、股票权重`N_eff/K`、独立池比例和归一熵之和。
- Phase 3静态/测试证据：`verify_scalable_optimizer_contract.py`验证12名/20候选走有界求解、5名走精确求解、均衡多池广度高于集中组合；V3.2既有9项性质回归通过；旧广度常数7.0的测试更新为新固定5只场景归一值3.8；`git diff --check`通过。
- Phase 4规模无关风险/补仓/退出完成：协方差目标组合新增风险`N_eff/K`、风险HHI、头部20%风险贡献；删除“Top-5风险>80%且少于8只”固定门，改用最大单名风险、风险`N_eff/K>=0.55`和头部20%风险贡献不高于55%的规模归一门。持仓账本新增袖套`N_eff/K`、HHI、头部20%袖套/账户权重；研究门不再让现金扭曲证券分散度，也不再以大组合最低5只或Top-5总股票仓位作通过条件。
- Phase 4补仓/权限/退出公式：catch-up直接消费上一决策的规模归一风险形状，健康的10/20只组合不因绝对持仓数被误杀；A档不确定性折扣改为`point-0.25SE`、B档改为`point-0.50SE`，恢复证据等级单调性；亏损控制拆为高尾部风险时由-16%向-12%收紧且需2日确认的软线，以及固定-18%当日立即执行的灾难线，不再使用会把高尾部风险放宽到-20%的反向`min`。
- Phase 4静态/测试证据：相关8个模块`py_compile`与`git diff --check`通过；新增`verify_capital_scaled_risk_and_exit_contract.py`验证均衡10名、集中组合修复/拦截、绝对K无关catch-up、袖套有效N研究门、自适应软止损方向、灾难线不被放宽及A/B证据折扣单调性，全部通过。既有`verify_scap_stage1_exposure.py`、`verify_governance_v3_lifecycle_math.py`、`verify_lifecycle_alert_semantics.py`、`verify_scap_v3_lean_static_authority.py`、`verify_scap_v31_golden_restore.py`通过；`verify_risk_monitoring_outputs.py`因工作区缺少`low_vol`历史结果、`verify_data_quality_reports.py`因本次运行ID尚未生成数据质量报告而失败，均为外部产物前置条件，不是本阶段公式断言失败，留待20日全链产物后复测。
- Phase 5因子/补仓/产品输出完成：柜内评分在同一决策日截面上按角色计算绝对Spearman相关，语义近亲必合并、观测不少于30且绝对相关不低于0.90的跨家族同质因子合并为经验簇；先簇内中位数、再家族平权，落盘原始因子数、经验簇数和压缩比，禁止74个数值近重复因子重复投票。该聚类只消费当日可见横截面，不使用未来收益或未来日期。
- Phase 5赢家加仓/动态边界：赢家加仓不再固定一手，申请手数为剩余动态单名硬上限、扣除现金缓冲后的可用现金、当前A/B权限手数三者最小值；生命周期、风险罚分和ActionPlan使用同一个当日动态单名上限。catch-up缺口触发从固定比例改为`min(预登记10%, max(代表性一手权重,1%))`，大资金的一手很小时不再必须等待10个百分点缺口；微型账户仍保留原10%保护。
- Phase 5报告/Web：研究准入删除固定Top-5≤80%与含现金账户有效N主门，改为袖套`N_eff/K>=0.65`、头部20%袖套权重≤55%并保留Top-1账户硬线；摘要和实时监控新增头部20%权重/风险、袖套/风险`N_eff/K`与HHI，Top-5明确标记为描述项。月度ML仍按预登记保持关闭/影子状态，本阶段不在基础链尚未形成经济证据时暗中接入或调高0.20上限。
- Phase 5静态/回归证据：21个受影响文件`py_compile`及`git diff --check`通过；新增经验簇专项测试证明跨家族完全重复因子由3压缩为2且删除重复因子不改变评分；赢家补仓专项证明在60%单名上限、15%一手、15%已有仓位时申请3手而不是永久1手。资本缩放、求解器、风险退出、柜语义、V3.1黄金恢复、V3.2激进合同、主线V3、统一效用、组合优化、补仓可达、退出仲裁、执行规则、Web合同和日期预检共16组脚本全部退出0。
- Phase 6运行过程与故障归因：首次20日进程`run20260729_220448`在第2日出现`OSError: Invalid argument`；3日复现`run20260729_221054`完成全部交易日后在保存时出现同一错误。两次均发生在外层工具超时关闭标准输出句柄后，策略日循环、账户和订单断言没有失败。最终改用独立Windows进程并显式重定向stdout/stderr，不改策略代码；`run20260729_221623`完成20日和165项保存，随后内容审计发现经验聚类字段未从日诊断传递到结果表，以及固定`Top1 account <=25%`会把四只近等权组合的25.29%误判为失败。修复为显式落盘经验簇字段，并把Top1改为描述项，由`N_eff/K`和头部20%袖套权重承担规模归一化门禁。
- Phase 6最终20日全链目录：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260729_224418`；运行身份哈希`a95565edcdcbc09dec74bed2a3a92898386efdb42bd3506a7af1dba87fee960f`，窗口2025-01-02至2025-02-06共20个交易日，checkpoint、`COMPLETE.json`和artifact manifest均为`complete`，进程正常退出，stderr=0，共165个文件。
- Phase 6交易/账户结果：初始NAV 20,000元，最终NAV 20,439.237541元，窗口成本后收益+2.196188%；目标仓位85%，最终实际仓位84.460098%，ActionPlan目标4只、实际4只、现金3,176.237541元。2025-01-20产生计划、2025-01-21按T+1成交4笔各100股买单，四笔均`filled`；账户独立重建20/20通过，最大调节误差0；运行完整性11/11通过；组合约束20/20通过。
- Phase 6规模归一化与因子证据：最终袖套`N_eff=3.946167`、`N_eff/K=0.986542`、头部20%袖套权重0.299484；Top1账户权重0.252945仅作描述，不再以固定25%误杀。每日原始因子数74，经验簇数随当日截面在26至34之间，最终28簇、压缩比0.378378；20行日结果与20行配置/分配账本均非空落盘该字段。
- Phase 6保存层验收：137个CSV逐文件`Import-Csv`失败0；12个JSON逐文件解析失败0；1个XLSX可作为OOXML ZIP打开且含38个条目；零字节文件0。最终stdout/stderr分别为`reports/capital_scalable_20d_final_stdout_20260729.txt`和`reports/capital_scalable_20d_final_stderr_20260729.txt`。
- Phase 6研究结论边界：研究总闸门仍为`blocked`，阻断项包括原始因子柜家族/模块/相关性冗余审计、20日窗口没有成熟的10日买入期望与ECE、以及不足60日的滚动相对收益。经验簇已消除运行时重复投票，但不能伪造原始柜预登记独立性；20日正收益、四只持仓和完整保存只证明工程链可用，不证明跨资本规模最优、长期盈利或可上线。月度ML继续保持影子/关闭，不借短窗口启用。
- 最终静态/回归验收：所有本次受影响Python文件再次`py_compile`通过，`git diff --check`通过；资本缩放、可扩展优化器、规模化风险/退出、经验因子聚类、V3.1黄金恢复、V3.2激进合同及Web入口/日期预检回归全部退出0。未删除、覆盖或纳入任何用户历史未跟踪产物。

### CHANGE-20260730-01：源码规模只读统计（不改策略代码）

- 用户问题：检查当前项目一共有多少行代码，不算注释。
- 本次操作：只读统计源码文件；未运行回测、未修改策略逻辑、未删除文件、未使用`python`或`py`。由于只是代码规模核验，不改变任何数据、公式、交易、报告或Web控制逻辑。
- 统计范围：纳入`.py`、`.pyw`、`.ps1`、`.mjs`、`.js`、`.ts`、`.tsx`、`.html`、`.css`、`.yaml`、`.yml`源码/配置文件；排除`.git`、`data`、`results`、`reports`、`runs`、`outputs`、`__pycache__`、`.mimocode`等产物或缓存目录。
- 统计口径：扣除空行、整行注释、常见块注释和Python三引号文档串；行尾内联注释所在行仍按代码行计入。
- 统计结果：纳入536个文件，总行数103,398，空行9,590，注释/文档行3,410，非空非注释代码行90,398。不含根目录`verify_*.py`验证脚本时，纳入301个文件，非空非注释代码行73,677。
- 分布摘要：`.py`文件529个、代码行89,645；`.pyw` 151行；`.ps1` 165行；`.mjs` 343行；`.yaml` 94行。按目录看，`functions`约58,233行，根目录脚本约31,506行，`tools`约565行，`config`约94行。
- 影响链：WBS-00变更控制与运行身份；本记录仅为审计统计证据，不进入策略研究、交易执行、账户、报告或上线验收链路。

### CHANGE-20260730-02：30日上午SCAP输出差异只读诊断（不改策略代码）

- 用户问题：分析2026-07-30上午输出结果为什么前后差距很大，并从数学、金融模型和代码模块逻辑定位原因。
- 本次操作：只读检查`results/runtime_progress_11888.json`、`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1200/v3/run20260729_233837`、`run20260729_234344`、7月29日多个`e4_l1800/e4_l1200`完整run、`governance_strategy_summary.csv`、`governance_candidate_funnel_summary.csv`、`governance_runtime_integrity_audit.csv`、`scap_profit_summary.csv`，并阅读`candidate_funnel_audit.py`、`mainline_v3.py`、`scap_v3_lean.py`、`policy.py`、`runner.py`、`config.py`相关逻辑。未修改策略、参数、执行、账户或报告代码，未删除文件，未运行新回测。
- 运行事实：2026-07-30 01:59完成的真实完整run为`e4_l1200/v3/run20260729_234344`，窗口`2025-01-02 -> 2026-05-29`，`final_net_value=1.229023169791833`，`total_return=22.9023%`，`max_drawdown=-18.7246%`，`closed_trade_count=37`，`closed_trade_win_rate=62.16%`，`realized_pnl=4769.72`，`profit_factor=1.7781`。同目录`run20260729_233837`仅写入PIT/因子时间合约，没有完整checkpoint和绩效账本，不能作为前后结果对照。
- 可比性诊断：7月29日白天`e4_l1800`完整run存在不同窗口和代码/身份口径，例如`run20260729_080250/092129/103208`截至2025-09-25为`+43.3465%`，`run20260729_115619`同截止日为`+29.6451%`，而30日凌晨`run20260729_234344`扩展到2026-05-29且为`e4_l1200`路径。不同日期窗口、止损/目录身份、运行身份哈希、代码指纹和保存阶段不得直接排名。
- 数学原因：收益是逐日NAV复利和持仓路径函数，`FinalNAV = cash + positions_market_value - costs`；窗口从2025-09-25扩到2026-05-29后新增行情、加仓、退出和未实现PnL都会改变终值。20日、180日、338日样本的闭合交易数从0/14/17/37变化，胜率、PF和最大回撤不是同一统计分母。`scap_profit_summary`中`optimizer_selected sample_count=0`说明部分选择血缘仍未进入利润目标审计，不能把该表当成优化器效果证明。
- 金融模型原因：SCAP-V3.2是小资金、整手、允许现金、最多5只、E4退出、赢家加仓开启、亏损摊平和主动替换关闭的激进开发口径。高集中度使单只或少数股票路径对NAV影响很大；赢家加仓会放大右尾，也会放大共同风格下跌。2025-04-07一类组合共振回撤会显著改变长窗表现，因此差异并不等同于因子突然失效或策略突然有效。
- 代码模块定位：主要差异来源在SCAP治理链而非TDX数据清洗或基础回测引擎。直接相关模块为`scap_v3_lean.py`的提案/唯一ActionPlan与赢家加仓、`integer_action_optimizer.py`的整数目标函数、`policy.py`的ActionPlan后订单过滤和旧离散入口残留、`runner.py`的Lean漏斗计数/授权/保存对账、`position_lifecycle.py`的E4退出和自适应止损、`runner_summary.py`/`candidate_funnel_audit.py`的报告口径。`candidate_funnel_audit.py`曾捕获`SCAP candidate funnel is non-monotonic`，证明早期run存在“slot为0但仍注册买单”的链路矛盾；最新完整run该单调性通过，但完整性审计仍有`execution_exposure_authorization=False`，2日实际暴露超过授权容忍。
- 结论：30日上午看到的大差距主要是口径不一致叠加SCAP动作链修复/路径扩展造成，不是单一数学公式错误，也不能归因为行情数据模块。当前最应优先复核的是唯一ActionPlan到订单/成交/暴露授权/利润审计的血缘一致性，其次才是因子经济有效性。所有相关run仍是`development_audit`且研究门`blocked`，不得作为上线或盈利准入结论。
- 后续要求：若要做真正因果判断，必须固定同一代码指纹、同一日期窗口、同一因子柜、同一资本档案、同一成本profile和同一PIT状态，做A/B单变量复跑；同时新增`optimizer_selected -> action_plan -> order -> fill -> PnL`血缘回归、暴露授权失败日复盘、`scap_profit_summary`选中样本非空校验和不同窗口的分段归因。

### CHANGE-20260730-03：30日上午SCAP差异复核、同类缺陷审计与完整修改方案（只读分析）

- 用户要求：继续检查代码是否存在同类型问题，从数学、金融模型和代码模块逻辑定位原因，并先形成详细完整修改方案；本条不授权直接修改策略代码。
- 本次边界与操作：先验证`E:\ForANACONDA\python.exe`为3.12.7、项目指定`stock_ai`解释器为3.10.19；只读检查Git工作区、WBS、7月29日至30日相关run的checkpoint/manifest/策略摘要/候选漏斗/安全决策/订单/成交/持仓/暴露/利润/完整性产物，并阅读`runtime_identity.py`、`runner.py`、`engine.py`、`policy.py`、`position_lifecycle.py`、`scap_v3_lean.py`、`integer_action_optimizer.py`、`runtime_integrity_audit.py`、`scap_profit_objective.py`。未删除文件，未运行新回测，未修改策略、参数、执行、账户或报告代码；仅新增方案报告和本WBS记录。工作区原有未提交改动均视为用户资产，未覆盖、回退或暂存。
- 可复现性新证据：`run20260729_103208`与`run20260729_115619`同为2025-01-02至2025-09-25的180日、2万元、同74因子柜、同费用、同随机种子、同特征文件大小/mtime、同记录代码指纹`c6773cad...`，但收益分别为+43.3465%和+29.6451%。WBS既有记录证明二者间接通winner-add字段；`runtime_identity._CODE_IDENTITY_FILES`却未包含直接承载提案和求解变化的`scap_v3_lean.py`、`integer_action_optimizer.py`、`scap_v31_authority.py`、`capital_scaling.py`等。同时`output_dir`进入runtime hash，使相同实验换目录也必然变身份。当前身份既不能可靠证明相同，也不能可靠证明不同。
- 路径分解：`103208`与`115619`首个实质交易分叉在2025-03-27，后者多选中`sz301300`一手`winner_add`，计划暴露由约69.50%变为83.63%，此后现金、权重、退出、再买和费用路径连锁变化。最新338日`run20260729_234344`在2025-09-25的NAV为27,499.46元（相对初始+37.4973%），到2026-05-29为24,580.46元，新增区间独立收益为-10.6147%；因此窗口扩展解释最终+22.9023%的一部分，但该run同时改变止损、代码和资本身份，仍不能与180日run作单变量比较。
- P0退出缺陷：最新338日安全账本有234个交易日出现普通`exit`提案被`non_positive_robust_profit`拒绝。`scap_v3_lean`只把少数原因映射为`hard_exit`，`integer_action_optimizer`又只强制`hard_exit/safety_exit`，使signal failure、thesis failure、profit giveback等普通E4退出可能因稳健利润不正而长期无交易权。实际卖出仅见profit hard stop 20笔、loss containment 14笔和safety deleveraging 3笔；当前结果不是文档所称完整E4路径，旧PF、胜率、持有期和回撤均不可作为修复后基线。
- P0暴露状态机缺陷：aggressive lean的战略预算由结构状态生成，强制降仓确认却主要读取另一套safety risk level/trigger streak。2026-02-02/03结构状态weak、目标/求解ceiling为65%，实际暴露约76.8%/77.3%，但safety risk仍normal而不生成强制退出，空计划保持超目标仓位，形成完整性审计2个失败日。必须拆分`desired_exposure_target`、`hard_exposure_ceiling`与`confirmed_derisk_target`；仅超软目标时实行非恶化，超硬上限或确认降仓时必须生成强制卖出或明确不可执行证据。
- P1血缘与报告缺陷：最新338日`governance_candidate_funnel_daily`的权威optimizer-selected累计42且registered entry buy同为42；`actual_exposure_ledger.optimizer_selected_entry_count`累计4,846，两者328/338日不一致；`scap_profit_summary.optimizer_selected sample_count=0`。原因是暴露账本保留Lean前旧选择口径、漏斗使用唯一ActionPlan口径、利润审计又未获得Lean最终选择回写。当前利润审计不能评价优化器，相关字段必须拆成preplan/actionplan/registered/filled四层并使用唯一proposal/plan血缘。
- P1数学与风险缺陷：赢家加仓在生命周期与Lean重复检查且Lean硬编码4%/8%，多个`attach_scap_v31_authority`调用可能产生不同权限快照，缺失review/authority字段又存在fail-open默认。优化器把约10日利润与日协方差边际波动直接相减，未显式按`sqrt(H)`换算；固定15% proposal downside、协方差CE、集中度惩罚和压力预算的职责未完全单一化；风险实际使用分解未落盘，日报可同时出现covariance runtime calibrated但used=False、风险贡献为0。
- P2金融/报告解释：最新run期末sleeve有效N约3.58、头号sleeve权重约33.77%，4—5只持仓不等于因子风险分散，winner-add会同时放大趋势右尾和拥挤反转左尾。-12%相对-18%止损还会改变卖出、冷却、再入场和费用路径，不能由现有run断言优劣。报告`benchmark_excess_return=-25.39%`与终值几何相对收益约-16.82%是不同公式，必须分列命名。
- 完整方案：新增`reports/SCAP_20260730_OUTPUT_DIVERGENCE_DEEP_AUDIT_AND_REMEDIATION_PLAN.md`。施工固定为Phase 0双身份/完整指纹与同spec确定性复现→Phase 1强制/风险/可选退出及三层暴露状态机→Phase 2单次权限快照和winner-add边际CE→Phase 3同期限人民币整数优化、单一风险表达及原子现金→Phase 4 proposal-plan-order-fill-PnL规范化血缘和报告修复→Phase 5同spec双跑、20日工程、180/338日、滚动块、留出期和前瞻纸面验收。
- 对应WBS影响链：WBS-00.07运行身份→WBS-06权限/校准→WBS-08.14/08.16唯一ActionPlan→WBS-09风险单位→WBS-10退出/补仓→WBS-11执行费用→WBS-13研究门→WBS-14.08/14.17血缘报告→WBS-16.05/16.10/16.16/16.17/16.20全链验收。当前状态仍为设计方案，未实施、未回测、禁止上线；建议主人确认后先实施Phase 0—1，不能先调因子或止损参数。

### CHANGE-20260730-04：SCAP同类缺陷全模块修复（阶段0—4实施与专项验收）

- 用户授权：按`CHANGE-20260730-03`方案直接实施所有模块；每一阶段先做不运行策略的代码审查，再执行专项bug测试；全部代码完成后另做20交易日从开始到保存的全流程实验。本条先登记阶段0—4代码实施和专项证据，20日实验结果将在同一变更记录续写。
- 工作区与解释器边界：使用`C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe`（Python 3.10.19）；未使用`python`或`py`，未删除文件，未覆盖、回退或暂存用户原有未提交改动。修改前已复核WBS影响链和现有dirty worktree。
- 阶段0（WBS-00.07/00.04）：`runtime_identity.py`升级为双身份。`experiment_spec_hash`只描述可比实验，排除输出目录；`run_instance_hash`包含输出目录并标识具体运行实例；兼容字段`runtime_identity_hash`指向实验spec。代码指纹扩展到`functions/decision_council`、`functions/execution`全部Python模块，资本档位写入完整解析值，小型因子柜文件写SHA256。`verify_scap_runtime_identity.py`验证换目录不改变实验spec、会改变run实例，且关键模块和资本参数进入指纹。
- 阶段1（WBS-08/10/16）：`ActionProposal`增加`execution_class/must_execute/authority_snapshot_id`；生命周期已确认的全部E4退出统一映射为`hard_exit`，不再由alpha利润目标否决。暴露状态拆为`desired_exposure_target`软目标、`hard_exposure_ceiling`硬上限、`confirmed_derisk_target`确认降仓目标；只超软目标时禁止进一步恶化，超硬上限或确认降仓时生成强制安全退出。普通可选退出仍与持有反事实竞争，但拒绝原因改为`hold_dominates_discretionary_exit`。
- 阶段1证据：受影响模块`py_compile`及`git diff --check`通过；`verify_scap_v3_lean_chain.py`、`verify_scap_exit_contract.py`、`verify_scap_exit_stage_contract.py`、`verify_scap_stage1_exposure.py`、`verify_scap_v2_property_contracts.py`、`verify_scap_v31_golden_restore.py`全部通过。
- 阶段2（WBS-06/10）：主运行链的`attach_scap_v31_authority`由同日三次收敛为一次，写入不可为空的`scap_authority_snapshot_id`；Lean仅为直接调用/合同测试保留一次fail-closed兜底。赢家加仓只消费生命周期已经确认的`add_allowed + winner_pyramiding`，删除Lean内重复硬编码4%/8%阈值和二次置信度变换；最大层数读取资本档位；缺少review、权限、层数配置或快照时默认拒绝。阶段2专项测试`verify_scap_v3_lean_chain.py`、`verify_scap_v3_lean_static_authority.py`、`verify_scap_v31_golden_restore.py`、`verify_scap_exit_contract.py`通过。
- 阶段3（WBS-08/09/11/14）：协方差边际风险从日频按`sqrt(risk_horizon_sessions)`换算到预测期限，再乘NAV和风险厌恶系数形成同单位人民币罚金；ActionPlan落盘`marginal_risk_penalty_amount/risk_model_used/risk_horizon_sessions`。卖出提案增加净`cash_release_amount`，计划现金、现金缓冲和替换原子约束均计入卖出回款。审计目标元组与优化器实际排序统一为稳健人民币利润、部署缺口、广度、期望利润、下行、成本。账户当前手数由runner的真实持仓股数和交易规则传入，不再优先用权重/单手权重反推。
- 阶段3证据：新增“强制卖出净回款进入ActionPlan”和“4日协方差罚金为1日的2倍”属性断言；`verify_scap_v2_property_contracts.py`、`verify_scap_v3_lean_chain.py`、`verify_scap_v31_golden_restore.py`、`verify_scalable_optimizer_contract.py`、`verify_scap_action_utility_v2.py`全部通过，相关文件`py_compile`与`git diff --check`通过。
- 阶段4（WBS-14/16）：每天保存规范化`governance_action_proposal_ledger.csv`和`governance_action_plan_ledger.csv`；proposal记录是否被唯一计划选中及拒绝原因，plan记录权限快照、软目标、硬上限、确认降仓、风险模型和目标分解。`scap_optimizer_selected`按最终ActionPlan的新开仓symbol回写候选/入场审计，暴露日报的optimizer计数改用Lean权威漏斗。完整性审计新增proposal→plan→order→fill一致性，并以`hard_exposure_ceiling`而非软目标判断执行越权。基准总收益明确标注`geometric_chain_linked_net_value`。
- 阶段4证据：新增唯一plan行、selected proposal与订单ID完全一致、精确账户手数保持不变断言；`verify_scap_v3_lean_chain.py`、`verify_scap_v3_lean_static_authority.py`、`verify_scap_action_utility_v2.py`、`verify_reporting_alignment.py`通过；相关模块`py_compile`和`git diff --check`通过。
- 客观边界：上述结果证明合同、构造场景和静态代码路径满足阶段要求，不证明策略盈利、因子有效或可上线。研究门继续`blocked`；阶段5必须完成全量回归、20日从输入到保存实验、产物解析和血缘/暴露/账户完整性核验后，才可把工程状态改为`verified`。
- 阶段5跨模块回归：按身份→时间隔离→效用/优化→退出/加仓→暴露→pending/替换→执行→漏斗/保存→报告顺序运行21个验证脚本，全部退出0；包括`verify_scap_runtime_identity.py`、`verify_scap_v2_property_contracts.py`、`verify_scap_action_utility_v2.py`、`verify_scap_unified_action_contract.py`、`verify_scap_add_reachability_v2.py`、`verify_governance_temporal_isolation.py`、`verify_scap_v3_lean_chain.py`、`verify_scap_v3_lean_static_authority.py`、`verify_scap_exit_contract.py`、`verify_scap_exit_stage_contract.py`、`verify_scap_stage1_exposure.py`、`verify_scap_v31_golden_restore.py`、`verify_scap_v31_position_recovery.py`、`verify_pending_order_idempotency_v2.py`、`verify_replacement_pair_execution_guard.py`、`verify_execution_rules.py`、`verify_v3_retail_audit_score_gate.py`、`verify_active_replacement_policy_integration.py`、`verify_runtime_checkpoint_and_schema_v2.py`、`verify_scalable_optimizer_contract.py`和`verify_reporting_alignment.py`（不存在的候选脚本未伪报为已运行）。最终所有本次涉及Python文件`py_compile`通过，`git diff --check`通过。
- 20日首次预检：命令只显式覆盖开始日而未覆盖默认结束日，被日期合同在进入策略循环前以`No observed feature session in 2025-01-02..2024-12-31`拒绝；未产生交易或部分run。失败stdout/stderr保存在`reports/scap_20260730_remediation_20d_stdout.txt`和`reports/scap_20260730_remediation_20d_stderr.txt`，用于证明空窗口被fail-closed。
- 20日正式实验口径：显式固定`2025-01-02..2025-12-31`并以`governance-max-days=20`截取20个观察交易日；`all_a_share_research`、`small_capital_lean`、20,000元、最多5只、1,000元缓冲、`aggressive_lean`、E4、-18%灾难底线、`mainline_v3_cabinet_native`、固定74因子柜`pruned_run20260714_184846_581132_20260715_230524`、PIT research、关闭shadow和live monitor。正式stdout/stderr为`reports/scap_20260730_remediation_20d_retry_stdout.txt`和`reports/scap_20260730_remediation_20d_retry_stderr.txt`，进程PID 38208正常退出，stderr为0。
- 20日完整产物：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260730_200746`；checkpoint、`COMPLETE.json`和artifact manifest均为`complete`，日期2025-01-02至2025-02-06、20/20日。`experiment_spec_hash/runtime_identity_hash=7327ec86b8cafccc7cb715e7c8a46e2ab476b27f3074e4b0e50d494340a53994`，`run_instance_hash=b1ed062ceb8c4704a024cbd2190d7fb23505613599ef272d5836cabb1cfa5430`，`code_fingerprint=78fb2cdc4ce3b82e289c303e99965b2b480ccf219fc1193338d36fe7197b3409`，因子柜内容SHA256为`b8dd096a6706b63e6e960d01e23fa647763b7cd5113ace055db58e2395788b90`，样本角色为`development_audit`。
- 保存层验收：目录共130个文件；111个CSV逐文件`Import-Csv`失败0，9个JSON逐文件解析失败0，无XLSX，零字节文件0。运行完整性12/12通过：4笔filled股数守恒、信号早于成交、次日执行、order_id唯一、账户20/20日NAV重建误差0、持仓上限、硬暴露授权、Action血缘和持仓状态/分数覆盖均通过。
- Action血缘验收：20个decision恰有20个唯一ActionPlan且每个`optimizer_invocation_count=1`；3,978个Proposal ID全部唯一；最终selected proposal、order proposal和filled proposal均为4，`selected-order=0`、`filled-selected=0`；权限快照缺失0、负计划现金0、计划超硬暴露0。`actual_exposure_ledger.optimizer_selected_entry_count`与权威漏斗累计均为4；`scap_profit_summary`的optimizer-selected已观察样本由旧run的0修复为4。
- 20日金融结果：最终净值`1.0219618770730023`、成本后总收益`+2.1961877073%`、最大回撤`-2.3038122927%`、4只持仓、0笔闭合交易，因此profit factor无统计意义；几何链式基准收益`+6.6736768162%`，复合超额净值收益`-5.1073387571%`。optimizer-selected 20日审计样本4个，平均净利润308.73元、中位393.72元、正收益率75%；该未来20日字段仅为事后审计，不能反哺决策或作为显著性证明。
- 最终状态：阶段0—5的代码合同、专项回归和20日工程全链状态改为`verified`；策略研究/上线状态仍为`blocked`。20日正收益、4个选择样本和无闭合交易无法证明长期盈利，后续必须使用冻结的同一`experiment_spec_hash`做同spec重复跑、180/338日修复后基线、滚动块/留出期与独立复核；禁止把本次结果与修复前run直接排名。
- 清理：正式进程退出后仅删除本次创建且已失去用途的单个临时PID文件`reports/scap_20260730_remediation_20d_retry.pid`；未批量删除任何文件，stdout/stderr和全部实验产物均保留。

### CHANGE-20260730-05：SCAP 静默计算缺陷只读复审

- 用户目标：继续检查“不影响运行、但影响计算”的缺陷。本轮严格限定为只读计算正确性审计；未修改策略、参数、执行、账户或报表代码，未删除文件，未重新运行回测。新增详细报告`reports/SCAP_20260730_SILENT_CALCULATION_BUG_AUDIT.md`。
- 审计对象与可比性：只复核阶段0—5完成后的20日完整产物`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260730_200746`及当前代码。该run的日期、资金、因子柜、费用、PIT、代码和实验指纹边界沿用`CHANGE-20260730-04`；没有把其他窗口或其他代码状态当作受控对照。
- 已确认影响当前产物的P0：`analytics.py`把每日账户收益减基准收益后再复利，并将结果命名为`benchmark_excess_return`。本次报表值为-5.1073387571%，而账户终值/基准终值-1约为-4.19737019%，简单总收益差约为-4.47748911%；三者不是同一数学对象。报表必须分列命名，几何相对财富应由NAV比值计算。
- 已确认影响当前产物的风险缺陷：20个ActionPlan全部写`risk_model_used=covariance`，但20个实际暴露日全部是covariance cold-start且`covariance_risk_model_used=False`；唯一买入日计划暴露约84.18%，边际协方差罚金仍为0。候选矩阵只取前80只，历史不足列被删除，缺失配对又以0协方差填充；“矩阵全局非空”不能证明入选股票已被风险模型覆盖，0协方差也不是保守未知值。
- 已确认影响当前计划目标的P1：`integer_feasible_exposure`只做单只可支付检查，没有累计扣现金，也没有从`top_n`扣除已占槽位；`signal_supported`使用罚authority前的`robust_profit>0`，而优化器使用罚后值。本次共有82个新开仓提案在罚前为正、罚后不可选，因而部署目标/缺口罚金可能被高估。
- 已确认目标审计不闭合：优化器扣除`soft_thesis_penalty`但ActionPlan不保存该项；唯一买入日入选提案稳健利润约74.9347元、authority罚金约16.8356元、未落盘thesis罚金约1.6889元，最终目标约56.4102元。`robust_net_profit_amount`实际为多项组合罚金后的目标值，不能按字段名理解为纯稳健净利润。
- 已确认最优性声明过强：唯一买入日有88个可执行正收益候选，先经启发式`_pareto_reduce`截为24个再穷举；`solver_optimality_proven=1`只对裁剪后的搜索集合成立，不能证明原始可行提案全集最优。该reducer不是严格Pareto支配证明，多手方案还可能因最低佣金产生非线性。
- 条件触发P0：Lean唯一ActionPlan生成后，runner仍无条件调用`_augment_force_deploy_diversify_orders`；在`force_deploy`配置下可追加没有ActionProposal/ActionPlan血缘的买单。本次为`allow_cash`，所以4个selected proposal、4个order和4个fill完全一致，当前run未被该旁路污染。
- 条件触发P0/P1：退出`cash_release_amount`用当前市值减候选一手往返成本，而不是全部真实股数的卖出净回款；成本内含的`one_lot_cash_required`同时被当作市场暴露、收益本金和现金需求；当已持仓股票不在当日候选表时，精确手数不会进入Lean槽位集合；loser add开关开启后可绕过生命周期`add_allowed/review/authority`；Lean active-replacement授权没有对应的replacement proposal生成器；authority兼容兜底可用legacy值合成Tier A，存在生产fail-open风险。20日窗口无卖出、loser averaging关闭、allow-cash，因此这些问题本次未触发，但会在配置或市场状态变化时改变计算。
- 字段语义风险：`scap_profit_objective.py`的所谓`realized_net_profit_yuan_20d_audit`使用决策日forward return、候选一手现金和估算成本，不是次日真实fill与trade-pair实现盈亏，应改为counterfactual forward audit；`invested_capital_return`是按日暴露缩放近似，必须显式标记approximate。
- 只读验证证据：固定解释器为Python 3.10.19；`verify_scap_v3_lean_chain.py`、`verify_scap_action_utility_v2.py`、`verify_scap_profit_objective_audit.py`、`verify_governance_runtime_integrity.py`、`verify_scap_unified_action_contract.py`全部退出0。这些通过证明现有合同路径没有运行错误，但没有覆盖上述数学语义、风险覆盖、旁路配置和字段命名缺陷，不能据此否定本次发现。
- WBS影响链：WBS-08唯一ActionPlan/整数优化→WBS-09风险覆盖与同期限人民币单位→WBS-10退出/加仓/替换授权→WBS-11现金与精确费用→WBS-13研究门→WBS-14血缘和报表语义→WBS-16全链验收。建议按P0后P1顺序先补失败测试再实施，随后以相同`experiment_spec_hash`重跑20日，并追加180/338日、滚动块和留出期。
- 当前状态：阶段0—5的既有工程验收结果不撤销，但“计划计算/风险状态/相对收益报表正确性”重新标记为`remediation_required`；策略研究门和上线门继续`blocked`。本条是缺陷发现和修复建议，不构成修复完成或收益改善证明。

### CHANGE-20260730-06：更新前黄金版本 GitHub 冻结与主干合并

- 用户授权：将当前代码在后续静默计算缺陷修复前冻结为新的 GitHub 黄金版本分支，并在发布审查后合并远端主干。
- 发布分支：`codex/golden-pre-calculation-fix-20260730`；基线为与`origin/main`完全同步的本地`main`，发布前`origin/main...main`左右提交差为`0/0`。
- 提交范围：当前全部已修改的受控源码和验证脚本、新增`functions/decision_council/capital_scaling.py`及4个新增验证脚本、WBS，以及2026-07-29至30日与本次代码状态直接相关的正式Markdown审计/方案报告。大量历史smoke目录、测试生成目录、stdout/stderr、运行过程JSON和其他临时产物不进入Git提交；它们保留在本地且不删除。
- 版本语义：该分支是“静默计算缺陷修复前”的工程黄金快照，不代表策略可上线。`CHANGE-20260730-05`确认的相对收益公式、协方差覆盖、计划目标、最优性声明、条件订单旁路等问题仍然存在，因此研究门和上线门继续`blocked`。
- 发布流程：先在新分支显式暂存上述文件，执行相关验证和`git diff --check`，再提交、推送、创建面向`main`的PR；仅在远端检查通过且合并无冲突时合并。分支、提交、PR、合并SHA和验证结果在本条后续补录。
- 提交前验证：固定解释器`C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe`为Python 3.10.19；32个本次受影响/新增Python文件全部`py_compile`通过。随后按身份、整数优化、动作效用、退出/加仓/替换、时间隔离、pending、执行、运行完整性、资本缩放、经验因子簇、利润审计、报表和Web合同顺序运行28个专项验证脚本，结果28/28退出0。该验证证明当前黄金快照满足既有工程合同，但不撤销`CHANGE-20260730-05`记录的静默计算缺陷。
