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

        # --- yfinance for USD/CNH MA200 (last 1 year) ---
        try:
            df_cnh_yf = yf.download("CNH=X", period="1y", progress=False)
            if not df_cnh_yf.empty:
                if isinstance(df_cnh_yf.columns, pd.MultiIndex):
                    df_cnh_yf.columns = df_cnh_yf.columns.get_level_values(0)
                df_cnh_yf.rename(columns=str.lower, inplace=True)
                if len(df_cnh_yf) > 0:
                    # If less than 200 days, just use the mean of available data
                    window = min(200, len(df_cnh_yf))
                    ma200 = df_cnh_yf['close'].rolling(window=window).mean()
                    data.usd_cnh_ma200 = float(ma200.iloc[-1])
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
                        if len(parts) > 5:
                            autd_price = float(parts[0]) 
                            if autd_price > 0:
                                data.sge_au9999 = autd_price
                                au_prev_close = float(parts[2])
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
                    data.iopv_518660 = round(nav_t1 * (data.sge_au9999 / au_prev_close), 4)
                elif data.sge_au9999 > 0:
                    # Last resort fallback if ETF metadata is missing
                    data.iopv_518660 = round(data.sge_au9999 / 100, 4)
                
        except Exception as e:
            self.errors.append(f"Sina domestic data error: {e}")

    def _fetch_fred_macro(self, data: MarketData):
        """Fetch 10-Year TIPS Yield from FRED via CSV download."""
        try:
            url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                df = pd.read_csv(io.StringIO(resp.text))
                if not df.empty and 'DFII10' in df.columns:
                    # Filter out '.' which FRED uses for nulls
                    df = df[df['DFII10'] != '.']
                    if not df.empty:
                        latest_val = float(df.iloc[-1]['DFII10'])
                        data.tips_yield = latest_val
        except Exception as e:
            self.errors.append(f"FRED TIPS error: {e}")


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
