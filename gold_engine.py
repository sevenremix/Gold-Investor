# -*- coding: utf-8 -*-
"""
Gold ETF Smart Router — Backend Engine (gold_engine.py)
=====================================================
Two-Layer quantitative allocation model for cross-market gold ETF routing.

Layer 1 (Position Sizing): TIPS Yield + Momentum → how much capital to deploy
Layer 2 (Vehicle Routing):  FX + SGE Premium + Friction → IAUM vs 518660 split

Design principle: ZERO Streamlit dependency. Pure data + math.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Tuple, List, Any

# ============================================================================
#  Configuration
# ============================================================================

@dataclass
class StrategyConfig:
    """All tunable strategy parameters. Persisted as strategy_config.json."""

    # --- Layer 1: Position Sizing thresholds ---
    tips_neutral: float = 1.5       # TIPS yield considered "neutral" (%)
    tips_range: float = 2.0         # Range for normalization (%)
    sizing_tips_weight: float = 0.6
    sizing_momentum_weight: float = 0.4
    rsi_blend: float = 0.6          # RSI weight in momentum composite
    j_blend: float = 0.4            # KDJ-J weight in momentum composite

    # --- Layer 2: Vehicle Routing weights ---
    weight_fx: int = 40
    weight_sge: int = 40
    weight_friction: int = 20

    # --- Normalization clipping ---
    cnh_ma_period: int = 200
    sge_clip_min: float = -3.0      # SGE premium clip lower bound (%)
    sge_clip_max: float = 5.0       # SGE premium clip upper bound (%)
    friction_clip: float = 2.0      # ±% clip for 518660 friction
    fx_dev_clip: float = 5.0        # ±% clip for FX deviation

    # --- Hard override thresholds ---
    sge_high_override: float = 4.0  # Force 100% IAUM above this SGE premium
    sge_low_override: float = -1.5  # Force 100% 518660 below this SGE premium
    rsi_overbought: float = 85.0
    rsi_oversold: float = 20.0
    j_overbought: float = 100.0
    j_oversold: float = -10.0

    # --- Friction cost ---
    fx_swap_cost_pct: float = 0.4   # CNY→USD换汇点差损耗 (%)

    @classmethod
    def load(cls, path: str) -> "StrategyConfig":
        """Load config from a JSON file. Returns defaults if file not found."""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError) as e:
                print(f"[WARN] Config load failed ({e}), using defaults.")
        return cls()

    def save(self, path: str) -> None:
        """Persist current config to JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4, ensure_ascii=False)


# ============================================================================
#  Market Data
# ============================================================================

@dataclass
class MarketData:
    """
    Raw market data snapshot — all prices and indicators needed by the engine.

    In MVP mode these are manually entered via UI.
    Future: plug in real API calls (e.g., Yahoo Finance, akshare, FRED).
    """
    # --- Prices ---
    price_518660: float = 0.0   # 工银黄金ETF 现价 (CNY)
    iopv_518660: float = 0.0    # 518660 盘中参考净值 IOPV (CNY)
    price_iaum: float = 0.0     # iShares Gold Trust Micro 现价 (USD)
    xau_usd: float = 0.0       # 国际现货金价 XAU/USD
    sge_au9999: float = 0.0    # 上海金交所 Au9999 现货价 (CNY/克)

    # --- FX ---
    usd_cnh: float = 0.0       # 离岸人民币汇率
    usd_cnh_ma200: float = 0.0 # USD/CNH 200日均线 (用户输入或API)

    # --- Macro ---
    tips_yield: float = 0.0    # 美国10年期TIPS收益率 DFII10 (%)
    us10y: float = 0.0         # 美国10年期国债名义收益率 DGS10 (%) - Ref Only
    bei_history: Any = None    # 历史 BEI 数据 (DataFrame 用于绘图)
    bei_slope_60d: float = 0.0 # BEI 的 60 日线性回归斜率
    bei_t_stat_60d: float = 0.0 # BEI 60天回归斜率的 t-statistic

    # --- Technicals ---
    rsi_14: float = 50.0       # XAU/USD RSI(14)
    kdj_j: float = 50.0        # XAU/USD KDJ的J值
    
    # --- Reference Indices ---
    ndx_spot: float = 0.0      # Nasdaq 100 Index Spot Value


