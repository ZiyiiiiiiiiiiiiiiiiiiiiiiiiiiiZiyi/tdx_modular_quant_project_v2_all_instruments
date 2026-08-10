# SCAP 2026-03-08 后回撤：全模块修复与 20 日验收报告

日期：2026-08-10

分支：`codex/scap-post-drawdown-remediation-20260810`

最终验收 run：`results/decision_council/scap/cab_c6dae8d4d69c/e4_l1800/v3/run20260810_200024`

窗口：2026-03-09 至 2026-04-03，共 20 个交易日

运行身份：`09e33f4689d714347f7d8fe1e096421398f0ed3692ad05108e739a98cc970e02`

代码指纹：`362dde459f628b262585bf901c895acbf007322eea232821a9b01901e17a9df7`

## 1. 结论

本轮工程修复完成，20 日从决策到保存的全流程通过；但策略在该窗口的经济表现明显失败，研究门和生产门都不能放行。

- 工程结果：20/20，最后成功日期 2026-04-03，进程退出码 0；checkpoint、artifact manifest、129 个 save-frame、146 个顶层 CSV、因子工作簿内容校验和视觉校验均完成。
- 经济结果：20,000 元降至 17,862.24 元，总收益 -10.6888%，最大回撤 -12.0735%。研究绩效基准为 -8.7206%，策略几何超额 -2.1563%。
- 亏损组成：3 笔已平仓全部亏损，已实现 -1,113.74 元；期末 4 个持仓全部浮亏，合计约 -1,024.02 元。两者合计与 NAV 损失约 -2,137.76 元一致。
- 核心诊断：该窗口新开仓均属于缺少严格全市场滚动 OOS 证据的 C 级；新权威账本将其判为 `shadow_only`，但为保证本次是诊断性改造，默认模式没有反向改写历史交易行为。
- 退出结论：47 条 post-entry-failure 观察中 43 条因 `configured_diagnostic_only` 无交易权。其检测后平均 5/10/20 日收益为 +1.64%/+1.91%/+3.91%，不能据此直接打开“检测即卖出”；这些行还存在同股票重复观察，必须做预注册的逐事件去重消融。
- 市场状态结论：20 日中 neutral 13 日、weak 4 日、bull 3 日；恢复状态 17 日 STABILIZING、3 日 STEP1，从未到 OPEN。这证明固定不变的市场标准不合理，但恢复模型仍只能保持 diagnostic，不能直接控制交易。
- 门控：工程门通过；研究门 `blocked`（6 项失败）；生产门 `blocked`。不得上线实盘。

## 2. 实际完成的模块

| 模块 | 接口/产物 | 权限与金融口径 |
|---|---|---|
| 退出真值 | `ExitSignalObservation`、`ExitAuthorityDecision`；exit authority/delay CSV | detected、paper、policy、control、authority、selected、order、fill 分离；默认 diagnostic 无交易权 |
| 市场状态与恢复 | `MarketStateVector`；market state/recovery episode CSV | 有效上限为 hard safety、结构预算、恢复阶梯、整数可达上限的最小值；恶化立即、恢复需连续健康日 |
| 买入质量 | `EntryEvidenceSnapshot`、`EntryQualityAuthority`；entry quality CSV | 人民币 CE 使用生命周期成本后 robust profit，并把 authority/scenario/model uncertainty 各扣一次；C 级缺严格 OOS 时只允许 shadow |
| 四基准 | `BenchmarkBundle`；benchmark bundle CSV | performance、opportunity set、style match、safety proxy 不得互相冒充；缺失角色 fail closed |
| 状态—因子 | regime factor IC daily/family/summary/stability/status CSV | PIT 日截面 Rank IC、IC/标准差、方向正确率、top-bottom spread、Newey-West、BH-FDR；样本不足显式失败 |
| 保存完整性 | artifact manifest 增加 `research_products_complete` | 研究产品失败不伪装成核心账本失败，状态分别披露 |
| Web | 7 个只读 API 与 diagnostics 页 | 日期/信号联动、持仓数量曲线、状态/基准/退出/买入/因子/门控面板；无在线改权或改阈值接口 |
| 工作簿 | `SCAP_holding_factor_curves.xlsx` | 文件名改为跨 Python/Node 稳定的 ASCII；单日窗口公式改为数学等价的末行直接引用；中文交互文本修复 |

