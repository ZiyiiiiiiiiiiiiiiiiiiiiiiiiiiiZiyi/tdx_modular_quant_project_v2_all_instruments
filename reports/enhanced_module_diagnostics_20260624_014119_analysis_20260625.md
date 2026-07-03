# Enhanced Module Diagnostics 20260624_014119 Analysis

生成日期: 2026-06-25

数据来源:

- `results/governance/layer_ablation_diagnostics_suite_20260624_014119/`
- 回测诊断窗口: 2023-01 至 2024-12
- 股票池: `hs300_csi500_a500_strict`
- shadow portfolios: 关闭
- 诊断线路: 13 条增强模块线路

## 1. 总结论

这次诊断不是“策略完全没有信号”，而是证明了当前主线存在明显的信号分工错误:

- `orderflow_only` 绝对收益最强，账户收益 `+7.31%`，持仓组合收益 `+32.12%`。
- `reversal_only` 买入端最干净，买入 10 日 expectancy `+0.29%`，账户最大回撤 `-6.93%`。
- `breakout_only` 概率桶最可信，10 日 best Wilson lower `50.17%`，是唯一超过 50% 的模块。
- `trend_only` 更像持有/过滤信号，不适合直接做买点，买入 10 日 expectancy `-0.67%`。
- `core_plus_regime`、`core_plus_probability`、`core_plus_complex_exit` 都拖累主线。
- `full_mainline_control` 仍是低仓位防守系统，不是强 alpha 系统，持仓组合收益 `-9.91%`。

下一阶段主线不应继续使用 23 因子 reputation 直接混合决策。更合理的结构是:

```text
候选池: orderflow
买入确认: reversal + breakout probability bucket
持有过滤: trend
卖出执行: 简化 exit，复杂 exit 先转观察
风险约束: top risk contribution 硬门槛
概率层: 暂停仓位驱动，只做高桶过滤和诊断
```

## 2. 13 条线路核心结果

| 线路 | 账户收益 | Sharpe | 最大回撤 | 平均仓位 | 持仓组合收益 | Top30 benchmark excess | 买入10日expectancy | 最大风险贡献 | 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `01_core_base` | `+0.95%` | `0.101` | `-15.24%` | `36.58%` | `+9.08%` | `+7.46%` | `-0.31%` | `23.66%` | 基线可用但买点不够好 |
| `02_trend_only` | `+1.93%` | `0.157` | `-12.50%` | `38.17%` | `+16.96%` | `+11.09%` | `-0.67%` | `25.96%` | 更适合持有/过滤 |
| `03_reversal_only` | `+2.28%` | `0.247` | `-6.93%` | `32.15%` | `+16.06%` | `-4.40%` | `+0.29%` | `100.00%` | 买点最好但风险集中严重 |
| `04_orderflow_only` | `+7.31%` | `0.494` | `-13.26%` | `37.42%` | `+32.12%` | `-80.04%` | `-0.08%` | `22.98%` | 绝对收益最强，候选池价值最高 |
| `05_breakout_only` | `+1.67%` | `0.150` | `-10.86%` | `36.49%` | `+11.30%` | `+5.16%` | `+0.006%` | `41.72%` | 概率桶最可信，需控风险 |
| `06_core_minus_trend` | `-0.49%` | `0.000` | `-11.57%` | `35.11%` | `+8.70%` | `-63.20%` | `-0.15%` | `35.47%` | 去趋势后账户转差 |
| `07_core_minus_reversal` | `+1.13%` | `0.109` | `-13.57%` | `37.15%` | `+13.92%` | `+7.87%` | `-0.68%` | `25.70%` | 去 reversal 后买入恶化 |
| `08_core_minus_orderflow` | `-2.58%` | `-0.150` | `-12.12%` | `36.95%` | `+9.74%` | `+3.06%` | `-0.09%` | `100.00%` | 去 orderflow 后账户明显变差 |
| `09_core_minus_breakout` | `-0.53%` | `0.008` | `-15.30%` | `36.80%` | `+7.35%` | `+9.27%` | `-0.22%` | `25.83%` | 去 breakout 后账户转差 |
| `10_core_plus_regime` | `-1.24%` | `-0.082` | `-9.89%` | `24.70%` | `-2.76%` | `+4.01%` | `-0.64%` | `24.56%` | 状态机更像防守器，不增 alpha |
| `11_core_plus_probability` | `-3.02%` | `-0.180` | `-12.53%` | `35.52%` | `+2.63%` | `+2.70%` | `-0.51%` | `79.61%` | 概率层不应驱动仓位 |
| `12_core_plus_complex_exit` | `-9.86%` | `-0.824` | `-16.70%` | `32.28%` | `-19.74%` | `-5.07%` | `-1.06%` | `36.86%` | 复杂卖出当前明确拖累 |
| `13_full_mainline_control` | `-2.89%` | `-0.331` | `-8.03%` | `17.71%` | `-9.91%` | `+0.87%` | `-0.08%` | `100.00%` | 低仓位防守，不是强 alpha |