# ============================================================================
#  Derived Metrics
# ============================================================================

@dataclass
class DerivedMetrics:
    """Intermediate calculations from raw MarketData."""
    sge_premium_pct: float = 0.0     # 沪伦溢价率 (%)
    sge_premium_usd_oz: float = 0.0  # 沪伦价差 (USD/oz)
    friction_518660_pct: float = 0.0 # 518660 场内折溢价率 (%)
    fx_deviation_pct: float = 0.0    # USD/CNH 偏离MA200 (%)
    xau_cny_intl: float = 0.0       # 国际金价折合人民币 (CNY/克)


def compute_derived(data: MarketData) -> DerivedMetrics:
    """
    Calculate derived metrics from raw market data.

    沪伦溢价率 = (SGE Au9999 / 国际金价折合CNY - 1) × 100
    场内折溢价率 = (518660现价 / IOPV - 1) × 100
    FX偏离率 = (USD/CNH现价 / MA200 - 1) × 100
    """
    m = DerivedMetrics()

    # 国际金价折合人民币/克: XAU/USD × USD/CNH / 31.1035
    if data.xau_usd > 0 and data.usd_cnh > 0:
        m.xau_cny_intl = data.xau_usd * data.usd_cnh / 31.1035
    else:
        m.xau_cny_intl = 0.0

    # 沪伦溢价率 & 具体价差 (USD/oz)
    if m.xau_cny_intl > 0 and data.sge_au9999 > 0:
        m.sge_premium_pct = (data.sge_au9999 / m.xau_cny_intl - 1) * 100
    else:
        m.sge_premium_pct = 0.0
        
    sge_usd_oz = data.sge_au9999 * 31.1034768 / data.usd_cnh if data.usd_cnh > 0 else 0
    if sge_usd_oz > 0 and data.xau_usd > 0:
        m.sge_premium_usd_oz = sge_usd_oz - data.xau_usd
    else:
        m.sge_premium_usd_oz = 0.0

    # 518660 场内折溢价率
    if data.iopv_518660 > 0 and data.price_518660 > 0:
        m.friction_518660_pct = (data.price_518660 / data.iopv_518660 - 1) * 100
    else:
        m.friction_518660_pct = 0.0

    # FX偏离率
    if data.usd_cnh_ma200 > 0 and data.usd_cnh > 0:
        m.fx_deviation_pct = (data.usd_cnh / data.usd_cnh_ma200 - 1) * 100
    else:
        m.fx_deviation_pct = 0.0

    return m


# ============================================================================
#  Normalization Helpers
# ============================================================================

def _clip(value: float, lo: float, hi: float) -> float:
    """Clip value to [lo, hi]."""
    return max(lo, min(hi, value))


def _linear_scale(value: float, lo: float, hi: float) -> float:
    """Linear map value from [lo, hi] to [-1, +1]. Clips input first."""
    value = _clip(value, lo, hi)
    mid = (lo + hi) / 2
    half_range = (hi - lo) / 2
    if half_range == 0:
        return 0.0
    return (value - mid) / half_range


# ============================================================================
#  Allocation Result
# ============================================================================

@dataclass
class AllocationResult:
    """Complete output of the allocation engine."""

    # Layer 1 output
    tips_score: float = 0.0          # Normalized TIPS factor [-1, +1]
    momentum_score: float = 0.0      # Normalized momentum composite [-1, +1]
    sizing_score: float = 0.0        # Combined sizing signal
    position_multiplier: float = 1.0 # Final position sizing [0, 1.5]

    # Layer 2 output
    f2_fx: float = 0.0              # Normalized FX factor [-1, +1]
    f3_sge: float = 0.0             # Normalized SGE premium factor [-1, +1]
    f4_friction: float = 0.0        # Normalized friction factor [-1, +1]
    routing_score: float = 0.0      # R = W2·F2 + W3·F3 + W4·F4

    # Allocation
    iaum_pct: float = 50.0
    a518660_pct: float = 50.0

    # Overrides
    override_triggered: bool = False
    override_reason: str = ""

    # Sizing gate
    sizing_gate: str = "NORMAL"     # NORMAL / OVERBOUGHT_REDUCE / OVERSOLD_BOOST / NO_BUY

    @property
    def total_score(self) -> float:
        return self.routing_score


# ============================================================================
#  Core Allocation Engine
# ============================================================================

