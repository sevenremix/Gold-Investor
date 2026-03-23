# -*- coding: utf-8 -*-
"""
Gold ETF Smart Router — Streamlit Dashboard (app.py)
====================================================
Frontend for the two-layer gold allocation engine.

Sections:
  - Sidebar: StrategyConfig editor (loads/saves JSON)
  - Main Top: Raw market data input + derived metrics display
  - Main Bottom: Allocation result with visual gauges

Run: streamlit run app.py
"""

import streamlit as st
import json
import os
from datetime import datetime
from gold_engine import (
    StrategyConfig,
    MarketData,
    DerivedMetrics,
    AllocationResult,
    GoldAllocator,
    compute_derived,
    log_to_markdown,
)
from data_fetcher import DataFetcher

# ============================================================================
#  Constants
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "strategy_config.json")
LOG_PATH = os.path.join(SCRIPT_DIR, "gold_data_log.md")

# ============================================================================
#  Page Config & Custom CSS
# ============================================================================

st.set_page_config(
    page_title="Gold ETF Smart Router",
    page_icon="🥇",
    layout="wide",
)

st.markdown("""
<style>
    /* ── Dark theme overrides ── */
    .stApp {
        background-color: #0b0f19;
    }

    /* ── Metric cards ── */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #151d2c 0%, #111827 100%);
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.5);
    }

    div[data-testid="stMetric"] label {
        color: #8892b0 !important;
        font-size: 0.78rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #e6f1ff !important;
        font-size: 1.4rem !important;
        font-weight: 700 !important;
    }

    /* ── Allocation gauge box ── */
    .alloc-box {
        background: linear-gradient(135deg, #1a1a2e 0%, #0a192f 100%);
        border: 2px solid #64ffda33;
        border-radius: 16px;
        padding: 28px 32px;
        margin: 12px 0;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    .alloc-title {
        color: #64ffda;
        font-size: 1.15rem;
        font-weight: 600;
        margin-bottom: 16px;
        letter-spacing: 1px;
    }
    .alloc-big {
        font-size: 2.2rem;
        font-weight: 800;
        color: #e6f1ff;
        line-height: 1.2;
    }
    .alloc-sub {
        font-size: 0.88rem;
        color: #8892b0;
        margin-top: 4px;
    }

    /* ── Override alert ── */
    .override-alert {
        background: linear-gradient(135deg, #ff6b3520 0%, #ff634720 100%);
        border-left: 4px solid #ff6347;
        border-radius: 8px;
        padding: 14px 20px;
        margin: 16px 0;
        color: #ffa07a;
        font-weight: 600;
    }

    /* ── Section headers ── */
    .section-hdr {
        color: #ccd6f6;
        font-size: 1.1rem;
        font-weight: 700;
        border-bottom: 2px solid #233554;
        padding-bottom: 8px;
        margin: 24px 0 16px 0;
        letter-spacing: 0.5px;
    }

    /* ── Sidebar styling ── */
    section[data-testid="stSidebar"] {
        background-color: #060910;
        border-right: 1px solid #111827;
    }

    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #64ffda !important;
        font-size: 0.95rem !important;
    }

    /* ── Progress bar colors ── */
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #64ffda, #00bcd4);
    }

    /* ── Button & Alert Overrides for Dark Mode ── */
    div[data-testid="stButton"] button {
        background-color: #1a1a2e !important;
        color: #64ffda !important;
        border: 1px solid #64ffda44 !important;
        border-radius: 8px !important;
        transition: all 0.3s ease;
    }
    div[data-testid="stButton"] button:hover {
        background-color: #64ffda22 !important;
        border-color: #64ffda !important;
    }

    /* Success box (st.success) override */
    div[data-testid="stNotification"] {
        background-color: rgba(22, 101, 52, 0.1) !important;
        border: 1px solid rgba(22, 101, 52, 0.3) !important;
        color: #4ade80 !important;
    }

    /* ── No-buy banner ── */

    .nobuy-banner {
        background: linear-gradient(135deg, #b71c1c33 0%, #d32f2f22 100%);
        border: 2px solid #ef5350;
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        margin: 16px 0;
    }
    .nobuy-text {
        color: #ef5350;
        font-size: 1.6rem;
        font-weight: 800;
    }

    /* ── Layer breakdown cards ── */
    .layer-card {
        background: #16213e;
        border: 1px solid #233554;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .layer-label {
        color: #64ffda;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .factor-row {
        display: flex;
        justify-content: space-between;
        padding: 4px 0;
        color: #a8b2d1;
        font-size: 0.88rem;
        border-bottom: 1px solid #233554;
    }
    .factor-val {
        font-weight: 600;
        color: #e6f1ff;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
#  Sidebar: Strategy Config Editor
# ============================================================================

def render_sidebar_config() -> StrategyConfig:
    """Render config editor in sidebar. Returns current config."""

    cfg = StrategyConfig.load(CONFIG_PATH)

    with st.sidebar:
        st.markdown("## ⚙️ Strategy Config")
        st.caption(f"`{os.path.basename(CONFIG_PATH)}`")

        with st.expander("🎯 Layer 1: Position Sizing", expanded=False):
            cfg.tips_neutral = st.number_input(
                "TIPS Neutral (%)", value=cfg.tips_neutral, step=0.1,
                format="%.2f", help="TIPS收益率中性水平")
            cfg.tips_range = st.number_input(
                "TIPS Range (%)", value=cfg.tips_range, step=0.1,
                format="%.2f", help="归一化范围")
            cfg.sizing_tips_weight = st.slider(
                "TIPS Weight", 0.0, 1.0, cfg.sizing_tips_weight, 0.05)
            cfg.sizing_momentum_weight = st.slider(
                "Momentum Weight", 0.0, 1.0, cfg.sizing_momentum_weight, 0.05)
            cfg.rsi_blend = st.slider(
                "RSI Blend", 0.0, 1.0, cfg.rsi_blend, 0.05)
            cfg.j_blend = st.slider(
                "J Blend", 0.0, 1.0, cfg.j_blend, 0.05)

        with st.expander("🔀 Layer 2: Routing Weights", expanded=False):
            cfg.weight_fx = int(st.number_input(
                "W(FX)", value=int(cfg.weight_fx), step=5,
                help="FX偏离权重"))
            cfg.weight_sge = int(st.number_input(
                "W(SGE)", value=int(cfg.weight_sge), step=5,
                help="沪伦溢价权重"))
            cfg.weight_friction = int(st.number_input(
                "W(Friction)", value=int(cfg.weight_friction), step=5,
                help="518660折溢价权重"))

        with st.expander("🔒 Hard Override Thresholds", expanded=False):
            cfg.sge_high_override = st.number_input(
                "SGE High Override (%)", value=cfg.sge_high_override, step=0.5,
                format="%.1f", help="溢价超过此值强制100% IAUM")
            cfg.sge_low_override = st.number_input(
                "SGE Low Override (%)", value=cfg.sge_low_override, step=0.5,
                format="%.1f", help="折价超过此值强制100% 518660")
            cfg.rsi_overbought = st.number_input(
                "RSI Overbought", value=float(cfg.rsi_overbought), step=1.0,
                format="%.0f")
            cfg.rsi_oversold = st.number_input(
                "RSI Oversold", value=float(cfg.rsi_oversold), step=1.0,
                format="%.0f")
            cfg.j_overbought = st.number_input(
                "J Overbought", value=float(cfg.j_overbought), step=5.0,
                format="%.0f")
            cfg.j_oversold = st.number_input(
                "J Oversold", value=float(cfg.j_oversold), step=5.0,
                format="%.0f")

        with st.expander("📐 Normalization Clips", expanded=False):
            cfg.sge_clip_min = st.number_input(
                "SGE Clip Min (%)", value=cfg.sge_clip_min, step=0.5,
                format="%.1f")
            cfg.sge_clip_max = st.number_input(
                "SGE Clip Max (%)", value=cfg.sge_clip_max, step=0.5,
                format="%.1f")
            cfg.friction_clip = st.number_input(
                "Friction Clip (±%)", value=cfg.friction_clip, step=0.5,
                format="%.1f")
            cfg.fx_dev_clip = st.number_input(
                "FX Dev Clip (±%)", value=cfg.fx_dev_clip, step=0.5,
                format="%.1f")
            cfg.fx_swap_cost_pct = st.number_input(
                "FX Swap Cost (%)", value=cfg.fx_swap_cost_pct, step=0.1,
                format="%.2f", help="CNY→USD换汇点差损耗")

        st.markdown("---")
        if st.button("💾 Save Config", use_container_width=True):
            cfg.save(CONFIG_PATH)
            st.success("Config saved!")
            st.rerun()

    return cfg


# ============================================================================
#  Main Area: Market Data Input
# ============================================================================

def render_market_data_input() -> MarketData:
    """Render manual market data input fields and return a MarketData instance."""

    st.markdown('<div class="section-hdr">📡 Raw Market Data Input</div>',
                unsafe_allow_html=True)

    # Initialize session state for market data defaults if not present
    if "mkt_data" not in st.session_state:
        st.session_state.mkt_data = MarketData(
            price_518660=5.3500, iopv_518660=5.3400, price_iaum=53.0000,
            xau_usd=3020.00, sge_au9999=710.00, usd_cnh=7.2500,
            usd_cnh_ma200=7.2200, tips_yield=1.83, us10y=4.25, rsi_14=52.0, kdj_j=48.0
        )


    # Fetch button row (Stretch mode)
    if st.button("🔄 Fetch Live Data", use_container_width=True, type="primary"):
        with st.spinner("Fetching data from yfinance, Akshare, FRED..."):
            fetcher = DataFetcher()
            # Pass current state as fallback so failed APIs keep previous values
            new_data = fetcher.fetch_all(fallback_data=st.session_state.mkt_data)
            
            # Update the dataclass
            st.session_state.mkt_data = new_data
            
            # CRITICAL: Streamlit widgets with 'key' ignore 'value=' changes on re-runs.
            # We MUST overwrite the exact session_state keys to force the UI to update.
            st.session_state["price_518660"] = float(new_data.price_518660)
            st.session_state["iopv_518660"] = float(new_data.iopv_518660)
            st.session_state["price_iaum"] = float(new_data.price_iaum)
            st.session_state["xau_usd"] = float(new_data.xau_usd)
            st.session_state["sge_au9999"] = float(new_data.sge_au9999)
            st.session_state["usd_cnh"] = float(new_data.usd_cnh)
            st.session_state["usd_cnh_ma200"] = float(new_data.usd_cnh_ma200)
            st.session_state["tips_yield"] = float(new_data.tips_yield)
            st.session_state["us10y"] = float(getattr(new_data, 'us10y', 0.0))
            st.session_state["rsi_14"] = float(new_data.rsi_14)
            st.session_state["kdj_j"] = float(new_data.kdj_j)

            if fetcher.errors:
                st.warning("⚠️ Some APIs failed. Showing cached/fallback data for failed fields.")
                with st.expander("Show Details"):
                    for err in fetcher.errors:
                        st.write(f"- {err}")
            else:
                st.success("✅ All data fetched successfully!")



    data = MarketData()

    # --- Row 1: Macro & FX Basis (4 cols) ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        data.xau_usd = st.number_input(
            "XAU/USD 国际金价", step=1.00,
            format="%.2f", key="xau_usd")
    with col2:
        data.sge_au9999 = st.number_input(
            "Au9999 上金所 (CNY/克)", step=0.50,
            format="%.2f", key="sge_au9999")
    with col3:
        data.usd_cnh = st.number_input(
            "USD/CNH 离岸汇率", step=0.0010,
            format="%.4f", key="usd_cnh")
    with col4:
        data.usd_cnh_ma200 = st.number_input(
            "USD/CNH MA200", step=0.0010,
            format="%.4f", key="usd_cnh_ma200")

    # --- Row 2: Macro & Technicals (4 cols) ---
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        data.tips_yield = st.number_input(
            "TIPS Yield (%)", step=0.01,
            format="%.2f", key="tips_yield")
    with col6:
        data.us10y = st.number_input(
            "US10Y (Reference)", step=0.01,
            format="%.2f", key="us10y",
            help="10年期美债名义收益率，仅供参考，不参与分仓计算")
    with col7:
        data.rsi_14 = st.number_input(
            "RSI(14)", step=0.5,
            format="%.1f", key="rsi_14",
            min_value=0.0, max_value=100.0)
    with col8:
        data.kdj_j = st.number_input(
            "KDJ-J", step=1.0,
            format="%.1f", key="kdj_j")

    # --- Row 3: Execution Instruments (3 cols) ---
    col9, col10, col11 = st.columns(3)
    with col9:
        data.price_518660 = st.number_input(
            "518660 现价 (CNY)", step=0.0010,
            format="%.4f", key="price_518660")
    with col10:
        data.iopv_518660 = st.number_input(
            "518660 IOPV (CNY)", step=0.0010,
            format="%.4f", key="iopv_518660")
    with col11:
        data.price_iaum = st.number_input(
            "IAUM 现价 (USD)", step=0.0100,
            format="%.4f", key="price_iaum")


    return data


# ============================================================================
#  Main Area: Derived Metrics Display
# ============================================================================

def render_derived_metrics(derived: DerivedMetrics, data: MarketData):
    """Display derived metrics as metric cards."""

    st.markdown('<div class="section-hdr">📊 Derived Metrics & Prices</div>',
                unsafe_allow_html=True)

    # Row 1: prices side by side
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "国际金价 (USD/oz)", 
            f"${data.xau_usd:.2f}",
            delta=f"折合 ¥{derived.xau_cny_intl:.2f}/克",
            delta_color="off"
        )
    with col2:
        # Display both the % and the absolute USD/oz difference
        st.metric("沪伦溢价率 & 价差", f"{derived.sge_premium_pct:+.2f}%",
                   delta=f"${derived.sge_premium_usd_oz:+.2f}/oz价差",
                   delta_color="normal" if derived.sge_premium_pct > 0 else "inverse")
    with col3:
        st.metric("518660 折溢价", f"{derived.friction_518660_pct:+.2f}%",
                   delta=f"{derived.friction_518660_pct:+.2f}%",
                   delta_color="inverse")
    with col4:
        st.metric("FX偏离 MA200", f"{derived.fx_deviation_pct:+.2f}%",
                   delta=f"{derived.fx_deviation_pct:+.2f}%",
                   delta_color="inverse")


# ============================================================================
#  Main Area: Allocation Result
# ============================================================================

def render_allocation_result(result: AllocationResult, cfg: StrategyConfig):
    """Display the allocation decision with visual gauges."""

    st.markdown('<div class="section-hdr">🎯 Allocation Decision</div>',
                unsafe_allow_html=True)

    # --- NO BUY banner ---
    if result.sizing_gate == "NO_BUY":
        st.markdown("""
        <div class="nobuy-banner">
            <div class="nobuy-text">🚫 DO NOT BUY — 极度超买</div>
            <div style="color:#ef9a9a; margin-top:8px;">
                RSI 和 KDJ-J 同时触及极端超买区间，建议暂不建仓，等待回调信号。
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- Override alert ---
    if result.override_triggered:
        st.markdown(f"""
        <div class="override-alert">
            ⚠️ 硬性覆盖触发: {result.override_reason}
        </div>
        """, unsafe_allow_html=True)

    # --- Allocation gauge ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(f"""
        <div class="alloc-box">
            <div class="alloc-title">IAUM (美股/离岸)</div>
            <div class="alloc-big">{result.iaum_pct:.0f}%</div>
            <div class="alloc-sub">iShares Gold Trust Micro · TER 0.15% · USD</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(result.iaum_pct / 100)

    with col_right:
        st.markdown(f"""
        <div class="alloc-box">
            <div class="alloc-title">518660 (A股/在岸)</div>
            <div class="alloc-big">{result.a518660_pct:.0f}%</div>
            <div class="alloc-sub">工银黄金ETF · TER 0.20% · CNY</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(result.a518660_pct / 100)

    # --- Position multiplier ---
    sizing_color = {
        "NORMAL": "#64ffda",
        "OVERBOUGHT_REDUCE": "#ffab40",
        "OVERSOLD_BOOST": "#69f0ae",
        "NO_BUY": "#ef5350",
    }.get(result.sizing_gate, "#64ffda")

    st.markdown(f"""
    <div class="alloc-box" style="text-align:center;">
        <div class="alloc-title">Position Sizing Multiplier</div>
        <div class="alloc-big" style="color:{sizing_color};">{result.position_multiplier:.2f}x</div>
        <div class="alloc-sub">{result.sizing_gate} · 1.0=标准 / 0=不买 / 1.5=加码</div>
    </div>
    """, unsafe_allow_html=True)

    # --- Two-layer breakdown ---
    st.markdown('<div class="section-hdr">🔍 Factor Breakdown</div>',
                unsafe_allow_html=True)

    col_l1, col_l2 = st.columns(2)

    with col_l1:
        st.markdown(f"""
        <div class="layer-card">
            <div class="layer-label">Layer 1 — Position Sizing</div>
            <div class="factor-row" title="说明：实际利率得分。反映持有黄金的机会成本（负相）。&#10;公式：(TIPS_Neutral - TIPS_Current) / TIPS_Range">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">TIPS Factor (F₁)</span>
                <span class="factor-val">{result.tips_score:+.3f}</span>
            </div>
            <div class="factor-row" title="说明：动量情绪得分。反映金价超买超卖程度。负数极大值代表恐慌超卖。&#10;公式：(RSI_Norm × W_rsi) + (KDJ_Norm × W_kdj)">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">Momentum (F₅)</span>
                <span class="factor-val">{result.momentum_score:+.3f}</span>
            </div>
            <div class="factor-row" title="说明：综合买入意愿。正数代表看涨加仓，负数代表看跌减仓。&#10;公式：(F₁ × 0.6) - (F₅ × 0.4) 【注: 动量按反向算】">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">Sizing Score</span>
                <span class="factor-val">{result.sizing_score:+.3f}</span>
            </div>
            <div class="factor-row" style="border:none;" title="说明：最终仓位乘数。决定此笔交易购买的标准资金倍数。&#10;公式：1.0 + (Sizing Score × 0.5)">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">Multiplier</span>
                <span class="factor-val" style="color:{sizing_color}">{result.position_multiplier:.2f}x</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_l2:
        st.markdown(f"""
        <div class="layer-card">
            <div class="layer-label">Layer 2 — Vehicle Routing</div>
            <div class="factor-row" title="说明：汇率偏离。衡量换汇买美元资产风险。负数偏向国内防守。&#10;公式：(USD_CNH / MA200 - 1) × 100 线性映射">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">F₂ FX × {cfg.weight_fx}</span>
                <span class="factor-val">{result.f2_fx:+.3f} → {result.f2_fx * cfg.weight_fx:+.1f}</span>
            </div>
            <div class="factor-row" title="说明：沪伦溢价纠偏。衡量国内金价相对国际的溢价。负数偏向国内。&#10;公式：(Au9999 / 国际价折合人民币 - 1) × 100 线性映射">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">F₃ SGE × {cfg.weight_sge}</span>
                <span class="factor-val">{result.f3_sge:+.3f} → {result.f3_sge * cfg.weight_sge:+.1f}</span>
            </div>
            <div class="factor-row" title="说明：ETF场内摩擦。衡量518660盘口折溢价率。负数代表由于折价值得抄底国内。&#10;公式：(518660现价 / IOPV - 1) × 100 线性映射">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">F₄ Friction × {cfg.weight_friction}</span>
                <span class="factor-val">{result.f4_friction:+.3f} → {result.f4_friction * cfg.weight_friction:+.1f}</span>
            </div>
            <div class="factor-row" style="border:none;" title="说明：路由总分。决定资金如何在境内外分配。&#10;公式：R = F₂*W₂ + F₃*W₃ + F₄*W₄ (R>0偏向出海, R<0偏向留守本土)">
                <span style="cursor:help; border-bottom:1px dotted #8892b0;">Routing Score R</span>
                <span class="factor-val">{result.routing_score:+.1f}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)


# ============================================================================
#  Main Entry Point
# ============================================================================

def main():
    # --- Title ---
    st.markdown("""
    <div style="text-align:center; padding: 8px 0 24px 0;">
        <span style="font-size:2.2rem; font-weight:800; color:#e6f1ff;">
            🥇 Gold ETF Smart Router
        </span>
        <div style="color:#8892b0; font-size:0.92rem; margin-top:6px;">
            Cross-Market Allocation Engine · IAUM vs 518660 · Two-Layer Quantitative Model
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Sidebar Config ---
    cfg = render_sidebar_config()

    # --- Market Data Input ---
    data = render_market_data_input()

    # --- Compute ---
    engine = GoldAllocator(cfg)
    result, derived = engine.allocate(data)

    # --- Derived Metrics ---
    render_derived_metrics(derived, data)

    # --- Allocation Result ---
    render_allocation_result(result, cfg)

    # --- Log & Save Button ---
    st.markdown("---")
    col_log, col_time = st.columns([3, 1])

    with col_time:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.markdown(f"""
        <div style="text-align:right; color:#8892b0; padding-top:8px; font-size:0.85rem;">
            ⏱ {ts}
        </div>
        """, unsafe_allow_html=True)

    with col_log:
        if st.button("📝 Log Data & Save to MD", use_container_width=True):
            try:
                log_to_markdown(LOG_PATH, data, derived, result, ts)
                st.success(f"✅ Data logged at {ts} → `gold_data_log.md`")
            except Exception as e:
                st.error(f"❌ Failed to log: {e}")

    # --- Data Log Preview ---
    if os.path.exists(LOG_PATH):
        with st.expander("📋 View Data Log (gold_data_log.md)", expanded=False):
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                st.markdown(f.read())


if __name__ == "__main__":
    main()