## 3. 关键模块解释

### 3.1 Orderflow: 候选池价值最高，但不是独立买点

`orderflow_only` 的账户收益和持仓组合收益最强:

- 账户收益: `+7.31%`
- 持仓组合收益: `+32.12%`
- 最大回撤: `-13.26%`
- 最大风险贡献: `22.98%`

但它的买入 10 日 expectancy 仍是 `-0.077%`，说明它更像“找股票池/找资金关注方向”的工具，而不是独立买点。

它的 Top30 benchmark excess 是 `-80.04%`，原因是本次 synthetic top-strength 30% benchmark 在该模块环境下收益高达 `+325.74%`。这不应直接解读为 orderflow 失效，而应解读为: orderflow 抓到了强风格，但没有跑赢同类最强 30% 的极端参考组合。该 benchmark 是探索性合成基准，不是可直接投资基准。

### 3.2 Reversal: 买入质量最好，但组合风险必须硬控

`reversal_only` 是唯一买入 10 日 expectancy 明显为正的模块:

- 买入 10 日 expectancy: `+0.29%`
- 买入 10 日 hit rate: `48.86%`
- 账户最大回撤: `-6.93%`
- 持仓组合收益: `+16.06%`

但最大风险贡献达到 `100%`。这意味着某些日期风险几乎完全由单一股票解释。它适合作为买入确认模块，但不能单独开放高仓位。

### 3.3 Breakout: 概率桶最可信

`breakout_only` 的整体收益不是最高，但概率验证最好:

- best Wilson lower: `50.17%`
- 买入 10 日 expectancy: `+0.006%`
- 10 日 `60-65%` 桶真实胜率: `60.44%`
- 10 日 `60-65%` 桶 Wilson lower: `50.17%`
- 10 日 `60-65%` 桶 expectancy: `+3.18%`

它适合做高置信入场过滤，而不是单独作为全局 alpha。

### 3.4 Trend: 适合持有和过滤，不适合买点

`trend_only` 的账户和持仓表现可以:

- 账户收益: `+1.93%`
- 持仓组合收益: `+16.96%`
- Top30 benchmark excess: `+11.09%`

但买入 10 日 expectancy 是 `-0.67%`。这说明趋势模块不适合直接触发买入，更适合作为:

- 持有继续验证
- 市场状态过滤
- trend break 退出辅助

### 3.5 Regime / Probability / Complex Exit: 当前不应进入主线加权

`core_plus_regime`、`core_plus_probability`、`core_plus_complex_exit` 相对 `core_base` 都是负增量:

- `core_plus_regime`: 账户收益下降 `-2.19%`，持仓组合下降 `-11.84%`
- `core_plus_probability`: 账户收益下降 `-3.97%`，风险贡献增加 `+55.95%`
- `core_plus_complex_exit`: 账户收益下降 `-10.81%`，持仓组合下降 `-28.82%`

这说明当前复杂层不是增强器，而是噪音和约束叠加器。

## 4. 买入端结论

买入端目前不能简单提高仓位。当前更合理的买入闭环是:

```text
step 1: orderflow 进入候选池
step 2: reversal 确认买点
step 3: breakout 高概率桶确认入场质量
step 4: trend 过滤是否值得持有
step 5: risk contribution 硬约束决定实际权重
```

下一版买入规则建议:

```text
candidate_pool = orderflow_rank_top

entry_confirmed =
    reversal_score_rank_pass
    and breakout_probability_bucket_pass
    and expected_return_after_cost > 0
    and liquidity_ok
    and not risk_cap_blocked

starter_position:
    reversal pass + orderflow support

confirmed_add:
    starter 后 3-5 日未失败
    breakout probability high bucket pass
    trend not broken

high_conviction:
    reversal positive
    breakout 60-65% or 65%+ bucket historically positive
    orderflow support
    top1 risk contribution <= 25%-35%
```

## 5. 卖出端结论

复杂卖出当前不能直接保留为主动执行层。

`core_plus_complex_exit` 中主要卖出原因表现:

- `profit_giveback_exit`: 10 日 expectancy `-1.37%`
- `replacement_opportunity_exit`: `-2.51%`
- `post_entry_failure_exit`: `-0.42%`
- `alpha_collapse_consensus`: `-3.02%`

但在 `full_mainline_control` 中:

- `post_entry_failure_exit`: `+1.62%`
- `replacement_opportunity_exit`: `+1.53%`
- `safety_deleveraging`: `+0.20%`
- `profit_giveback_exit`: `-1.71%`
- `normal_sell`: `-1.77%`

这说明卖出规则强依赖上下文，不能简单照搬。下一版应:

- 保留 `safety_deleveraging`。
- 保留 `post_entry_failure_exit`，但加上下文限制。
- 将 `profit_giveback_exit` 转为观察信号，不直接卖。
- 将 `replacement_opportunity_exit` 转为观察信号，只有 replacement edge 显著且风险更低时执行。
- `normal_sell` 要拆分为目标权重漂移、风险缩权、alpha 衰减，不要混在一个 reason。

## 6. 概率校准结论

全局 `p_win` 仍不可信:

- 多数模块 `p_win_10d_ece > 0.06`
- 多数模块 best Wilson lower < `0.50`
- `breakout_only` 是唯一 best Wilson lower 超过 50% 的模块

但高概率桶有局部使用价值:

| 模块 | 桶 | 样本 | 真实胜率 | Wilson lower | expectancy |
|---|---:|---:|---:|---:|---:|
| `breakout_only` | `60-65%` | `91` | `60.44%` | `50.17%` | `+3.18%` |
| `breakout_only` | `65%+` | `260` | `51.54%` | `45.49%` | `+1.47%` |
| `orderflow_only` | `65%+` | `444` | `51.58%` | `46.93%` | `+2.01%` |
| `full_mainline` | `65%+` | `143` | `55.24%` | `47.06%` | `+2.95%` |

因此下一版概率层应降级:

```text
禁止: p_win 直接控制仓位
允许: breakout 高桶作为买入过滤器
允许: p_win 高桶作为候选优先级排序
必须: 每次输出 ECE / Wilson / Brier / bucket expectancy
```

## 7. 风险集中结论

风险集中是进入高仓位前必须修的硬问题。

风险贡献异常:

- `reversal_only`: max risk contribution `100%`
- `core_minus_orderflow`: `100%`
- `full_mainline_control`: `100%`
- `core_plus_probability`: `79.61%`
- `breakout_only`: `41.72%`

典型异常日期:

- `2024-11-01`, `full_mainline_control`, `sz003816`, risk contribution `100%`
- `2024-04-15`, `reversal_only`, `sh600516`, risk contribution `100%`
- `2023-02-10`, `core_minus_orderflow`, `sh600256`, risk contribution `100%`
- `2024-03-14`, `core_plus_probability`, `sh600007`, risk contribution `79.61%`

下一版风险约束:

```text
if top1_risk_contribution > 0.35:
    block_new_buy_for_offender
    shrink_target_weight

if top1_risk_contribution > 0.50:
    forced_trim_to_risk_budget

if top5_risk_contribution_sum > 0.80 and holding_count < 8:
    disallow_catchup_buy

if risk_symbol_count <= 4:
    max_total_exposure <= 30%-40%
```

## 8. 与外部资料框架的合理性校验

### 8.1 MIT / Markowitz / portfolio theory