class GoldAllocator:
    """
    Two-layer gold ETF allocation engine.

    Layer 1 — Position Sizing: TIPS + Momentum → deploy X% of capital
    Layer 2 — Vehicle Routing: FX + SGE + Friction → IAUM vs 518660 split
    """

    def __init__(self, config: StrategyConfig):
        self.cfg = config

    def allocate(self, data: MarketData) -> Tuple[AllocationResult, DerivedMetrics]:
        """
        Main entry point. Takes raw market data, returns allocation decision.

        Returns:
            (AllocationResult, DerivedMetrics)
        """
        derived = compute_derived(data)
        result = AllocationResult()

        # ============================
        #  LAYER 1: Position Sizing
        # ============================

        # F1: TIPS Score — lower TIPS = more bullish gold = deploy more
        # tips_score ∈ [-1, +1], positive when TIPS < neutral
        result.tips_score = _clip(
            (self.cfg.tips_neutral - data.tips_yield) / self.cfg.tips_range,
            -1.0, 1.0
        )

        # F5: Momentum composite
        rsi_norm = (data.rsi_14 - 50) / 50   # [-1, +1]
        j_norm = _clip((data.kdj_j - 50) / 50, -1.0, 1.0)
        result.momentum_score = (
            self.cfg.rsi_blend * rsi_norm +
            self.cfg.j_blend * j_norm
        )

        # Sizing score: positive = bullish → deploy more
        # TIPS positive (gold bullish) + momentum negative (oversold) = max deploy
        result.sizing_score = (
            self.cfg.sizing_tips_weight * result.tips_score +
            self.cfg.sizing_momentum_weight * (-result.momentum_score)
        )

        result.position_multiplier = _clip(1.0 + result.sizing_score * 0.5, 0.5, 1.5)

        # --- Hard sizing gates ---
        if (data.rsi_14 > self.cfg.rsi_overbought and
                data.kdj_j > self.cfg.j_overbought):
            result.position_multiplier = 0.0
            result.sizing_gate = "NO_BUY"
        elif (data.rsi_14 < self.cfg.rsi_oversold and
              data.kdj_j < self.cfg.j_oversold):
            result.position_multiplier = 1.5
            result.sizing_gate = "OVERSOLD_BOOST"
        elif result.momentum_score > 0.7:
            result.sizing_gate = "OVERBOUGHT_REDUCE"
        else:
            result.sizing_gate = "NORMAL"

        # ============================
        #  LAYER 2: Vehicle Routing
        # ============================

        # F2: FX deviation — positive = CNH weak → favor IAUM
        result.f2_fx = _linear_scale(
            derived.fx_deviation_pct,
            -self.cfg.fx_dev_clip,
            self.cfg.fx_dev_clip
        )

        # F3: SGE premium — positive premium → 518660 expensive → favor IAUM
        # NOTE: We invert the sign so that high SGE premium → positive F3 → favor IAUM
        result.f3_sge = _linear_scale(
            derived.sge_premium_pct,
            self.cfg.sge_clip_min,
            self.cfg.sge_clip_max
        )

        # F4: 518660 friction — positive = at premium → favor IAUM
        result.f4_friction = _linear_scale(
            derived.friction_518660_pct,
            -self.cfg.friction_clip,
            self.cfg.friction_clip
        )

        # Routing score: R > 0 → favor IAUM; R < 0 → favor 518660
        result.routing_score = (
            self.cfg.weight_fx * result.f2_fx +
            self.cfg.weight_sge * result.f3_sge +
            self.cfg.weight_friction * result.f4_friction
        )

        # Allocation split
        result.iaum_pct = _clip(50 + result.routing_score / 2, 0, 100)
        result.a518660_pct = 100 - result.iaum_pct

        # ============================
        #  HARD OVERRIDES
        # ============================

        # Override 1: Extreme SGE premium → force IAUM
        if derived.sge_premium_pct > self.cfg.sge_high_override:
            result.iaum_pct = 100.0
            result.a518660_pct = 0.0
            result.override_triggered = True
            result.override_reason = (
                f"沪伦溢价 {derived.sge_premium_pct:.2f}% > {self.cfg.sge_high_override}% "
                f"→ 强制 100% IAUM (境内黄金溢价过高)"
            )

        # Override 2: SGE discount → force 518660
        elif derived.sge_premium_pct < self.cfg.sge_low_override:
            result.iaum_pct = 0.0
            result.a518660_pct = 100.0
            result.override_triggered = True
            result.override_reason = (
                f"沪伦溢价 {derived.sge_premium_pct:.2f}% < {self.cfg.sge_low_override}% "
                f"→ 强制 100% 518660 (罕见折价套利机会)"
            )

        return result, derived

    def generate_report(self, data: MarketData, result: AllocationResult,
                        derived: DerivedMetrics) -> str:
        """Generate a human-readable Chinese-language allocation report."""

        lines = [
            "=" * 60,
            "  📊 黄金 ETF 智能路由配置建议",
            "=" * 60,
            "",
            "【原始市场数据】",
            f"  518660 现价:    {data.price_518660:.4f} CNY",
            f"  518660 IOPV:    {data.iopv_518660:.4f} CNY",
            f"  IAUM 现价:      ${data.price_iaum:.4f} USD",
            f"  XAU/USD:        ${data.xau_usd:.2f}",
            f"  SGE Au9999:     ¥{data.sge_au9999:.2f}/克",
            f"  USD/CNH:        {data.usd_cnh:.4f}",
            f"  USD/CNH MA200:  {data.usd_cnh_ma200:.4f}",
            f"  TIPS Yield:     {data.tips_yield:.2f}%",
            f"  US10Y (Ref):    {data.us10y:.2f}%",
            f"  RSI(14):        {data.rsi_14:.1f}",

            f"  KDJ-J:          {data.kdj_j:.1f}",
            "",
            "【衍生指标】",
            f"  国际金价(CNY/克):  ¥{derived.xau_cny_intl:.2f}",
            f"  沪伦溢价率:        {derived.sge_premium_pct:+.2f}%",
            f"  沪伦价差(美元):    ${derived.sge_premium_usd_oz:+.2f}/oz",
            f"  518660 折溢价率:   {derived.friction_518660_pct:+.2f}%",
            f"  FX偏离MA200:       {derived.fx_deviation_pct:+.2f}%",
            "",
            "── Layer 1: 仓位管理 ──────────────────",
            f"  TIPS因子:    {result.tips_score:+.3f}",
            f"  动量因子:    {result.momentum_score:+.3f}",
            f"  仓位系数:    {result.position_multiplier:.2f}x",
            f"  仓位状态:    {result.sizing_gate}",
            "",
            "── Layer 2: 路由决策 ──────────────────",
            f"  F2(FX):      {result.f2_fx:+.3f} × {self.cfg.weight_fx} = {result.f2_fx * self.cfg.weight_fx:+.1f}",
            f"  F3(SGE):     {result.f3_sge:+.3f} × {self.cfg.weight_sge} = {result.f3_sge * self.cfg.weight_sge:+.1f}",
            f"  F4(摩擦):    {result.f4_friction:+.3f} × {self.cfg.weight_friction} = {result.f4_friction * self.cfg.weight_friction:+.1f}",
            f"  路由总分 R:  {result.routing_score:+.1f} (>0 偏向IAUM, <0 偏向518660)",
            "",
        ]

        if result.override_triggered:
            lines.append(f"  ⚠️  硬性覆盖: {result.override_reason}")
            lines.append("")

        lines.extend([
            "══════════════════════════════════════════",
            f"  🎯 配置建议:  IAUM {result.iaum_pct:.0f}%  |  518660 {result.a518660_pct:.0f}%",
            f"  📏 仓位系数:  {result.position_multiplier:.2f}x (1.0=标准, 0=不买, 1.5=加码)",
            "══════════════════════════════════════════",
        ])

        if result.sizing_gate == "NO_BUY":
            lines.append("  🚫 当前动量极度超买，建议暂不建仓，等待回调信号。")

        return "\n".join(lines)


