# -*- coding: utf-8 -*-
"""
Gold ETF Smart Router — Data Fetcher Module (data_fetcher.py)
=============================================================
Automated data pipeline using:
  - Finnhub (IAUM, XAU_USD, USD_CNH)
  - Akshare (518660, Au9999)
  - pandas_datareader (FRED TIPS)
  - pandas_ta (RSI, KDJ computation)

Fail-safe design: returns MarketData populated with whatever succeeded.
Manual overrides are always allowed in the UI.
"""

import os
import io
import json
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np
import requests
from bs4 import BeautifulSoup
import io

def _calc_rsi(series: pd.Series, period: int = 9) -> pd.Series:
    """Calculate RSI using Wilder's Smoothing (MMA/RMA)"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def _calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.Series:
    """Calculate KDJ-J using EMA smoothing"""
    low_min = df['low'].rolling(window=n, min_periods=n).min()
    high_max = df['high'].rolling(window=n, min_periods=n).max()
    rsv = (df['close'] - low_min) / (high_max - low_min) * 100
    rsv = rsv.fillna(0)
    # EMA smoothing corresponds to alpha = 1/m1
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return j

from gold_engine import MarketData

# Lazy imports for optional dependencies to avoid crashing if missing
try:
    import finnhub
except ImportError:
    finnhub = None

try:
    # pandas_ta is no longer used directly, but its import might be kept for other reasons
    # or removed if it's truly not needed anywhere else.
    # For this change, we are replacing its usage with custom functions.
    pass
except ImportError:
    pass

try:
    import akshare as ak
except ImportError:
    ak = None

# pandas_datareader is no longer used.


try:
    import yfinance as yf
except ImportError:
    yf = None


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_KEYS_PATH = os.path.join(SCRIPT_DIR, "api_keys.json")


def _get_api_keys() -> dict:
    keys = {}
    if os.path.exists(API_KEYS_PATH):
        try:
            with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
                keys.update(json.load(f))
        except Exception:
            pass

    config_path = os.path.join(SCRIPT_DIR, "strategy_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if "fred_api_key" in cfg:
                    keys["fred_api_key"] = cfg["fred_api_key"]
        except Exception:
            pass
    return keys


class DataFetcher:
    """Orchestrates all API calls and returns a MarketData object."""

    def __init__(self):
        self.errors = []

    def fetch_all(self, fallback_data: Optional[MarketData] = None) -> MarketData:
        """
        Attempt to fetch all 10 inputs.
        Fallbacks to existing values in `fallback_data` if an API fails.
        """
        data = MarketData() if fallback_data is None else MarketData(**fallback_data.__dict__)
        self.errors.clear()
        
        # 1. yfinance (International Prices)
        self._fetch_yfinance_quotes(data)
        
        # 2. yfinance + pandas-ta (Historical Data -> RSI, KDJ, MA200)
        self._fetch_technical_indicators(data)
        
        # 3. Sina HQ (A-share & SGE Au(T+D) real-time)
        self._fetch_sina_domestic_data(data)
        
        # 4. FRED (TIPS)
        self._fetch_fred_macro(data)
        
        return data

    def _fetch_yfinance_quotes(self, data: MarketData):
        if not yf:
            self.errors.append("yfinance module not installed.")
            return

        # IAUM (US Equity)
        try:
            val = yf.Ticker("IAUM").fast_info.last_price
            if val and val > 0:
                data.price_iaum = float(val)
        except Exception as e:
            self.errors.append(f"yfinance IAUM error: {e}")

        # XAU/USD (Gold COMEX)
        # Note: We NO LONGER use yfinance's GC=F here for the spot price, 
        # to prevent structural mismatch (Futures vs Spot) in the premium calculation.
        # It is now fetched natively as London Spot (hf_XAU) in the Sina API block.
        pass
            
        # USD/CNH (Offshore RMB)
        try:
            val = yf.Ticker("CNH=X").fast_info.last_price
            if val and val > 0:
                data.usd_cnh = float(val)
        except Exception as e:
            self.errors.append(f"yfinance CNH error: {e}")
            
        # Nasdaq 100 Spot (Reference)
        try:
            val = yf.Ticker("^NDX").fast_info.get("lastPrice", 0.0)
            if val and val > 0:
                data.ndx_spot = float(val)
        except Exception as e:
            self.errors.append(f"yfinance NDX error: {e}")

    def _fetch_technical_indicators(self, data: MarketData):
        if not yf: return
        
        # --- yfinance for XAU Historical (last 3 months) ---
        try:
            df_yf = yf.download("GC=F", period="3mo", progress=False)
            if not df_yf.empty:
                if isinstance(df_yf.columns, pd.MultiIndex):
                    df_yf.columns = df_yf.columns.get_level_values(0)
                df_yf.rename(columns=str.lower, inplace=True)
                # Technical Indicators
                try:
                    # RSI(9)
                    rsi = _calc_rsi(df_yf['close'], period=9)
                    if rsi is not None and not rsi.empty and not pd.isna(rsi.iloc[-1]):
                        data.rsi_14 = float(rsi.iloc[-1])
                        
                    # KDJ J value (9, 3, 3)
                    j_vals = _calc_kdj(df_yf, n=9, m1=3, m2=3)
                    if j_vals is not None and not j_vals.empty and not pd.isna(j_vals.iloc[-1]):
                        data.kdj_j = float(j_vals.iloc[-1])
                except Exception as e:
                    self.errors.append(f"Indicator calc error: {e}")
        except Exception as e:
            self.errors.append(f"yfinance XAU historical error: {e}")

        # --- USD/CNY MA200 (FRED DEXCHUS via API, fallback to yfinance CNH=X) ---
        fetched_cnh_ma200 = False
        api_keys = _get_api_keys()
        fred_key = api_keys.get("fred_api_key", "").strip()

        proxies_to_try = [
            None,
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"},
            {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"}
        ]

        if fred_key:
            url_dexchus = f"https://api.stlouisfed.org/fred/series/observations?series_id=DEXCHUS&api_key={fred_key}&file_type=json&limit=250&sort_order=desc"
            for proxies in proxies_to_try:
                try:
                    resp = requests.get(url_dexchus, proxies=proxies, timeout=10)
                    if resp.status_code == 200:
                        obs = resp.json().get("observations", [])
                        vals = [float(o["value"]) for o in obs if o["value"] != "."]
                        if len(vals) > 0:
                            window = min(200, len(vals))
                            data.usd_cnh_ma200 = round(sum(vals[:window]) / window, 4)
                            fetched_cnh_ma200 = True
                            break
                except Exception:
                    continue
            if not fetched_cnh_ma200:
                self.errors.append("FRED API DEXCHUS error: All proxy attempts timed out.")

        if not fetched_cnh_ma200:
            try:
                df_cnh_hist = yf.download("CNH=X", period="1y", progress=False)
                if isinstance(df_cnh_hist.columns, pd.MultiIndex):
                    df_cnh_hist.columns = df_cnh_hist.columns.get_level_values(0)
                df_cnh_hist.columns = [c.lower() for c in df_cnh_hist.columns]
                if not df_cnh_hist.empty and 'close' in df_cnh_hist.columns:
                    s = df_cnh_hist['close'].dropna()
                    if len(s) > 0:
                        window = min(200, len(s))
                        data.usd_cnh_ma200 = float(s.rolling(window=window).mean().iloc[-1])
            except Exception as e:
                self.errors.append(f"yfinance CNH MA200 error: {e}")

    def _fetch_sina_domestic_data(self, data: MarketData):
        """Fetch Spot Gold, 518660, and SGE Au9999 from Sina Finance real-time HQ API."""
        fetched_iopv = False
        nav_t1 = 0.0
        au_prev_close = 0.0
        
        try:
            url = "http://hq.sinajs.cn/list=hf_XAU,sh518660,gds_AU9999,f_518660"
            headers = {"Referer": "http://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    if "sh518660" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 8:
                            price = float(parts[3])
                            # Index 8 is volume for A-shares, not IOPV.
                            if price > 0: data.price_518660 = price
                    elif "hf_XAU" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 0:
                            spot_price = float(parts[0])
                            if spot_price > 0: data.xau_usd = spot_price
                    elif "gds_AU9999" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 7:
                            autd_price = float(parts[0]) 
                            if autd_price > 0:
                                data.sge_au9999 = autd_price
                                # parts[7] is yesterday's close for gds_AU9999
                                au_prev_close = float(parts[7])
                    elif "f_518660" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 1:
                            nav_t1 = float(parts[1])
                                
            # Smart Fallback: Dynamic Proportional Tracking
            if not fetched_iopv:
                if nav_t1 > 0 and au_prev_close > 0 and data.sge_au9999 > 0:
                    # Real-time IOPV = (T-1 NAV) * (Current Au9999 / Yesterday's Au9999 Close)
                    # This perfectly preserves the exact historical tracking error and fee decay.
                    # round(..., 4): 保留4位小数，与518660的0.0001元市场报价精度对齐，防止引入无意义的浮点噪声
                    data.iopv_518660 = round(nav_t1 * (data.sge_au9999 / au_prev_close), 4)
                elif data.sge_au9999 > 0:
                    # Last resort fallback if ETF metadata is missing
                    data.iopv_518660 = round(data.sge_au9999 / 100, 4)
                
        except Exception as e:
            self.errors.append(f"Sina domestic data error: {e}")

    def _fetch_fred_macro(self, data: MarketData):
        """
        Fetch US10Y and TIPS Yield spot values.
        - US10Y: Prioritize yfinance (^TNX) for REAL-TIME market yield. Fallback to FRED DGS10 (T-1 delayed).
        - TIPS: Prioritize FRED official API (DFII10) because real TIPS yield is not live on Yahoo.
        """
        api_keys = _get_api_keys()
        fred_key = api_keys.get("fred_api_key", "").strip()

        fetched_us10y = False
        fetched_tips = False

        proxies_to_try = [
            None,
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"},
            {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"}
        ]

        # 1. Fetch Real-time US10Y via yfinance
        try:
            us10y_spot = float(yf.Ticker("^TNX").fast_info["last_price"])
            if us10y_spot > 0:
                data.us10y = round(us10y_spot, 3)
                fetched_us10y = True
        except Exception as e:
            self.errors.append(f"yfinance US10Y error: {e}")

        if fred_key:
            # Fallback 1: Fetch FRED DGS10 (US10Y) if yfinance failed
            if not fetched_us10y:
                url_dgs10 = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={fred_key}&file_type=json&limit=5&sort_order=desc"
                for proxies in proxies_to_try:
                    try:
                        resp = requests.get(url_dgs10, proxies=proxies, timeout=10)
                        if resp.status_code == 200:
                            obs = resp.json().get("observations", [])
                            for o in obs:
                                if o["value"] != ".":
                                    data.us10y = float(o["value"])
                                    fetched_us10y = True
                                    break
                            if fetched_us10y:
                                break
                    except Exception:
                        continue
                if not fetched_us10y:
                    self.errors.append("FRED API US10Y fallback error: All proxy attempts timed out.")

            # 2. Fetch FRED DFII10 (TIPS) - Always use FRED for this as primary
            url_dfii10 = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={fred_key}&file_type=json&limit=5&sort_order=desc"
            for proxies in proxies_to_try:
                try:
                    resp = requests.get(url_dfii10, proxies=proxies, timeout=10)
                    if resp.status_code == 200:
                        obs = resp.json().get("observations", [])
                        for o in obs:
                            if o["value"] != ".":
                                data.tips_yield = float(o["value"])
                                fetched_tips = True
                                break
                        if fetched_tips:
                            break
                except Exception:
                    continue
            if not fetched_tips:
                self.errors.append("FRED API TIPS error: All proxy attempts timed out.")

        # --- Fallback if TIPS logic totally fails ---
        if not fetched_tips and fetched_us10y:
            try:
                # Approximate TIPS ≈ US10Y − 2.20% (current expected BEI)
                data.tips_yield = round(data.us10y - 2.20, 2)
            except Exception as e:
                self.errors.append(f"TIPS proxy calculation error: {e}")

    def fetch_sge_premium_history(self, period="3mo") -> pd.DataFrame:
        """
        Fetch historical data to compute the onshore gold premium trend.
        Uses yfinance as the primary robust source.
        Returns a DataFrame with ['SGE Premium (%)', '30d MA', 'Upper (+2σ)', 'Lower (-2σ)']
        """
        df_result = pd.DataFrame()
        if not yf:
            return df_result
            
        try:
            # 1. Fetch Intl Gold (GC=F)
            df_gc = yf.download("GC=F", period=period, progress=False)
            if isinstance(df_gc.columns, pd.MultiIndex):
                df_gc.columns = df_gc.columns.get_level_values(0)
            df_gc.columns = [c.lower() for c in df_gc.columns]
            
            # 2. Fetch USD/CNY (CNH=X is currently broken on Yahoo Finance returning only 1 row)
            df_cnh = yf.download("USDCNY=X", period=period, progress=False)
            if isinstance(df_cnh.columns, pd.MultiIndex):
                df_cnh.columns = df_cnh.columns.get_level_values(0)
            df_cnh.columns = [c.lower() for c in df_cnh.columns]
            
            # 3. Fetch Domestic proxy (518660.SS)
            df_sh = yf.download("518660.SS", period=period, progress=False)
            if isinstance(df_sh.columns, pd.MultiIndex):
                df_sh.columns = df_sh.columns.get_level_values(0)
            df_sh.columns = [c.lower() for c in df_sh.columns]
            
            # Create explicit copies to safely modify indices
            s_xau = df_gc['close'].copy()
            s_cnh = df_cnh['close'].copy()
            s_dom = (df_sh['close'] * 100).copy()  # Convert ETF price to approx Au9999 price (CNY/g)
            
            # 4. Align across different trading calendars
            # Normalize timezone: yfinance returns tz-aware for some tickers (CNH=X), tz-naive for others (GC=F).
            # Strip all timezones so pd.concat can join the indices safely.
            s_xau.index = s_xau.index.tz_localize(None) if s_xau.index.tz is not None else s_xau.index
            s_cnh.index = s_cnh.index.tz_localize(None) if s_cnh.index.tz is not None else s_cnh.index
            s_dom.index = s_dom.index.tz_localize(None) if s_dom.index.tz is not None else s_dom.index
            
            # US and China markets have different holidays/weekends.
            # ffill() carries the last known price forward across gaps.
            df = pd.concat([s_xau, s_cnh, s_dom], axis=1, keys=['xau', 'cnh', 'dom'])
            df = df.ffill().dropna()  # ffill first, then drop only leading NaN rows
            
            if df.empty:
                return df_result
            
            df['intl_cny'] = df['xau'] * df['cnh'] / 31.1035
            df['SGE Premium (%)'] = (df['dom'] / df['intl_cny'] - 1) * 100
            
            # Compute 30-day MA and Bollinger Bands
            df['30d MA'] = df['SGE Premium (%)'].rolling(window=30, min_periods=5).mean()
            std = df['SGE Premium (%)'].rolling(window=30, min_periods=5).std()
            df['Upper (+2σ)'] = df['30d MA'] + 2 * std
            df['Lower (-2σ)'] = df['30d MA'] - 2 * std
            
            return df[['SGE Premium (%)', '30d MA', 'Upper (+2σ)', 'Lower (-2σ)']].dropna()
            
        except Exception as e:
            self.errors.append(f"Historical premium fetch error: {e}")
            return df_result

    def fetch_bei_history(self, period: str = "1y") -> dict:
        """
        Fetch DFII10 + DGS10 history for BEI trend chart.
        Uses FRED official API if fred_api_key is provided, else falls back to CSV.
        Uses automatic retry with common local proxy ports (7890, 10809, 1080) if GFW blocks it.
        """
        api_keys = _get_api_keys()
        fred_key = api_keys.get("fred_api_key", "").strip()

        # List of proxies to try automatically, starting with None (direct)
        proxies_to_try = [
            None,
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},      # Clash
            {"http": "http://127.0.0.1:10809", "https": "http://127.0.0.1:10809"},    # v2rayN
            {"http": "http://127.0.0.1:1080", "https": "http://127.0.0.1:1080"},      # Shadowsocks
        ]

        df_tips = pd.DataFrame()
        df_us10y = pd.DataFrame()
        success = False

        if fred_key:
            url_dfii10 = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={fred_key}&file_type=json&limit=300&sort_order=desc"
            url_dgs10 = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={fred_key}&file_type=json&limit=300&sort_order=desc"
            
            for proxies in proxies_to_try:
                try:
                    resp_tips = requests.get(url_dfii10, proxies=proxies, timeout=10)
                    resp_us10y = requests.get(url_dgs10, proxies=proxies, timeout=10)
                    if resp_tips.status_code == 200 and resp_us10y.status_code == 200:
                        obs_tips = [o for o in resp_tips.json().get("observations", []) if o["value"] != "."]
                        obs_us10y = [o for o in resp_us10y.json().get("observations", []) if o["value"] != "."]
                        
                        df_tips = pd.DataFrame(obs_tips)[['date', 'value']].rename(columns={'date': 'DATE', 'value': 'DFII10'})
                        df_us10y = pd.DataFrame(obs_us10y)[['date', 'value']].rename(columns={'date': 'DATE', 'value': 'DGS10'})
                        
                        for df, col in [(df_tips, 'DFII10'), (df_us10y, 'DGS10')]:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                            df['DATE'] = pd.to_datetime(df['DATE'])
                            df.set_index('DATE', inplace=True)
                            
                        # Sort index chronologically because sort_order=desc puts newest first
                        df_tips.sort_index(inplace=True)
                        df_us10y.sort_index(inplace=True)
                        success = True
                        break
                except Exception:
                    continue

        # Fallback to CSV if API key not present or failed
        if not success:
            url_dfii10_csv = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
            url_dgs10_csv = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"

            resp_tips_csv = None
            resp_us10y_csv = None

            for proxies in proxies_to_try:
                try:
                    resp_tips_csv = requests.get(url_dfii10_csv, proxies=proxies, timeout=10)
                    resp_us10y_csv = requests.get(url_dgs10_csv, proxies=proxies, timeout=10)
                    if resp_tips_csv.status_code == 200 and resp_us10y_csv.status_code == 200:
                        df_tips = pd.read_csv(io.StringIO(resp_tips_csv.text))
                        df_us10y = pd.read_csv(io.StringIO(resp_us10y_csv.text))

                        for df, col in [(df_tips, 'DFII10'), (df_us10y, 'DGS10')]:
                            if col not in df.columns:
                                raise ValueError(f"Missing column {col}")
                            df[col] = df[col].replace('.', np.nan)
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                            date_col = df.columns[0]
                            df[date_col] = pd.to_datetime(df[date_col])
                            df.set_index(date_col, inplace=True)
                        
                        success = True
                        break
                except Exception:
                    continue

        if not success:
            self.errors.append("❌ FRED 数据获取失败：所有网络/代理尝试均超时。请确保已开启全局 VPN 或检查 API Key。")
            return None

        try:
            df_macro = df_us10y.join(df_tips, how='inner').dropna()
            if len(df_macro) < 5:
                self.errors.append("BEI: 有效对其数据点不足。")
                return None

            df_macro['BEI'] = df_macro['DGS10'] - df_macro['DFII10']
            df_macro = df_macro.tail(250)

            return self._compute_bei_regression(df_macro)

        except Exception as e:
            self.errors.append(f"FRED 数据解析错误: {e}")
            return None

    def _compute_bei_regression(self, df_macro: pd.DataFrame) -> dict:
        """Compute 60-day BEI linear regression slope and t-statistic."""
        result = {
            'df': df_macro,
            'slope_60d': 0.0,
            't_stat_60d': 0.0,
        }

        if len(df_macro) >= 60:
            y = df_macro['BEI'].tail(60).values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            result['slope_60d'] = float(slope)

            n = len(x)
            y_pred = slope * x + intercept
            sse = np.sum((y - y_pred) ** 2)
            if sse > 0:
                se = np.sqrt(sse / (n - 2))
                sb = se / np.sqrt(np.sum((x - np.mean(x)) ** 2))
                result['t_stat_60d'] = float(slope / sb) if sb > 0 else 0.0

        return result

    def fetch_nasdaq_history(self, symbol: str = "^NDX", period: str = "1y") -> dict:
        """
        Fetch Nasdaq history and spot metrics via yfinance.
        Suitable for deploy environments like Streamlit Cloud where there is no GFW.
        Returns a dict with 'df' (history), 'spot', 'change', 'change_pct'.
        """
        result = {
            'df': pd.DataFrame(),
            'spot': 0.0,
            'change': 0.0,
            'change_pct': 0.0
        }
        
        if not yf:
            self.errors.append("yfinance library is not available for Nasdaq fetch.")
            return result
            
        try:
            # 1. Fetch History
            df = yf.download(symbol, period=period, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            
            if not df.empty and 'close' in df.columns:
                df = df.dropna()
                # Keep last 200 days
                result['df'] = df.tail(200)[['close']]
                
            # 2. Fetch Spot & Change
            ticker = yf.Ticker(symbol)
            spot = ticker.fast_info.get("lastPrice", 0.0)
            prev_close = ticker.fast_info.get("previousClose", 0.0)
            
            result['open'] = float(ticker.fast_info.get("open", 0.0))
            result['day_high'] = float(ticker.fast_info.get("dayHigh", 0.0))
            result['day_low'] = float(ticker.fast_info.get("dayLow", 0.0))
            result['prev_close'] = float(prev_close)
            result['year_high'] = float(ticker.fast_info.get("yearHigh", 0.0))
            result['year_low'] = float(ticker.fast_info.get("yearLow", 0.0))
            
            if spot and spot > 0:
                result['spot'] = float(spot)
                if prev_close and prev_close > 0:
                    change = spot - prev_close
                    result['change'] = float(change)
                    result['change_pct'] = float((change / prev_close) * 100)
            
            return result
            
        except Exception as e:
            self.errors.append(f"Nasdaq fetch error ({symbol}): {e}")
            return result


if __name__ == "__main__":
    print("Testing DataFetcher...")
    fetcher = DataFetcher()
    data = fetcher.fetch_all()
    print("\n--- Fetched Data ---")
    for k, v in data.__dict__.items():
        print(f"{k:15}: {v}")
    
    if fetcher.errors:
        print("\n--- Errors ---")
        for err in fetcher.errors:
            print(err)
