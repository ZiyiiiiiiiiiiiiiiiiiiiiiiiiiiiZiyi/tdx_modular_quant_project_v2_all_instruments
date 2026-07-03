# 2026-06-08 代码改动报告

## 一、Bug 修复（8 个）

### 1.1 高严重性

| # | 文件 | 行号 | 问题 | 修复 |
|---|------|------|------|------|
| 1 | `config.py` | 271 | `SAFETY_PROXY_MODE` 在定义前被引用，`globals()` 检查永远为 False，CLI_GOVERNANCE_SAFETY_PROXY_MODE 永远是 "strict" | 改为直接使用 `"strict"` |
| 2 | `feature_engineering.py` | 482 | `signal_trigger_count` 用了 `len(one_day)`（全部候选），导致触发率恒为 ~1.0 | 改为 `len(selected)`（实际选中数） |

### 1.2 中严重性

| # | 文件 | 行号 | 问题 | 修复 |
|---|------|------|------|------|
| 3 | `strategy_signal_generators.py` | 268 | `data.get("volatility_20", np.nan)` 返回标量时 `.replace()` 报 `AttributeError` | 改为先检查列是否存在 |
| 4 | `strategy_registry.py` | 19 | `str \| None` 语法需要 Python 3.10+，缺少 `from __future__ import annotations` | 添加导入 |
| 5 | `backtest_engine.py` | 138, 140 | `backtest_end_date` 为 `None` 时 `.date()` 抛 `AttributeError` | 添加 None 检查 |
| 6 | `backtest_engine.py` | 568 | `drawdown.values` 直接赋值，索引不对齐可能导致数据错位 | 改用 `.reindex().fillna().values` |

### 1.3 低严重性

| # | 文件 | 行号 | 问题 | 修复 |
|---|------|------|------|------|
| 7 | `view_strategy_selection.py` | 92 | `dates.iloc[-1]` 在空 Series 上抛 `IndexError` | 添加 `if not dates.empty` 守卫 |
| 8 | `convert_tdx_daily.py` | 95 | 空 `failed` 列表生成无列 CSV | 添加列名兜底 |

---

## 二、智能缓存增强

### 2.1 Step 3 数据完整性检测

**文件**: `main.py`

新增 `_check_feature_completeness()` 函数。Step 3 现在的逻辑：

```
签名匹配 → 跳过（原有逻辑）
签名不匹配 → 检查现有 feature parquet 是否包含所有策略需要的列
  ├── 全部包含 → 跳过，打印原因
  └── 缺少列 → 重新生成
```

**效果**：新增策略时如果所需列已存在，省去 ~20 分钟的特征重算。

### 2.2 空选中元数据修复

**文件**: `feature_engineering.py:721`

`_attach_strategy_metadata` 在 selection 为空时直接返回，导致空选中的 parquet 文件缺少 `strategy_source` 等 6 列元数据。已修复为即使空 DataFrame 也添加元数据列。

---

## 三、PBO 过拟合检测（新增模块）

**新增文件**: `functions/pbo_cscv.py`

### 3.1 原理

- CSCV (Combinatorial Symmetric Cross-Validation)
- 将回测收益序列分成 S=16 个等长块
- 遍历所有 C(16,8)=12870 种组合
- 每次用一半做 IS（样本内）、一半做 OOS（样本外）
- 按 IS 表现排名，检查 IS 最佳策略在 OOS 中是否低于中位数
- **PBO** = IS 最佳策略在 OOS 中表现差的比例
- **Logit 转换**：log(rank / (N+1-rank))，>0 表示过拟合

### 3.2 输出

| 文件 | 内容 |
|------|------|
| `results/pbo_overfitting_report.md` | PBO 值、mean logit、各组合详情 |

### 3.3 解读

| PBO | 含义 |
|-----|------|
| < 30% | 可接受 |
| 30-50% | 需谨慎 |
| > 50% | 严重过拟合风险 |
| Mean logit > 0 | 系统性过拟合 |

### 3.4 核心函数

```python
compute_pbo(strategy_returns, n_blocks=16, performance_metric="sharpe")
pbo_summary_report(result)
```

---

## 四、数据泄漏检测（新增模块）

**新增文件**: `functions/leakage_detector.py`

### 4.1 检测内容