MIT OCW 的 portfolio theory 课程强调组合收益风险应由均值、方差、相关性共同决定，组合风险不能只看单票收益或持仓数量，而要看协方差结构和组合整体方差。MIT 15.401 课件也指出多股票组合的风险会由股票间平均协方差主导。[MIT OCW Portfolio Theory](https://ocw.mit.edu/courses/15-401-finance-theory-i-fall-2008/pages/video-lectures-and-slides/portfolio-theory/), [MIT 15.401 Risk Analytics PDF](https://ocw.mit.edu/courses/15-401-finance-theory-i-fall-2008/dd628e151309a7f23962b1a31b9356e5_MIT15_401F08_lec13.pdf)

这支持本次方案中的 `top risk contribution` 硬约束。当前 `reversal_only` 和 `full_mainline` 出现单票风险贡献 `100%`，不能仅凭回撤低就进入高仓位。

### 8.2 Princeton ORFE / optimization and risk management

Princeton ORFE 公开研究方向强调 portfolio optimization、risk management、stochastic optimization、convex analysis 等工具在金融工程中的核心地位。[Princeton ORFE Research](https://orfe.princeton.edu/research), [Princeton Financial Mathematics](https://orfe.princeton.edu/research/financial-mathematics)

这支持把仓位追赶从“想买多少”改成“在风险约束下优化配置”。即先解决 `w.T @ Sigma @ w` 和 risk contribution，再谈 70%-100% 仓位。

### 8.3 Stanford CME 241 / sequential decision and trading

Stanford CME 241 将金融交易、资产配置、执行等问题建模为序列决策问题。[Stanford CME 241](https://cme241.github.io/), [Stanford Bulletin CME 241](https://bulletin.stanford.edu/courses/2207331)

这支持本次的三段式买入:

```text
starter -> confirm add -> high conviction
```

而不是一次性满仓。当前数据也证明，同一个卖出规则在 `complex_exit` 和 `full_mainline` 中表现不同，说明策略状态上下文很重要。

### 8.4 Oxford Mathematical and Computational Finance

Oxford MSc in Mathematical and Computational Finance 强调 stochastic calculus、numerical methods、financial computing 等核心训练。[Oxford MCF](https://www.ox.ac.uk/admissions/graduate/courses/msc-mathematical-and-computational-finance)

这支持本方案强调数值验证和风控口径，而不是主观凭经验调阈值。当前概率层 ECE / Wilson 不达标，所以不应直接作为仓位公式。

### 8.5 AQR / trend and style evidence

趋势跟随和动量在长期多市场中有证据基础，但也存在状态依赖、崩溃和成本问题。AQR 相关趋势跟随研究和 time-series momentum 框架支持“趋势有效但不能无条件作为买点”。[AQR trend-following evidence overview](https://www.aqr.com/Insights/Research/White-Papers/A-Century-of-Evidence-on-Trend-Following-Investing), [Moskowitz/Ooi/Pedersen Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)

本次数据正好符合这一点: `trend_only` 持仓收益可观，但买入 10 日 expectancy 为负，因此 trend 更适合做持有过滤，不适合作为唯一买入触发。

### 8.6 Probability calibration literature

概率预测必须用 calibration、Brier score、reliability curve、ECE 等验证。Guo et al. 对概率校准的研究和 Brier score 框架支持“未经校准的概率不能直接驱动仓位”。[Guo et al. Calibration](https://arxiv.org/abs/1706.04599), [Brier score](https://en.wikipedia.org/wiki/Brier_score)

本次多数模块 `p_win_10d_ece > 0.06`，best Wilson lower 多数低于 50%，因此当前 `p_win` 只能作为高桶过滤器，不应作为仓位控制器。

### 8.7 Ledoit-Wolf covariance shrinkage

Ledoit-Wolf 协方差收缩用于缓解样本协方差在高维组合优化中的不稳定问题。[Ledoit-Wolf covariance shrinkage](https://arxiv.org/abs/1207.5322)

这支持继续强化协方差风险模型，但本次结果也说明仅有协方差模型还不够，必须加入硬门槛和异常降级逻辑。

### 8.8 Backtest overfitting / DSR / PBO

Bailey 和 Lopez de Prado 的 Deflated Sharpe Ratio / PBO 框架强调多次试验和策略选择容易过拟合。[Deflated Sharpe Ratio](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio)

这提醒本次不能直接因为 `orderflow_only` 最强就满仓上主线。正确做法是先把它作为候选池模块，再用后续窗口和固定诊断 suite 验证。

## 9. 完整落地方案

### 9.1 主线结构重建

将当前 `president_core_bundle` 的 23 因子 reputation 混合，改为分层角色:

```text
候选池层:
    orderflow_amount_shock
    orderflow_close_drive
    orderflow_accumulation
    orderflow_efficiency
    eod_close_strength

买入确认层:
    mean_reversion
    rsi_reversal
    kdj_oversold_cross
    low_volume_pullback
    consecutive_decline_rebound

入场概率过滤层:
    price_volume_breakout
    turtle_breakout
    limit_up_follow
    ma_break

持有/过滤层:
    momentum
    mom_lowvol
    macd_trend
    ma_cross
    macd_cross

风险层:
    safety
    covariance risk contribution
    liquidity
    concentration
```

### 9.2 买入逻辑

建议新买入条件:

```text
candidate_pool_pass =
    orderflow_rank_top
    or orderflow_65pct_bucket

entry_quality_pass =
    reversal_confirmed
    and breakout_bucket in {60-65%, 65%+}
    and expected_edge_after_cost > 0

risk_pass =
    top1_risk_contribution_after_buy <= 0.35
    and top5_risk_contribution_after_buy <= 0.80
    and liquidity_ok

buy =
    candidate_pool_pass
    and entry_quality_pass
    and risk_pass
```

仓位:

```text
starter: 1%-2%
confirmed_add: 1%-3%
high_conviction: 3%-5%
单票账户上限: 6%-8%
```

### 9.3 卖出逻辑

下一版主线先使用简化卖出:

```text
hard exits:
    safety_deleveraging
    liquidity_hard_exit
    alpha_collapse_consensus only if forward diagnostic remains positive

conditional exits:
    post_entry_failure_exit only when:
        entry age >= 5
        MFE < 2%
        unrealized < -2%
        reversal and breakout both fail

observe-only:
    profit_giveback_exit
    replacement_opportunity_exit
```

`profit_giveback_exit` 和 `replacement_opportunity_exit` 在本次数据中不稳定，先不要主动执行。

### 9.4 概率层

概率层从“仓位控制器”降级为“过滤器”:

```text
禁止:
    p_win 直接提高 exposure cap
    p_win 直接触发 catchup

允许:
    breakout 高桶提高候选排序
    p_win bucket 作为二级过滤

上线条件:
    ECE <= 0.06
    best Wilson lower >= 0.50
    bucket expectancy > 0
    Brier 不恶化
```

### 9.5 风险约束

新增硬约束:

```text
top1_risk_contribution > 0.35:
    block new buy for offender
    shrink target weight

top1_risk_contribution > 0.50:
    forced trim

top5_risk_contribution_sum > 0.80 and holding_count < 8:
    block catchup

risk_symbol_count <= 4:
    exposure_cap <= 0.40
```

### 9.6 状态机

状态机暂时降级:

```text
不再:
    主动提高买入分
    主动提高仓位上限

保留:
    bear/crisis 降低 cap
    liquidity stress 降低 cap
    rebound 只作为报告维度，不作为加仓理由
```

### 9.7 Reputation 权重

当前不建议用 23 因子 reputation 直接混合。下一版:

```text
module weight first, factor weight second

orderflow: candidate score
reversal: entry score
breakout: probability gate
trend: hold filter
risk: cap only
```

只有模块自身在增强诊断中通过后，才允许进入主线权重。

## 10. 验收标准

下一版代码跑同一套 enhanced diagnostics 后，至少要满足:

- `full_mainline_control` 或新主线账户收益 > `core_base`
- 新主线持仓组合收益 > `core_base`
- 新主线买入 10 日 expectancy > 0
- `p_win_10d_ece <= 0.06`
- best Wilson lower >= 0.50 或至少 breakout 高桶稳定通过
- max risk contribution <= 0.35
- `complex_exit` 不再显著拖累
- `full_mainline_control` 不再依靠低仓位防守获得表面低回撤

## 11. 当前最重要的行动

不要继续直接跑普通主线。下一步应改代码:

1. 拆分因子角色，不再 23 因子直接 reputation 混合。
2. 买入端改为 `orderflow candidate + reversal confirm + breakout probability gate`。
3. 概率层降级为过滤器。
4. 复杂卖出降级为观察。
5. 风险贡献加硬门槛。
6. 再跑同一套 Enhanced module diagnostics 验证。

本次数据已经足够支撑进入策略修改阶段。
