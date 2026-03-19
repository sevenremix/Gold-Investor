# Cross-Market Gold ETF Smart Routing & Dynamic Allocation Strategy

## Background

An independent investor with dual onshore (CNY) and offshore (USD) capital channels seeks a disciplined, quantitative framework for allocating gold exposure between:

| Ticker | Name | Currency | TER | Domain |
|--------|------|----------|-----|--------|
| **518660** | 工银黄金 ETF (A-share) | CNY | 0.20%/yr | SGE-linked, contains SGE premium + sentiment premium |
| **IAUM** | iShares Gold Trust Micro | USD | 0.15%/yr | LBMA-linked, near-zero tracking error |

The strategy is **NOT** a short-term trading system. It is a **"smart order router"** that fires on two discrete events:
1. **New capital deployment** — fresh funds arrive; where to build the position?
2. **Extreme regime rebalance** — macro or sentiment extremes warrant a shift between vehicles.

---

## Strategy Core Logic

### Macro Quadrant Framework

The allocation decision lives in a 2×2 macro quadrant defined by two primary axes:

| | **TIPS Yield < 0.5% (Goldilocks/Easy)** | **TIPS Yield ≥ 0.5% (Restrictive)** |
|---|---|---|
| **CNH Weak (USD/CNH > 7.25)** | **Q1 — Strong IAUM bias.** Low real rates = gold tailwind; weak RMB makes FX conversion expensive → stay in USD. | **Q3 — Neutral / Reduce.** High real rates headwind for gold; weak RMB means no incentive to convert. Smallest allocation increment. |
| **CNH Strong (USD/CNH ≤ 7.25)** | **Q2 — Mixed, lean 518660.** Low real rates = gold tailwind; strong RMB means CNY→USD is cheap, but 518660 may carry SGE premium discount opportunity. | **Q4 — Cautious 518660 tilt.** High real rates = gold headwind; but strong RMB means 518660 offers FX-implicit hedge and potential SGE premium mean-reversion. |

### Five-Factor Scoring Model

We define a composite score **S** ∈ [-100, +100]:
- **S > 0** → favor **IAUM** (offshore USD channel)
- **S < 0** → favor **518660** (onshore CNY channel)
- **|S|** magnitude → conviction level → determines allocation split

#### Formula

```
S = W₁·F₁ + W₂·F₂ + W₃·F₃ + W₄·F₄ + W₅·F₅
```

#### Factor Definitions & Weights

| # | Factor | Symbol | Raw Input | Normalization | Polarity | Weight |
|---|--------|--------|-----------|---------------|----------|--------|
| 1 | **Macro Anchor** | F₁ | DFII10 (10Y TIPS Yield, %) | Clip to [-2, 3], linear map to [-1, +1] | **Negative** → lower TIPS = more bullish gold = bigger position overall; sign controls IAUM vs 518660 via interaction with F₂ | **W₁ = 25** |
| 2 | **FX Hedge** | F₂ | USD/CNH spot rate | Deviation from 200-day MA, clipped ±5%, scaled to [-1, +1] | **Positive** → CNH weaker than MA → favor IAUM (avoid FX loss); **Negative** → CNH stronger → favor 518660 | **W₂ = 25** |
| 3 | **Cross-Border Basis** | F₃ | SGE Premium % = (SGE Au9999 in CNY / (XAU_USD × USDCNH) - 1) × 100 | Clip to [-3, +5]%, map to [-1, +1] | **Negative** → high SGE premium → 518660 expensive → favor IAUM; **Positive** → SGE discount → 518660 cheap → favor 518660 | **W₃ = 25** |
| 4 | **Market Friction** | F₄ | 518660 intraday premium % = (Price / IOPV - 1) × 100 | Clip to [-2, +2]%, map to [-1, +1] | **Negative** → 518660 trading at premium → favor IAUM; **Positive** → 518660 at discount → favor 518660 | **W₄ = 10** |
| 5 | **Momentum Extremes** | F₅ | Composite of RSI(14) and KDJ-J for XAU/USD | See below | **Gate / Override** signal | **W₅ = 15** |

**F₅ Normalization Detail:**
```
RSI_norm = (RSI - 50) / 50          → [-1, +1]
J_norm   = clip((J - 50) / 50, -1, 1)  → [-1, +1]
F₅_raw   = 0.6 × RSI_norm + 0.4 × J_norm
```
- F₅ > 0 → momentum is hot / overbought → **reduce overall position size** (risk management)
- F₅ < 0 → momentum is cold / oversold → **increase overall position size** (opportunity)
- Polarity for IAUM vs 518660: F₅ is **routing-neutral** — it only scales total allocation size, not the split. But when F₅ is extreme (|F₅| > 0.7), it also **hard-overrides** the routing score toward IAUM (flight to quality / liquidity).

### Allocation Mapping

1. **Routing Score** `R = W₁·F₁ + W₂·F₂ + W₃·F₃ + W₄·F₄` (range [-85, +85])
2. **Momentum Gate** `M = W₅·F₅` (range [-15, +15])
3. **Total Score** `S = R + M`

**Allocation split:**
```
IAUM_pct = clip(50 + S/2, 0, 100)
518660_pct = 100 - IAUM_pct
```

**Position sizing via momentum:**
```
If F₅ > 0.7 (overbought):  deploy only 50% of intended capital
If F₅ < -0.7 (oversold):   deploy up to 150% of intended capital (use reserves)
Otherwise:                  deploy 100% of intended capital
```

**Hard override rules:**
1. If SGE Premium > 4% → force 100% IAUM (premium is irrational)
2. If SGE Premium < -1.5% → force 100% 518660 (rare discount, arbitrage)
3. If RSI > 85 AND J > 100 → **DO NOT BUY** (wait signal)
4. If RSI < 20 AND J < -10 → **MAXIMUM BUY** with 100% IAUM (panic = buy LBMA-linked)

---

## Proposed Changes

### [NEW] [gold_allocator.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_allocator.py)

A single-file, self-contained Python module (~350 lines) containing:

1. **`FactorInput` dataclass** — structured input for the 5 factors
2. **`normalize_*()` functions** — one per factor, with clipping and scaling
3. **`GoldAllocator` class** — the core engine:
   - `compute_score(factors: FactorInput) → ScoringResult`
   - `allocate(factors: FactorInput) → AllocationResult`
   - `generate_report(result: AllocationResult) → str`
4. **`AllocationResult` dataclass** — output with IAUM%, 518660%, position sizing, override flags, human-readable rationale
5. **`if __name__ == "__main__":` demo block** — runs 4 scenario simulations (bullish gold, bearish gold, SGE premium spike, panic crash)
6. Comprehensive docstrings and comments in **bilingual (English logic / Chinese context notes)**
7. No external dependencies beyond Python stdlib (uses only `dataclasses`, `enum`, `typing`)

---

## Verification Plan

### Automated Tests

Since this is a standalone quantitative model (not integrated into an existing codebase), verification will be done via:

1. **Scenario simulation** — run `python gold_allocator.py` directly; it will execute 4 hardcoded scenarios and print allocation results.
2. **Boundary condition checks** — embedded assertions in the demo block to verify:
   - Score clipping (S stays within [-100, +100])
   - Allocation percentages sum to 100%
   - Hard override triggers fire correctly
   - Position sizing gates work

```powershell
cd "e:\Google Drive Local\Investor\Glod Investor"
python gold_allocator.py
```

### Manual Verification

The user should:
1. Review the 4 scenario outputs and verify they match financial intuition
2. Plug in current real-world data points and validate the recommendation makes sense
3. Confirm the factor weights and hard override thresholds align with their risk appetite