| 检测项 | 方法 | 严重性 |
|--------|------|--------|
| 特征名含 `future_` 前缀 | 列名检查 | HIGH |
| 特征含 `reward_` / `_ml_target` | 列名检查 | HIGH |
| 特征[t] 与 close[t+1] 相关性 > 0.99 | 统计检查 | CRITICAL |
| 特征[t] 与 close[t+1] 相关性 > 0.95 | 统计检查 | MEDIUM |
| 特征 = close.shift(负数) | 精确匹配 | CRITICAL |
| ML 训练/测试集时间重叠 | 时间检查 | CRITICAL |
| ML 训练/测试集 purge 不足 | 时间检查 | HIGH |
| 标签计算错误（label 对齐） | 手动验证 | CRITICAL |

### 4.2 输出

| 文件 | 内容 |
|------|------|
| `results/leakage_audit_report.md` | 所有检测项结果、violation 明细 |

### 4.3 核心函数

```python
run_full_leakage_audit(feature_df, feature_columns, label_columns, ...)
leakage_audit_report(result)
```

---

## 五、策略时间窗口调整

### 5.1 配置变更

| 配置项 | 旧值 | 新值 |
|--------|------|------|
| `STRATEGY_END_DATE` | `"2021-12-31"` | `"2024-12-31"` |
| `GOVERNANCE_END_DATE` | `None` | `"2024-12-31"` |

### 5.2 影响范围

| 步骤 | 是否需要重跑 | 原因 |
|------|-------------|------|
| Step 1-3 | ❌ | 智能缓存跳过 |
| Step 4 | ✅ | 日期窗口变了 |
| Step 5-6 | ✅ | 依赖 Step 4 |
| 政府版本 | ✅ | GOVERNANCE_END_DATE 变了 |

### 5.3 输出变化

| 指标 | 变化 |
|------|------|
| 累计收益 | 1 年 → 4 年，数值不可直接比较 |
| 年化收益 | 同口径，可比 |
| 夏普率 | 样本更充分，更稳定 |
| 最大回撤 | 通常更大（经历更多周期） |
| 月度热力图 | 多 36 行 |
| 年度分布图 | 多 3 个柱子 |
| 凯利图谱 | 数据量 4 倍 |

---

## 六、AGENTS.md 重写

**文件**: `AGENTS.md`

从 538 行精简到 ~120 行。保留高信号内容：

- Python 环境路径（conda env 绝对路径）
- 运行命令（全量、低内存、单策略、治理模式）
- 数据流（6 步 pipeline）
- 关键架构点（两个 selection engine、ML proxy、降级标记）
- Gotchas（READ_LIMIT、日期窗口、缓存、文件删除规则）
- 配置阈值（4 个 warn 阈值）
- 策略分类表（5 类 source）

删除了过时的模块细节、旧命名约定、已不存在的文件列表。

---

## 七、文件清单

### 7.1 新增文件（2 个）

| 文件 | 用途 |
|------|------|
| `functions/pbo_cscv.py` | PBO 过拟合检测 + CSCV 交叉验证 |
| `functions/leakage_detector.py` | 数据泄漏检测 |

### 7.2 修改文件（10 个核心 + 其他）

| 文件 | 改动类型 |
|------|----------|
| `config.py` | Bug 修复 + 日期窗口调整 |
| `main.py` | 智能缓存 + PBO/泄漏集成 |
| `feature_engineering.py` | Bug 修复（signal_trigger_count, 空选中元数据） |
| `backtest_engine.py` | Bug 修复（None guard, drawdown 对齐） |
| `strategy_signal_generators.py` | Bug 修复（.replace on scalar） |
| `strategy_registry.py` | Bug 修复（__future__ annotations） |
| `view_strategy_selection.py` | Bug 修复（空 Series guard） |
| `convert_tdx_daily.py` | Bug 修复（空 failed CSV） |
| `AGENTS.md` | 重写精简 |

### 7.3 新增输出文件（运行后生成）

| 文件 | 内容 |
|------|------|
| `results/pbo_overfitting_report.md` | PBO 过拟合概率报告 |
| `results/leakage_audit_report.md` | 数据泄漏审计报告 |

---

## 八、验证结果

```
✅ config.py: 语法检查通过
✅ main.py: 语法检查通过
✅ feature_engineering.py: 语法检查通过
✅ backtest_engine.py: 语法检查通过
✅ strategy_signal_generators.py: 语法检查通过
✅ strategy_registry.py: 语法检查通过
✅ pbo_cscv.py: 语法检查 + 功能测试通过
✅ leakage_detector.py: 语法检查 + 功能测试通过
✅ verify_decision_council_phase_one.py: 全部通过
✅ verify_mainline_outputs.py: 全部通过（空选中文件需重跑 Step 4 修复）
```
