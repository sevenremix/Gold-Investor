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
    if os.path.exists(API_KEYS_PATH):
        try:
            with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


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

        # --- FRED for USD/CNY MA200 (last 1 year) ---
        try:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXCHUS"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                df_cnh = pd.read_csv(io.StringIO(resp.text))
                if not df_cnh.empty and 'DEXCHUS' in df_cnh.columns:
                    # Filter out '.' which FRED uses for nulls/holidays
                    df_cnh = df_cnh[df_cnh['DEXCHUS'] != '.']
                    if not df_cnh.empty:
                        df_cnh['DEXCHUS'] = pd.to_numeric(df_cnh['DEXCHUS'], errors='coerce')
                        df_cnh = df_cnh.dropna(subset=['DEXCHUS'])
                        # We only need the last 300 rows to calculate a safe 200-day SMA
                        df_cnh = df_cnh.tail(300)
                        if len(df_cnh) > 0:
                            window = min(200, len(df_cnh))
                            ma200 = df_cnh['DEXCHUS'].rolling(window=window).mean()
                            data.usd_cnh_ma200 = float(ma200.iloc[-1])
        except Exception as e:
            self.errors.append(f"FRED CNH MA200 error: {e}")

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
        """Fetch TIPS Yield (DFII10) and US10Y (DGS10) from FRED via CSV."""
        # 1. TIPS Yield (DFII10)
        try:
            url_tips = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
            resp = requests.get(url_tips, timeout=10)
            if resp.status_code == 200:
                df = pd.read_csv(io.StringIO(resp.text))
                if not df.empty and 'DFII10' in df.columns:
                    df = df[df['DFII10'] != '.']
                    if not df.empty:
                        data.tips_yield = float(df.iloc[-1]['DFII10'])
        except Exception as e:
            self.errors.append(f"FRED TIPS error: {e}")

        # 2. US10Y (DGS10) - Reference Only
        try:
            url_us10y = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
            resp = requests.get(url_us10y, timeout=10)
            if resp.status_code == 200:
                df = pd.read_csv(io.StringIO(resp.text))
                if not df.empty and 'DGS10' in df.columns:
                    df = df[df['DGS10'] != '.']
                    if not df.empty:
                        # We use a custom attribute in data object for US10Y
                        setattr(data, 'us10y', float(df.iloc[-1]['DGS10']))
        except Exception as e:
            self.errors.append(f"FRED US10Y error: {e}")

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
