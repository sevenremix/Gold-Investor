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
import requests
from gold_engine import MarketData

# Lazy imports for optional dependencies to avoid crashing if missing
try:
    import finnhub
except ImportError:
    finnhub = None

try:
    import pandas_ta as ta
except ImportError:
    ta = None

try:
    import akshare as ak
except ImportError:
    ak = None

try:
    import pandas_datareader.data as pdr
except ImportError:
    pdr = None

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
        if not yf or not ta: return
        
        # --- yfinance for XAU Historical (last 3 months) ---
        try:
            df_yf = yf.download("GC=F", period="3mo", progress=False)
            if not df_yf.empty:
                if isinstance(df_yf.columns, pd.MultiIndex):
                    df_yf.columns = df_yf.columns.get_level_values(0)
                df_yf.rename(columns=str.lower, inplace=True)
                
                rsi = df_yf.ta.rsi(length=14)
                if rsi is not None and not rsi.empty:
                    data.rsi_14 = float(rsi.iloc[-1])
                    
                kdj_df = df_yf.ta.kdj(length=9, signal=3) 
                if kdj_df is not None and not kdj_df.empty:
                    j_col = [c for c in kdj_df.columns if c.startswith('J_')][0]
                    data.kdj_j = float(kdj_df[j_col].iloc[-1])
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
        """Fetch Spot Gold, 518660, and SGE Au(T+D) from Sina Finance real-time HQ API."""
        fetched_iopv = False
        try:
            url = "http://hq.sinajs.cn/list=hf_XAU,sh518660,gds_AUTD"
            headers = {"Referer": "http://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    if "sh518660" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 8:
                            # Index 3 is current price, 8 is IOPV
                            price = float(parts[3])
                            iopv = float(parts[8])
                            if price > 0: data.price_518660 = price
                            if iopv > 0 and 0.5 * price < iopv < 1.5 * price:
                                data.iopv_518660 = iopv
                                fetched_iopv = True
                    elif "hf_XAU" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 0:
                            # Index 0 is the current London spot price
                            spot_price = float(parts[0])
                            if spot_price > 0: data.xau_usd = spot_price
                    elif "gds_AUTD" in line and '="' in line:
                        content = line.split('="')[1].split('";')[0]
                        parts = content.split(',')
                        if len(parts) > 5:
                            # Index 0 or 3 usually contains the current match price for AUTD
                            autd_price = float(parts[0]) 
                            if autd_price > 0:
                                data.sge_au9999 = autd_price
                                
            # Fallback: if Sina doesn't provide valid IOPV, approximate it from Au9999
            if not fetched_iopv and data.sge_au9999 > 0:
                data.iopv_518660 = round(data.sge_au9999 / 100, 4)
                
        except Exception as e:
            self.errors.append(f"Sina domestic data error: {e}")

    def _fetch_fred_macro(self, data: MarketData):
        if not pdr: return
        
        try:
            # Fetch last 30 days to ensure we get the latest published yield
            end_date = datetime.now()
            start_date = end_date - pd.Timedelta(days=30)
            df_tips = pdr.DataReader('DFII10', 'fred', start_date, end_date)
            
            if not df_tips.empty:
                # Drop NaNs and get latest
                df_clean = df_tips.dropna()
                if not df_clean.empty:
                    data.tips_yield = float(df_clean.iloc[-1]['DFII10'])
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