只读 API：`/api/market-state`、`/api/benchmarks`、`/api/exit-authority`、`/api/entry-quality`、`/api/regime-factors`、`/api/gates`、`/api/diagnostic-export`。所有接口返回显式 authority/data-quality envelope，缺失数据返回 pending/legacy_unavailable/failed，而不是伪造 0。

## 3. 分阶段缺陷与修复证据

1. 原始保存 bug：holding-factor workbook 内容/视觉核验失败，导致 338 日任务在最后保存阶段抛错。
2. 第一处根因：工作簿文件名在 Python 到 Node 之间被损坏成问号路径。改为 `SCAP_holding_factor_curves.xlsx`。
3. 第二处根因：Summary 使用 `INDEX(range, ROWS(range))`，artifact evaluator 在单日窗口返回 `#VALUE!`。改为直接引用已知末行；公式含义不变。
4. 1 日完整 smoke：`run20260810_194056`，退出码 0，checkpoint/manifest complete，工作簿 content/visual passed。
5. 首轮 20 日：`run20260810_194455` 完成，但产物审计发现 recovery episode 为空。
6. 第三处根因：episode 只接受显式 `BLOCKED` 行作为起点；持久化首行已经从隐式初始 BLOCKED 推进到 STABILIZING，整段被跳过。现改为任意非 OPEN 状态启动 episode、首次 OPEN 闭合。
7. 最终 20 日：`run20260810_200024` 完成；episode 正确生成 1 条，起止 2026-03-09/2026-04-03，20 日，未到 OPEN。
8. 非侵入性对账：最终 run 与修复前首轮 20 日的 `nominal_nav/cash/actual_exposure/holding_count/invested_value` 逐日最大差异均为 0。

## 4. 20 日窗口的策略诊断

### 4.1 账户与执行

- 平均实际暴露 57.69%，最大 74.14%，平均持仓 4.7，只数最大 6。
- 现金为负天数 0；持仓上限违约 0；计划 floor 合同违约 0；12 项 runtime integrity 全部通过。
- 2026-03-23 风险上限从 85% 降至 65% 时，既有实际暴露为 70.88%，短暂超出 5.88 个百分点。当天选中 3 个 `loss_containment_exit`，2026-03-24 成交后暴露降至 38.51%。这是决策后执行时序和隔夜价格变化，不是越权新增买入；账本显示无 locked position、无 unresolved safety exposure。
- 绩效基准有 3 日覆盖率 99% 而被标为 attribution invalid；展示净值仍按缺价零收益口径连续。因此 -8.7206% 只能作为 exploratory endpoint benchmark，不是正式可投资基准结论。

### 4.2 买入质量

- entry-quality 权威表共 119 行：C 级 115 行，A 级 4 行（A 级是 hard exit，不是新买入）。
- 119 行的 full-universe OOS 状态全部 unavailable；71 行为 `shadow_only`，44 行 blocked。
- 83 行通过经济订单门、75 行人民币 CE 为正，但“CE 为正”不能替代外样本授权。
- 实际被 ActionPlan 选中的 7 个新开仓全部为 C 级、`tier_c_full_universe_oos_unavailable`。窗口内 3 个已经以 -14.03%、-16.86%、-16.10% 平仓；期末其余 4 个浮亏约 -10.69%、-15.77%、-11.54%、-2.64%。
- 所以本窗口支持“买入证据校准不足/低证据新开仓是主要问题”，不支持“只要提高持仓数量或投入更多钱即可修复”。

### 4.3 退出质量

