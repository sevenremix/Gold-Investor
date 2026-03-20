# USD/HKD 购汇策略模块设计方案

## 背景

当前策略已具备两层决策：
- **Layer 1（仓位管理）**：基于 TIPS + RSI/KDJ 决定总仓位大小
- **Layer 2（路由决策）**：基于 FX偏离、沪伦溢价、518660折价决定 IAUM 与 518660 的分仓比例

用户提出了一个关键洞察：当 **USD/CNH 负偏离 MA200** 时，存在两种对立但都有道理的操作哲学：
1. **趋势跟随**（现有策略）：RMB 强势中，不买美元，留在 518660
2. **均值回归**（购汇策略）：美元处于"打折"区间，正是低吸美元的窗口期

用户希望将第二种哲学作为 **独立的购汇时机参考** 融入系统中，并特别提出引入 **USD/HKD（美元兑港币）** 汇率来增强决策精度。

---

## 核心设计：Layer 3 — 购汇时机顾问（FX Timing Advisor）

### 为什么引入 USD/HKD？

港币实行联系汇率制度，与美元挂钩于 **7.75–7.85** 的官方波动区间。金管局（HKMA）会在触及边界时强制干预。这使得 USD/HKD 成为一个天然的**"美元温度计"**：

| USD/HKD 位置 | 金融含义 | 购汇信号 |
|:---|:---|:---|
| **≤ 7.76**（接近强方兑换保证） | 港币极强 / 美元极弱 / 套利资金涌入港币 | 🟢 **强烈买入美元** |
| **7.78–7.82**（中性区域） | 美元供需平衡 | 🟡 **中性** |
| **≥ 7.84**（接近弱方兑换保证） | 港币极弱 / 美元极强 / 资本外流香港 | 🔴 **不宜购汇** |

> [!IMPORTANT]
> USD/HKD 的核心优势：它是一个**有边界的、制度性保证的均值回归信号**。不像 USD/CNH（理论上可以无限贬值或升值），USD/HKD 被金管局"焊死"在一个 1.3% 的窄幅区间内，天然适合均值回归策略。

### 综合购汇评分模型

将 **USD/CNH 偏离度**（宏观趋势）与 **USD/HKD 区间位置**（微观制度套利）结合，构建一个双因子购汇评分：

```
购汇评分 = 0.5 × HKD区间分 + 0.5 × CNH均值回归分
```

#### 因子 1：HKD 区间分（Band Score）

```python
# USD/HKD 在 [7.75, 7.85] 区间内线性映射到 [+1, -1]
# 接近 7.75（强方） → +1（最佳购汇时机）
# 接近 7.85（弱方） → -1（避免购汇）
hkd_band_score = (7.80 - usd_hkd) / 0.05   # clip to [-1, +1]
```

#### 因子 2：CNH 均值回归分（Mean Reversion Score）

```python
# USD/CNH 偏离 MA200 的百分比
# 负偏离（美元便宜） → 正分（利于购汇）
# 正偏离（美元昂贵） → 负分（不利购汇）
# 注意：这里的正负号与 Layer 2 中的趋势跟随逻辑相反！
cnh_mr_score = -fx_deviation_pct / fx_dev_clip   # clip to [-1, +1]
```

#### 购汇建议信号

| 综合评分 | 信号灯 | 操作建议 |
|:---|:---|:---|
| **> +0.5** | 🟢 **强买** | 大额集中购汇，锁定低价美元 |
| **+0.2 ~ +0.5** | 🟡 **偏多** | 分批小额购汇 |
| **-0.2 ~ +0.2** | ⚪ **中性** | 维持原有计划，不主动加仓 |
| **< -0.2** | 🔴 **回避** | 暂缓购汇，等待更好窗口 |

---

## 数据源方案

| 数据 | 来源 | 接口 |
|:---|:---|:---|
| **USD/HKD 实时汇率** | Yahoo Finance | `yf.Ticker("HKD=X").fast_info.last_price` |
| **USD/CNH MA200** | FRED DEXCHUS | 已实现（当前系统） |
| **USD/CNH 实时** | Yahoo Finance / Sina | 已实现（当前系统） |

---

## 涉及文件变动

### 数据层 ([data_fetcher.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/data_fetcher.py))
- [MarketData](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_engine.py#83-108) 新增字段：`usd_hkd: float = 0.0`
- [_fetch_yfinance_quotes()](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/data_fetcher.py#121-147) 中新增 `HKD=X` 抓取逻辑

### 引擎层 ([gold_engine.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_engine.py))
- 新增 `FxTimingResult` 数据类（购汇评分、信号灯、建议文字）
- 新增 `compute_fx_timing()` 独立函数
- 保持 Layer 1 和 Layer 2 完全不变，购汇建议作为**并行输出**而非干扰现有路由

### 展示层 ([app.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/app.py))
- 在 Dashboard 底部新增一个**购汇信号卡片**：
  - 显示 USD/HKD 当前值与区间位置图
  - 显示综合购汇评分与信号灯
  - 显示一句话操作建议

---

## 关键设计原则

> [!WARNING]
> **Layer 3 不干预现有的 Layer 1/2 决策。** 它是一个独立的、并行输出的"购汇时机参考面板"。
> - Layer 1/2 回答："买多少黄金？用哪个通道？"（趋势跟随）
> - Layer 3 回答："此刻换美元划不划算？"（均值回归）
> 
> 两者哲学不同，但可以同时为用户提供不同维度的决策参考。

---

## 验证计划

### 自动化验证
- 运行 [data_fetcher.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/data_fetcher.py) 验证 USD/HKD 数据抓取正常
- 在 [gold_engine.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_engine.py) 的 [_run_demo()](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_engine.py#482-533) 中新增含 HKD 的测试场景
- 验证计算结果：当 USD/HKD=7.76 + CNH 负偏离 -3% 时，应得到 🟢 强买信号

### 手动验证
- 在本地 Streamlit 界面确认购汇信号卡片展示正确
- 对比实际 USD/HKD 行情与信号合理性
