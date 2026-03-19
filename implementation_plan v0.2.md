# Gold ETF Smart Router — V3 Architecture

> [!IMPORTANT]
> V3: Added Streamlit UI, JSON config, MD data log, modular separation per user's 6 requirements.

## File Structure

```
Glod Investor/
├── strategy_config.json   # [NEW] Configurable thresholds & weights
├── gold_engine.py         # [NEW] Data collection + scoring (backend)
├── app.py                 # [NEW] Streamlit dashboard (frontend)
└── gold_data_log.md       # [AUTO] Timestamped raw data log
```

---

## Two-Layer Engine (unchanged from V2)

- **Layer 1 (Sizing):** TIPS + Momentum → `position_multiplier` ∈ [0, 1.5]
- **Layer 2 (Routing):** FX + SGE Premium + Friction → `R` score → IAUM% vs 518660%

---

## Proposed Changes

### [NEW] [strategy_config.json](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/strategy_config.json)

All thresholds editable in Streamlit sidebar. Structure:

```json
{
  "tips_neutral": 1.5,
  "tips_range": 2.0,
  "cnh_ma_period": 200,
  "sge_high_override": 4.0,
  "sge_low_override": -1.5,
  "rsi_overbought": 85,
  "rsi_oversold": 20,
  "j_overbought": 100,
  "j_oversold": -10,
  "weight_fx": 40,
  "weight_sge": 40,
  "weight_friction": 20,
  "sizing_tips_weight": 0.6,
  "sizing_momentum_weight": 0.4
}
```

---

### [NEW] [gold_engine.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_engine.py)

Pure backend — zero Streamlit imports. Contains:

| Class/Function | Responsibility |
|---|---|
| `StrategyConfig` | Load/save JSON, dataclass |
| `MarketData` dataclass | All raw prices: 518660 price, IOPV, IAUM price, XAU/USD, SGE Au9999, USD/CNH, TIPS yield, RSI, KDJ-J |
| `collect_market_data()` | Stub function returning `MarketData`; user plugs in real APIs later |
| `compute_derived()` | Calculates SGE premium%, 518660 friction%, FX deviation% from raw prices |
| `compute_sizing()` | Layer 1: TIPS + momentum → position multiplier |
| `compute_routing()` | Layer 2: FX + SGE + friction → R score → IAUM/518660 split |
| `allocate()` | Orchestrates both layers, applies hard overrides |
| `log_to_markdown()` | Appends timestamped row to `gold_data_log.md` |

---

### [NEW] [app.py](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/app.py)

Streamlit dashboard with 3 sections:

**Sidebar — Config Panel:**
- Load `strategy_config.json` on startup
- Render all params as `st.number_input` / `st.slider`
- "Save Config" button → writes back to JSON

**Main Area — Top: Raw Data Dashboard:**
- Shows all `MarketData` fields in `st.metric` cards:
  - Row 1: 518660 Price, IOPV, 518660 Friction%
  - Row 2: IAUM Price, XAU/USD (international gold), SGE Au9999 (domestic gold)
  - Row 3: USD/CNH, TIPS Yield, RSI(14), KDJ-J
  - Row 4: **Derived** — SGE Premium%, FX Deviation%
- Manual input mode: `st.number_input` for each factor (MVP, before API integration)

**Main Area — Bottom: Allocation Result:**
- Two-layer breakdown: sizing multiplier + routing score
- Visual gauge/progress bars for IAUM% vs 518660%
- Override alerts if any hard rule fires
- "Log & Save" button → appends to `gold_data_log.md`

---

### [AUTO] [gold_data_log.md](file:///e:/Google%20Drive%20Local/Investor/Glod%20Investor/gold_data_log.md)

Auto-generated markdown table. Each row = one snapshot:

```markdown
| Timestamp | 518660 | IOPV | IAUM | XAU/USD | Au9999 | USD/CNH | TIPS | RSI | J | SGE_Prem% | Friction% | FX_Dev% | R_Score | Size_Mult | IAUM% | 518660% | Override |
```

---

## Verification Plan

```powershell
cd "e:\Google Drive Local\Investor\Glod Investor"
pip install streamlit
streamlit run app.py
```

1. Verify all raw data fields render correctly with manual inputs
2. Verify config changes save to JSON and reload on refresh
3. Verify allocation result matches expected math for 5 scenarios
4. Verify "Log & Save" appends correct row to `gold_data_log.md`
5. Verify Bug 2 scenario (panic + strong CNH → should NOT force IAUM)