- 47 条 signal observation 涉及 6 只股票；47 条 detected/paper，4 条获得真实 authority 并被选中，分别是 3 月 23 日三笔 loss containment 和 4 月 3 日一笔尚未成交的 loss containment。
- post-entry-failure 的 raw signal 不再伪装成真实卖出权。43 条仅诊断观察明确记录 veto。
- 检测后均值为正提示“早卖”存在反弹风险。由于观察行不是独立事件，当前只足以否定立即全开，不足以证明永远关闭；下一步应按 `symbol + first_detected_date` 去重后做 0/1/2/3 日延迟的单变量 shadow 消融。

### 4.4 市场状态

- 诊断模型给出的有效部署上限在 26.0% 至 58.5% 之间，但 authority_mode 全部为 diagnostic，所以没有改变本次交易。
- 恢复 episode 20 日内没有到 OPEN；说明冲击后的状态并未达到模型定义的完全恢复。
- 这支持把 fast shock、structural regime、recovery state 分层，而不是用一个永恒阈值；但启用 trading 前必须完成同代码身份、单变量 A/B。

## 5. 2025 年 9—12 月：对“持续走低”的校正

审计对象为已完成的 338 日 run `run20260809_214739`。它与本次 20 日 E4/-18% 代码身份和止损参数不同，只能用于历史事实描述，不能作单变量因果比较。

| 月份 | 策略收益 | 研究基准 | 几何超额 | 平均暴露 | 平均持仓 | 主要结构状态 |
|---|---:|---:|---:|---:|---:|---|
| 2025-09 | +4.74% | +10.63% | -5.32% | 65.68% | 5.45 | bull 22/22 |
| 2025-10 | -0.59% | -2.64% | +2.10% | 61.91% | 5.29 | bull 16、neutral 1 |
| 2025-11 | -4.01% | -3.79% | -0.22% | 58.47% | 4.80 | bull 10、neutral 9、weak 1 |
| 2025-12 | -0.76% | -0.69% | -0.08% | 66.84% | 5.78 | neutral 13、bull 10 |

9—12 月合计策略 -0.81%，基准 +2.92%，几何超额 -3.62%。因此“9—12 月一直绝对下跌”不准确：9 月策略上涨，主要问题是没有跟上强牛市基准；10 月反而跑赢；11—12 月主要是市场共同下行并有轻微相对落后。

按买入月份看闭合交易也明显不稳定：9 月 9 笔、胜率 66.7%、均值 +2.71%；10 月 5 笔、胜率 20%、均值 -6.64%；11 月只有 1 笔，不可推断；12 月 6 笔、胜率 83.3%、均值 +5.58%。这支持“买入质量随状态变化”，但不支持把整个 9—12 月归因于单一市场模块。

关于“钱更多反而挣得更慢”：当前没有同代码、同日期、同因子柜、同成本、只改变初始资本的受控 A/B，不能作因果结论。可能机制包括固定持仓/订单只数导致现金拖累、整手可达性、有限正 CE 信号、市场 beta 变化和低证据 C 级开仓，但必须用资本网格实验验证，不能凭单个 run 调参。

## 6. 不同市场状态下的因子证据

338 日只读重建产品覆盖 74 因子、11 家族、338 日、244,638 条日度指标、1,773 条汇总。以下仍是 `candidate_gate_conditional`、proposal audit 范围；严格 full-universe rolling OOS unavailable，因此只可用于研究排序。

全状态：

- reversal：5/10/20 日 mean Rank IC 为 0.0623/0.0680/0.0649，IC/标准差为 0.492/0.587/0.536；三档 BH-FDR 均通过，是最一致的家族。
- volatility：5/10/20 日 IC 为 0.0578/0.0575/0.0403，短中期较稳，20 日 FDR 未通过。
- momentum：5/10 日 IC 约 0.0287/0.0276，20 日不在前列，说明更偏短周期。
- breakout：10 日 IC 0.1063、IC/标准差 0.383，但只有 65 个观察日，不能与 333 日家族等权比较。
- value 与 orderflow 在当前符号约定下长期为负：10 日 IC -0.0286/-0.0215，20 日 -0.0450/-0.0217。应优先检查方向定义或降权，不应继续按“名称听起来合理”强行正向使用。