# ============================================================================
#  Markdown Data Logger
# ============================================================================

MD_HEADER = (
    "| Timestamp | 518660 | IOPV | IAUM | XAU/USD | Au9999 | USD/CNH | "
    "TIPS% | US10Y | RSI | J | SGE溢价% | 摩擦% | FX偏离% | R分 | 仓位系数 | "
    "IAUM% | 518660% | 覆盖 |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def log_to_markdown(
    path: str,
    data: MarketData,
    derived: DerivedMetrics,
    result: AllocationResult,
    timestamp: Optional[str] = None,
) -> None:
    """
    Append a timestamped row to the markdown data log file.

    Creates the file with headers if it doesn't exist.

    Args:
        path: Absolute path to gold_data_log.md
        data: Raw market data snapshot
        derived: Calculated derived metrics
        result: Allocation engine output
        timestamp: ISO-format timestamp string (auto-generated if None)
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Create file with header if it doesn't exist
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 黄金 ETF 智能路由 — 原始数据日志\n\n")
            f.write(MD_HEADER + "\n")

    override_flag = result.override_reason if result.override_triggered else "-"

    row = (
        f"| {timestamp} "
        f"| {data.price_518660:.4f} "
        f"| {data.iopv_518660:.4f} "
        f"| {data.price_iaum:.4f} "
        f"| {data.xau_usd:.2f} "
        f"| {data.sge_au9999:.2f} "
        f"| {data.usd_cnh:.4f} "
        f"| {data.tips_yield:.2f} "
        f"| {data.us10y:.2f} "
        f"| {data.rsi_14:.1f} "
        f"| {data.kdj_j:.1f} "
        f"| {derived.sge_premium_pct:+.2f} "
        f"| {derived.friction_518660_pct:+.2f} "
        f"| {derived.fx_deviation_pct:+.2f} "
        f"| {result.routing_score:+.1f} "
        f"| {result.position_multiplier:.2f} "
        f"| {result.iaum_pct:.0f} "
        f"| {result.a518660_pct:.0f} "
        f"| {override_flag} |"
    )

    with open(path, "a", encoding="utf-8") as f:
        f.write(row + "\n")


# ============================================================================
#  Demo / Smoke Test
# ============================================================================

def _run_demo():
    """Run 5 scenarios to verify the engine logic."""

    cfg = StrategyConfig()
    engine = GoldAllocator(cfg)

    scenarios = [
        ("场景1: 正常牛市 — TIPS低, 无溢价, CNH稳定",
         MarketData(
             price_518660=5.2000, iopv_518660=5.1950, price_iaum=52.10,
             xau_usd=3050.00, sge_au9999=720.00,
             usd_cnh=7.2500, usd_cnh_ma200=7.2200,
             tips_yield=0.80, rsi_14=55.0, kdj_j=60.0
         )),
        ("场景2: 正常熊市 — TIPS高, 超买",
         MarketData(
             price_518660=4.8000, iopv_518660=4.7900, price_iaum=48.00,
             xau_usd=2800.00, sge_au9999=660.00,
             usd_cnh=7.1500, usd_cnh_ma200=7.2000,
             tips_yield=2.50, rsi_14=88.0, kdj_j=105.0
         )),
        ("场景3: 沪伦溢价飙升 — SGE Premium > 4%",
         MarketData(
             price_518660=5.5000, iopv_518660=5.4800, price_iaum=50.00,
             xau_usd=2900.00, sge_au9999=700.00,
             usd_cnh=7.2000, usd_cnh_ma200=7.2000,
             tips_yield=1.20, rsi_14=60.0, kdj_j=65.0
         )),
        ("场景4: 恐慌崩盘(Bug2验证) — RSI<20, J<-10, CNH强, SGE正常",
         MarketData(
             price_518660=4.0000, iopv_518660=4.0100, price_iaum=40.00,
             xau_usd=2500.00, sge_au9999=585.00,
             usd_cnh=6.9000, usd_cnh_ma200=7.2000,
             tips_yield=1.00, rsi_14=15.0, kdj_j=-20.0
         )),
        ("场景5: 2026现实数据(Bug1验证) — TIPS=1.83, CNH=6.90",
         MarketData(
             price_518660=5.3500, iopv_518660=5.3400, price_iaum=53.00,
             xau_usd=3020.00, sge_au9999=710.00,
             usd_cnh=6.9000, usd_cnh_ma200=7.1000,
             tips_yield=1.83, rsi_14=52.0, kdj_j=48.0
         )),
    ]

    for title, data in scenarios:
        print(f"\n{'━' * 60}")
        print(f"  {title}")
        print(f"{'━' * 60}")
        result, derived = engine.allocate(data)
        report = engine.generate_report(data, result, derived)
        print(report)


if __name__ == "__main__":
    _run_demo()
