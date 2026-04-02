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
    st.caption(
        "数据源说明：**宏观基准** (TIPS, USD/CNH MA200) 取自 FRED API；**国际金实盘** (XAU/USD) 取自 Finnhub；"
        "**海外上市资产** (US10Y, IAUM, USD/CNH汇率) 取自 Yahoo Finance；**境内上市资产** (Au9999, 518660) 取自 Sina Finance。<br>"
        "⚡ **境内 ETF 实时净值 (IOPV) 估算公式**：<code>518660 IOPV = 基金 T-1 日净值 × (Au9999 实时盘口价 / Au9999 昨收盘价)</code><br>"
        "⚠️ *如果表单文本后方带有 <code>[异常]</code> 标识，代表该指标本次拉取失败，系统暂以当前表单所列数值作为降级缓存参与计算。*",
        unsafe_allow_html=True
    )

    # Initialize session state for market data defaults if not present
    if "mkt_data" not in st.session_state:
        st.session_state.mkt_data = MarketData(
            price_518660=5.3500, iopv_518660=5.3400, price_iaum=53.0000,
            xau_usd=3020.00, sge_au9999=710.00, usd_cnh=7.2500,
            usd_cnh_ma200=7.2200, tips_yield=1.83, us10y=4.25, rsi_14=52.0, kdj_j=48.0,
            ndx_spot=0.0
        )
    else:
        if not hasattr(st.session_state.mkt_data, "ndx_spot"):
            st.session_state.mkt_data.ndx_spot = 0.0
        if not hasattr(st.session_state.mkt_data, "us10y"):
            st.session_state.mkt_data.us10y = 4.30
            
    # Ensure individual widget keys exist for the first run to avoid 'key' vs 'value' conflict
    for k in ["xau_usd", "sge_au9999", "usd_cnh", "usd_cnh_ma200", "tips_yield", "us10y", "rsi_14", "kdj_j", "price_518660", "iopv_518660", "price_iaum", "ndx_spot"]:
        if k not in st.session_state:
            st.session_state[k] = float(getattr(st.session_state.mkt_data, k, 0.0))


    # Fetch button row (Stretch mode)
    if st.button("🔄 Fetch Live Data", use_container_width=True, type="primary"):
        with st.spinner("Fetching data from yfinance, Akshare, FRED..."):
            fetcher = DataFetcher()
            new_data = fetcher.fetch_all(fallback_data=st.session_state.mkt_data)
            st.session_state.mkt_data = new_data
            
            # Map error keywords to session state keys to identify failed fields
            error_map = {
                "XAU": "xau_usd",
                "Au9999": "sge_au9999",
                "CNH": "usd_cnh",
                "CNH MA200": "usd_cnh_ma200",
                "TIPS": "tips_yield",
                "US10Y": "us10y",
                "RSI": "rsi_14",
                "KDJ": "kdj_j",
                "518660": "price_518660",
                "IOPV": "iopv_518660",
                "IAUM": "price_iaum",
                "NDX": "ndx_spot"
            }
            st.session_state["failed_fields"] = [v for k, v in error_map.items() if any(k in err for err in fetcher.errors)]
            
            # CRITICAL: Streamlit widgets with 'key' ignore 'value=' changes on re-runs.
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
            st.session_state["ndx_spot"] = float(getattr(new_data, 'ndx_spot', 0.0))

            if hasattr(new_data, 'bei_history') and new_data.bei_history is not None:
                st.session_state["bei_history"] = new_data.bei_history
                st.session_state["bei_slope_60d"] = getattr(new_data, 'bei_slope_60d', 0.0)
                st.session_state["bei_t_stat_60d"] = getattr(new_data, 'bei_t_stat_60d', 0.0)

            if fetcher.errors:
                st.error("⚠️ Some APIs failed. Showing cached/fallback data for failed fields.")
                with st.expander("Show Details"):
                    for err in fetcher.errors:
                        st.write(f"- {err}")
            else:
                st.session_state["failed_fields"] = []
                st.success("✅ All data fetched successfully!")



    # Initialize failed_fields if not present
    if "failed_fields" not in st.session_state:
        st.session_state.failed_fields = []

    def get_label(name, key):
        return f"{name} [异常]" if key in st.session_state.failed_fields else name

    data = MarketData()

    # --- Row 1: Macro & FX Basis (4 cols) ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        data.xau_usd = st.number_input(
            get_label("XAU/USD 国际金价", "xau_usd"), step=1.00,
            format="%.2f", key="xau_usd")
    with col2:
        data.sge_au9999 = st.number_input(
            get_label("Au9999 上金所 (CNY/克)", "sge_au9999"), step=0.50,
            format="%.2f", key="sge_au9999")
    with col3:
        data.usd_cnh = st.number_input(
            get_label("USD/CNH 离岸汇率", "usd_cnh"), step=0.0010,
            format="%.4f", key="usd_cnh")
    with col4:
        data.usd_cnh_ma200 = st.number_input(
            get_label("USD/CNH MA200", "usd_cnh_ma200"), step=0.0010,
            format="%.4f", key="usd_cnh_ma200")

    # --- Row 2: Macro & Technicals (4 cols) ---
    col5, col6, col7, col8 = st.columns(4)
    with col5:
        data.tips_yield = st.number_input(
            get_label("TIPS Yield (%)", "tips_yield"), step=0.01,
            format="%.2f", key="tips_yield")
    with col6:
        data.us10y = st.number_input(
            get_label("US10Y (Reference)", "us10y"), step=0.01,
            format="%.2f", key="us10y",
            help="10年期美债名义收益率，仅供参考，不参与分仓计算")
    with col7:
        data.rsi_14 = st.number_input(
            get_label("RSI(14)", "rsi_14"), step=0.5,
            format="%.1f", key="rsi_14",
            min_value=0.0, max_value=100.0)
    with col8:
        data.kdj_j = st.number_input(
            get_label("KDJ-J", "kdj_j"), step=1.0,
            format="%.1f", key="kdj_j")

    # --- Row 3: Execution Instruments & Indices (4 cols) ---
    col9, col10, col11, col12 = st.columns(4)
    with col9:
        data.price_518660 = st.number_input(
            get_label("518660 现价 (CNY)", "price_518660"), step=0.0010,
            format="%.4f", key="price_518660")
    with col10:
        data.iopv_518660 = st.number_input(
            get_label("518660 IOPV (CNY)", "iopv_518660"), step=0.0010,
            format="%.4f", key="iopv_518660")
    with col11:
        data.price_iaum = st.number_input(
            get_label("IAUM 现价 (USD)", "price_iaum"), step=0.0100,
            format="%.4f", key="price_iaum")
    with col12:
        data.ndx_spot = st.number_input(
            get_label("Nasdaq 100 Index", "ndx_spot"), step=1.00,
            format="%.2f", key="ndx_spot"
        )


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

    # --- Tabs ---
    tab_main, tab_premium, tab_bei, tab_nasdaq = st.tabs(["🎯 Allocation Engine", "📈 SGE Premium Trend", "🏦 BEI Trend", "🚀 Nasdaq Trend"])

    with tab_main:
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

    with tab_premium:
        st.markdown('<div class="section-hdr">📈 沪伦溢价率历史走势 (SGE Premium Trend)</div>', unsafe_allow_html=True)
        st.caption("基于 518660.SS 日线收盘价反推国内金价，对比 COMEX GC=F 国际金价，计算沪伦溢价率的历史走势。叠加 30 日移动均线与 ±2σ 布林带。")
        
        if st.button("📡 Fetch Historical Premium Data", use_container_width=True, type="primary", key="btn_fetch_premium"):
            with st.spinner("正在从 Yahoo Finance 拉取 6 个月历史数据，请稍候..."):
                fetcher = DataFetcher()
                try:
                    df_hist = fetcher.fetch_sge_premium_history(period="6mo")
                    if df_hist.empty:
                        st.error("❌ 未能获取到有效的历史数据。")
                        if fetcher.errors:
                            for err in fetcher.errors:
                                st.write(f"- {err}")
                    else:
                        st.session_state["df_premium_history"] = df_hist
                        st.success(f"✅ 成功获取 {len(df_hist)} 个交易日的溢价数据！")
                except Exception as e:
                    st.error(f"❌ 拉取失败: {e}")
        
        if "df_premium_history" in st.session_state and not st.session_state.df_premium_history.empty:
            st.line_chart(st.session_state.df_premium_history)
        else:
            st.info("💡 请点击上方按钮获取历史溢价数据。")

    with tab_bei:
        st.markdown('<div class="section-hdr">🏦 DFII10 vs US10Y — 通胀预期 (BEI) 趋势图</div>', unsafe_allow_html=True)
        st.caption("数据源：FRED (Federal Reserve Economic Data)。需要全局 VPN 或本地代理环境以获取 DFII10 和 DGS10 数据。BEI = DGS10 − DFII10，反映市场对未来 10 年通胀的隐含预期。")

        if st.button("📡 Fetch BEI Historical Data", use_container_width=True, type="primary", key="btn_fetch_bei"):
            with st.spinner("正在尝试通过代理连接 FRED 获取真实历史数据（支持自动尝试本地代理端），请稍候..."):
                fetcher = DataFetcher()
                bei_result = fetcher.fetch_bei_history(period="1y")
                if bei_result is None or bei_result['df'].empty:
                    st.error("❌ 未能获取 BEI 历史数据。")
                    if fetcher.errors:
                        for err in fetcher.errors:
                            st.write(f"- {err}")
                else:
                    st.session_state["bei_history"] = bei_result['df']
                    st.session_state["bei_slope_60d"] = bei_result['slope_60d']
                    st.session_state["bei_t_stat_60d"] = bei_result['t_stat_60d']
                    st.success(f"✅ 成功获取 {len(bei_result['df'])} 个交易日的 BEI 数据！")

        if "bei_history" in st.session_state and st.session_state.bei_history is not None and not st.session_state.bei_history.empty:
            slope = st.session_state.get("bei_slope_60d", 0.0)
            t_stat = st.session_state.get("bei_t_stat_60d", 0.0)

            is_significant = abs(t_stat) >= 2.00

            if is_significant and slope > 0:
                trend_str = f"📈 BEI 显著扩张中 (+{slope:.4f}/日)"
                trend_implication = "通胀预期升温 → US10Y 与 DFII10 开口扩大 → 宏观面偏多黄金"
                trend_color = "#69f0ae"
            elif is_significant and slope < 0:
                trend_str = f"📉 BEI 显著收窄中 ({slope:.4f}/日)"
                trend_implication = "通胀预期降温 → US10Y 与 DFII10 开口缩小 → 实际利率走高，宏观面偏空黄金"
                trend_color = "#ef5350"
            else:
                trend_str = f"➖ BEI 震荡横盘 ({slope:.4f}/日)"
                trend_implication = "趋势不具统计学显著性 (p≥0.05)，通胀预期无共识方向"
                trend_color = "#8892b0"

            st.markdown(f"""
            <div class="alloc-box" style="text-align:center;">
                <div class="alloc-title">BEI 60日趋势判断 (开口方向)</div>
                <div class="alloc-big" style="color:{trend_color};">{trend_str}</div>
                <div class="alloc-sub">{trend_implication}</div>
                <div style="color:#8892b0; font-size:0.8rem; margin-top:8px;">
                    统计显著性：t = {t_stat:.2f} ({'p < 0.05 显著' if is_significant else 'p ≥ 0.05 不显著'})
                </div>
            </div>
            """, unsafe_allow_html=True)

            try:
                import plotly.graph_objects as go

                df_bei = st.session_state.bei_history
                fig = go.Figure()

                # DGS10 line (US10Y nominal yield)
                fig.add_trace(go.Scatter(
                    x=df_bei.index, y=df_bei['DGS10'],
                    mode='lines',
                    name='US10Y 名义收益率 (DGS10)',
                    line=dict(color='#8892b0', width=1.5, dash='dot')
                ))

                # DFII10 line (TIPS real yield, derived from TIP ETF)
                fig.add_trace(go.Scatter(
                    x=df_bei.index, y=df_bei['DFII10'],
                    mode='lines',
                    name='TIPS 实际收益率 (官方 DFII10)',
                    line=dict(color='#64ffda', width=1.5)
                ))

                # BEI as filled area
                fig.add_trace(go.Scatter(
                    x=df_bei.index, y=df_bei['BEI'],
                    mode='lines',
                    name='BEI 盈亏平衡通胀',
                    fill='tozeroy',
                    fillcolor='rgba(239, 83, 80, 0.15)',
                    line=dict(color='#ef5350', width=2)
                ))

                min_val = df_bei[['DGS10', 'DFII10', 'BEI']].min().min()
                max_val = df_bei[['DGS10', 'DFII10', 'BEI']].max().max()

                fig.update_layout(
                    height=660,
                    margin=dict(l=0, r=0, t=30, b=0),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    hovermode='x unified',
                    yaxis_title='Yield (%)',
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                    xaxis=dict(gridcolor='#233554'),
                    yaxis=dict(
                        gridcolor='#233554',
                        range=[min_val * 0.95, max_val * 1.05]
                    )
                )
                st.plotly_chart(fig, use_container_width=True)

            except ImportError:
                st.line_chart(st.session_state.bei_history)
                st.info("💡 安装 `plotly` 可获得更佳的交互式图表体验。")

        else:
            st.info("💡 请点击上方按钮获取 BEI 历史数据。")


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

    with tab_nasdaq:
        st.markdown('<div class="section-hdr">🚀 Nasdaq 100 Index (NDX) — 纳指200日趋势监控</div>', unsafe_allow_html=True)
        st.caption("数据源：Yahoo Finance (^NDX)。展示纳指100实时现价及过去 200 个交易日的收盘趋势。")

        if st.button("📡 Fetch Nasdaq Data", use_container_width=True, type="primary", key="btn_fetch_nasdaq"):
            with st.spinner("Fetching latest Nasdaq 100 data from yfinance..."):
                fetcher = DataFetcher()
                ndx_result = fetcher.fetch_nasdaq_history(symbol="^NDX", period="1y")
                
                if ndx_result and not ndx_result['df'].empty:
                    st.session_state["ndx_data"] = ndx_result
                    st.success("✅ 成功获取纳指100数据！")
                else:
                    st.error("❌ 未能获取纳指历史数据。")
                    if fetcher.errors:
                        for err in fetcher.errors:
                            st.write(f"- {err}")

        if "ndx_data" in st.session_state and st.session_state.ndx_data is not None:
            ndx_res = st.session_state.ndx_data
            df_ndx = ndx_res['df']
            
            spot = ndx_res['spot']
            change = ndx_res['change']
            change_pct = ndx_res['change_pct']
            open_p = ndx_res.get('open', 0.0)
            prev_close = ndx_res.get('prev_close', 0.0)
            high_p = ndx_res.get('day_high', 0.0)
            low_p = ndx_res.get('day_low', 0.0)
            y_high = ndx_res.get('year_high', 0.0)
            y_low = ndx_res.get('year_low', 0.0)
            
            is_up = change >= 0
            # Dark Mode Theme Colors
            text_color = "#69f0ae" if is_up else "#ef5350"
            line_color = "#69f0ae" if is_up else "#ef5350"
            fill_color = "rgba(105, 240, 174, 0.10)" if is_up else "rgba(239, 83, 80, 0.10)"
            sign = "+" if change > 0 else ""
            
            import pytz
            est_date = datetime.now(pytz.timezone('US/Eastern')).strftime('%b %d, %Y EST')
            
            # --- Top Header (Dark widget style) ---
            st.markdown(f"""
            <div style="background-color: transparent; border: 1px solid #233554; border-bottom: none; border-radius: 8px 8px 0 0; padding: 20px 20px 5px 20px; font-family: 'Segoe UI', Arial, sans-serif;">
                <div style="font-size: 2.2rem; font-weight: 500; color: #e6f1ff; line-height: 1;">{spot:,.2f}</div>
                <div style="font-size: 1.1rem; color: {text_color}; margin-top: 8px; font-weight: 500;">
                    {sign}{change:,.2f} ({sign}{change_pct:.2f}%) <span style="color: #8892b0; font-weight: 400; font-size: 0.9rem; margin-left: 5px;">{est_date}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # --- Plotly Chart (Dark Theme) ---
            try:
                import plotly.graph_objects as go
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_ndx.index, y=df_ndx['close'],
                    mode='lines',
                    name='NDX',
                    line=dict(color=line_color, width=2),
                    fill='tozeroy',
                    fillcolor=fill_color,
                    hoverinfo='y+x'
                ))
                
                fig.update_layout(
                    height=660,
                    margin=dict(l=0, r=0, t=10, b=0),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    hovermode='x unified',
                    showlegend=False,
                    xaxis=dict(
                        showgrid=False,
                        zeroline=False,
                        showline=True,
                        linecolor='#233554',
                        tickfont=dict(color='#8892b0')
                    ),
                    yaxis=dict(
                        showgrid=True,
                        gridcolor='#233554',
                        zeroline=False,
                        side='right',
                        tickfont=dict(color='#8892b0'),
                        range=[df_ndx['close'].min() * 0.98, df_ndx['close'].max() * 1.02]
                    )
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
            except ImportError:
                st.line_chart(df_ndx['close'])
            
            # --- Footer Stats (Dark Theme Table) ---
            st.markdown(f"""
            <div style="background-color: transparent; border: 1px solid #233554; border-top: none; border-radius: 0 0 8px 8px; padding: 10px 20px 20px 20px; font-family: 'Segoe UI', Arial, sans-serif;">
                <table style="width: 100%; font-size: 0.95rem; color: #e6f1ff; border-collapse: separate; border-spacing: 0 12px;">
                    <tr>
                        <td style="color: #8892b0; width: 16%;">Open</td><td style="width: 17%; font-weight: 500;">{open_p:,.2f}</td>
                        <td style="color: #8892b0; width: 16%;">High</td><td style="width: 17%; font-weight: 500;">{high_p:,.2f}</td>
                        <td style="color: #8892b0; width: 16%;">52-wk high</td><td style="width: 17%; font-weight: 500;">{y_high:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="color: #8892b0;">Prev close</td><td style="font-weight: 500;">{prev_close:,.2f}</td>
                        <td style="color: #8892b0;">Low</td><td style="font-weight: 500;">{low_p:,.2f}</td>
                        <td style="color: #8892b0;">52-wk low</td><td style="font-weight: 500;">{y_low:,.2f}</td>
                    </tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
            
        else:
            st.info("💡 请点击上方按钮获取纳指最新数据。")

if __name__ == "__main__":
    main()