10 日、按 structural state：

- bull（148 日）：volatility IC/标准差 0.448、growth 0.369、reversal 0.367；value -0.369。bull 中 growth 的作用明显强于 neutral。
- neutral（166 日）：reversal 最强，IC 0.0896、IC/标准差 0.820、FDR q 约 1.58e-8；volatility 次之。growth 在 neutral 转负，IC/标准差 -0.273。
- weak 样本按 safety policy band 仅 44 日：volatility IC/标准差 0.903、reversal 0.641；value -0.447、orderflow -0.304。样本虽超过最低 30 日，但仍应扩大 OOS。

建议的 shadow 路由是：bull 研究 volatility/growth/reversal；neutral 以 reversal/volatility 为主；weak 只研究 volatility/reversal 并降低部署上限。value/orderflow 在修正方向定义前不获得新增权重。该建议不是交易授权。

## 7. 基准应该如何选

不能随市场状态事后切换绩效基准，否则会产生 benchmark shopping。应该固定绩效基准，同时让市场状态改变风险预算和 shadow 因子路由。

1. **正式绩效主基准**：若策略授权范围确为小市值且强调流动性，优先预注册中证 2000 的可投资总收益/ETF 实现版本；官方编制方案说明它选取市值较小且流动性较好的 2,000 只证券。当前组合多为 301/603 小市值股票，用沪深 300 作唯一绩效基准存在明显风格错配。来源：[中证2000指数编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208180041-932000_Index_Methodology_cn.pdf)。
2. **市场整体副基准**：中证全指用于说明全 A 市场方向；官方样本覆盖沪、深、北交易所符合条件证券。来源：[中证全指编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175438-000985_Index_Methodology_cn.pdf)。
3. **机会集基准**：用每个决策日前可知的 PIT 可交易池、相同过滤规则和预声明权重构造；当前尚未物化，必须保持 unavailable。
4. **风格匹配基准**：在小盘主基准上做行业/规模/beta 暴露匹配，仅用于 alpha 归因，不替代绩效基准。
5. **安全代理**：沪深 300/510300 可继续作为流动性和大盘冲击代理，但官方沪深 300 是大市值、高流动性 300 只证券，不能冒充小盘绩效基准。来源：[沪深300指数编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)。

## 8. 测试与门控

最终回归通过：受影响文件 `py_compile`；退出/恢复/买入/基准性质测试；Web API/布局/持仓数量曲线；regime factor 与 full-universe OOS 合成测试；Lean 单一权威、ActionPlan、仲裁、执行与黄金恢复；保存韧性；工作簿集成；`git diff --check`（仅用户既有 baseline JSON 的 CRLF 提示）。

研究门失败项：alpha diversification、buy expectancy 10d positive、entry calibration ECE、latest sleeve effective N、entry-failure sell lag ratio、rolling 60d beat ratio。另有 PIT adjustment、PIT corporate action、PIT universe、PIT industry、正式账户/公司行动账本、税务账本、可投资基准、独立复核和正式复现包未完成，所以生产门继续 blocked。

## 9. 下一步顺序

1. 保持新模块 diagnostic/shadow，不打开交易权。
2. 以同一代码身份跑不少于 338 日 development A/B：每次只打开 exit、recovery、entry-quality 中一个模块。
3. 建立不少于 504 日、严格 PIT、全市场滚动 OOS；C 级只有在同状态同家族证据通过后才可候选交易权。
4. 做初始资本网格（2/5/10/20/50 万），其他条件完全冻结，比较收益、暴露、现金拖累、整手可达性、容量和成交成本，回答“更多钱为何更慢”。
5. 预注册中证 2000 主基准、中证全指副基准、PIT 机会集和风格匹配基准；禁止事后换基准。
6. 完成独立复核、正式复现包、税务/公司行动账本后，才重新评估研究门和生产门。
