# app.py – Lightweight Flask app (LightGBM + rule-based strategies)
# UPDATED:
#  - Accurate 10s trade monitor
#  - Silent percentage-based trailing stop (locks 30%/50%/70%)
#  - Silent force TP at FORCE_TP_PERCENT (30%)
#  - UI-friendly API: /api/open_trades returns profit_pct, current, pnl
#  - MT4-style timeframes supported (M1..MN) → mapped to yfinance intervals

import os
import time
import threading
import requests
import traceback
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import yfinance as yf
import pandas as pd
import numpy as np
import pandas_ta as ta
from dotenv import load_dotenv
import warnings
warnings.filterwarnings('ignore')

from patterns_light import detect_candlestick_patterns, get_pattern_signal, detect_chart_patterns

logging.getLogger('yfinance').setLevel(logging.ERROR)
load_dotenv()

try:
    from pytrader_api import Pytrader_API
    PYTRADER_AVAILABLE = True
except ImportError as e:
    PYTRADER_AVAILABLE = False
    print(f"PyTrader module not found: {e}. Auto-trading disabled.")

app = Flask(__name__)

# ---------- Configuration ----------
RISK_ATR = 1.0
REWARD_RATIO = 1.5
ALL_PAIRS = ['EURUSD', 'GBPUSD', 'AUDUSD', 'USDCAD', 'USDCHF',
             'EURGBP', 'EURJPY', 'NZDUSD', 'GBPJPY', 'USDJPY']
AUTO_TRADE_PAIRS = ALL_PAIRS

PYTRADER_SERVER = os.environ.get('PYTRADER_SERVER', 'localhost')
PYTRADER_PORT = int(os.environ.get('PYTRADER_PORT', 1122))
PYTRADER_AUTH_CODE = os.environ.get('PYTRADER_AUTH_CODE', 'None')
TRADE_VOLUME = float(os.environ.get('TRADE_VOLUME', 0.10))
BALANCE = float(os.environ.get('BALANCE', 100000.0))

AUTO_TRADE_ENABLED = os.environ.get('AUTO_TRADE_ENABLED', 'True').lower() == 'true'
AUTO_TRADE_INTERVAL_MINUTES = int(os.environ.get('AUTO_TRADE_INTERVAL_MINUTES', 60))

CONFIDENCE_THRESHOLD = float(os.environ.get('CONFIDENCE_THRESHOLD', 0.75))
MIN_VOLUME = float(os.environ.get('MIN_VOLUME', 0.01))
MAX_VOLUME = float(os.environ.get('MAX_VOLUME', 1.00))
PROFIT_CLOSE_PCT = float(os.environ.get('PROFIT_CLOSE_PCT', 0.50))  # legacy close (unused in new UI)

ATR_LENGTH = int(os.environ.get('ATR_LENGTH', 14))
ATR_MULTIPLIER_SL = float(os.environ.get('ATR_MULTIPLIER_SL', 2.5))
ATR_MULTIPLIER_TP = float(os.environ.get('ATR_MULTIPLIER_TP', 2.0))
TRAILING_STOP_ACTIVE = os.environ.get('TRAILING_STOP_ACTIVE', 'True').lower() == 'true'
MIN_RR = float(os.environ.get('MIN_RR', 2.0))
WIN_RATE_THRESHOLD = float(os.environ.get('WIN_RATE_THRESHOLD', 0.6))
LOW_RR_ALLOWED = float(os.environ.get('LOW_RR_ALLOWED', 1.2))

LGB_TP_MULT = 0.02
LGB_SL_MULT = 0.012
LGB_TIME_HORIZON = 30
LGB_MIN_CONFIDENCE = 0.55

FORCE_TP_PERCENT = float(os.environ.get('FORCE_TP_PERCENT', 0.30))  # silent force TP

PAIRS_TRADING_CORRELATED = {
    'EURUSD': 'GBPUSD', 'GBPUSD': 'EURUSD',
    'AUDUSD': 'NZDUSD', 'NZDUSD': 'AUDUSD',
    'USDJPY': 'EURJPY', 'EURJPY': 'USDJPY',
}

FEATURE_COLUMNS = [
    'open', 'high', 'low', 'close',
    'open_prev_1', 'high_prev_1', 'low_prev_1', 'close_prev_1',
    'open_prev_2', 'high_prev_2', 'low_prev_2', 'close_prev_2',
    'rsi_14', 'macd', 'atr_14',
    'bb_upper', 'bb_middle', 'bb_lower', 'bb_width',
    'roc_10', 'roc_20',
    'returns_std_10', 'returns_skew_10', 'returns_kurt_10',
    'stoch_k', 'stoch_d', 'williams_r', 'cci_20', 'adx_14',
    'volatility_20', 'volatility_ratio',
    'crude_oil', 'gold', 'agri',
    'spread_us_de', 'spread_us_uk', 'spread_us_au', 'spread_us_ca',
    'spread_us_ch', 'spread_de_uk', 'spread_de_jp', 'spread_us_nz',
    'spread_uk_jp', 'spread_us_jp',
    'vix',
    'sp500', 'dax', 'ftse', 'nikkei', 'asx', 'hsi', 'dxy'
]

ORIGINAL_FEATURES = [
    'open', 'high', 'low', 'close',
    'open_prev_1', 'high_prev_1', 'low_prev_1', 'close_prev_1',
    'open_prev_2', 'high_prev_2', 'low_prev_2', 'close_prev_2',
    'rsi_14', 'macd', 'atr_14',
    'bb_upper', 'bb_middle', 'bb_lower', 'bb_width',
    'roc_10', 'roc_20',
    'returns_std_10', 'returns_skew_10', 'returns_kurt_10',
    'stoch_k', 'stoch_d', 'williams_r', 'cci_20', 'adx_14',
    'volatility_20', 'volatility_ratio',
    'crude_oil', 'gold', 'agri',
    'spread_us_de', 'spread_us_uk', 'spread_us_au', 'spread_us_ca',
    'spread_us_ch', 'spread_de_uk', 'spread_de_jp', 'spread_us_nz',
    'spread_uk_jp', 'spread_us_jp',
    'vix'
]

PAIR_MODEL_MAP = {pair: 'lightgbm' for pair in ALL_PAIRS}

# MT4 timeframe mapping → yfinance interval
TIMEFRAME_MAP = {
    'm1': '1m', 'm5': '5m', 'm15': '15m', 'm30': '30m',
    'h1': '1h', 'h4': '4h', 'd1': '1d', 'w1': '1wk', 'mn': '1mo',
}

# Cache TTLs (seconds)
_SIGNAL_CACHE_TTL = 30
_LIVE_PRICE_CACHE_TTL = 8


def normalize_pair(pair: str) -> str:
    pair = (pair or '').upper()
    if pair.endswith('=X'):
        return pair[:-2]
    return pair


def normalize_timeframe(tf: str) -> str:
    """Accept '1h', 'H1', 'h1' → return yfinance interval."""
    tf = (tf or 'h1').lower().strip()
    return TIMEFRAME_MAP.get(tf, '1h')


# ---------- Twelve Data ----------
TWELVE_DATA_API_KEY = os.environ.get('TWELVE_DATA_API_KEY')
TWELVE_BASE = 'https://api.twelvedata.com/quote'

_live_price_cache = {}
_twelve_request_count = 0
_twelve_last_request_time = 0
_twelve_request_lock = threading.Lock()


def _twelve_rate_limit():
    global _twelve_last_request_time
    with _twelve_request_lock:
        now = time.time()
        elapsed = now - _twelve_last_request_time
        min_interval = 1.0
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _twelve_last_request_time = time.time()


def get_live_price_twelve(symbol):
    if not TWELVE_DATA_API_KEY:
        return None
    symbol = normalize_pair(symbol)
    if len(symbol) == 6 and symbol.isalpha():
        symbol_formatted = f"{symbol[:3]}/{symbol[3:]}"
    else:
        symbol_formatted = symbol
    now = time.time()
    if symbol in _live_price_cache and (now - _live_price_cache[symbol]['timestamp'] < _LIVE_PRICE_CACHE_TTL):
        return _live_price_cache[symbol]['price']
    try:
        _twelve_rate_limit()
        url = f"{TWELVE_BASE}?symbol={symbol_formatted}&apikey={TWELVE_DATA_API_KEY}"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if 'close' in data and data['close'] is not None:
                price = float(data['close'])
                _live_price_cache[symbol] = {'price': price, 'timestamp': now}
                global _twelve_request_count
                _twelve_request_count += 1
                return price
    except Exception as e:
        print(f"⚠️ Twelve Data exception for {symbol}: {e}")
    return None


# ---------- Supabase ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set!")

if not SUPABASE_URL.endswith('/'):
    SUPABASE_URL += '/'
if 'rest/v1' not in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.rstrip('/') + '/rest/v1/'


def supabase_request(method, endpoint, data=None):
    url = SUPABASE_URL + endpoint
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    try:
        if method == 'GET':
            resp = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            resp = requests.post(url, json=data, headers=headers, timeout=10)
        elif method == 'PATCH':
            resp = requests.patch(url, json=data, headers=headers, timeout=10)
        elif method == 'DELETE':
            resp = requests.delete(url, headers=headers, timeout=10)
        else:
            return False, f"Unsupported method {method}"
        if resp.status_code in (200, 201, 204):
            try:
                return True, resp.json() if resp.text else {}
            except Exception:
                return True, {}
        return False, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)


class SupabaseClientWrapper:
    def __init__(self, url, key):
        self.base_url = url
        self.key = key

    def table(self, name):
        return TableWrapper(self, name)


class TableWrapper:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.select_fields = '*'
        self.filters = {}
        self.order_by = None
        self.limit_val = None
        self.order_desc = False

    def select(self, fields):
        self.select_fields = fields
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, col, desc=False):
        self.order_by = col
        self.order_desc = desc
        return self

    def limit(self, n):
        self.limit_val = n
        return self

    def execute(self):
        url = self.client.base_url + self.table_name
        params = {}
        if self.select_fields != '*':
            params['select'] = self.select_fields
        for col, val in self.filters.items():
            params[col] = f'eq.{val}'
        if self.order_by:
            params['order'] = f'{self.order_by}.desc' if self.order_desc else f'{self.order_by}.asc'
        if self.limit_val:
            params['limit'] = self.limit_val
        headers = {"apikey": self.client.key, "Authorization": f"Bearer {self.client.key}"}

        class Response:
            def __init__(self, data):
                self.data = data

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return Response(resp.json())
            return Response([])
        except Exception:
            return Response([])

    def insert(self, data):
        url = self.client.base_url + self.table_name
        headers = {
            "apikey": self.client.key,
            "Authorization": f"Bearer {self.client.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

        class Response:
            def __init__(self, data):
                self.data = data

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                try:
                    return Response(resp.json())
                except Exception:
                    return Response([])
            return Response([])
        except Exception:
            return Response([])

    def update(self, data):
        url = self.client.base_url + self.table_name
        params = {k: f'eq.{v}' for k, v in self.filters.items()}
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        headers = {
            "apikey": self.client.key,
            "Authorization": f"Bearer {self.client.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

        class Response:
            def __init__(self, data):
                self.data = data

        try:
            resp = requests.patch(url, json=data, headers=headers, timeout=10)
            if resp.status_code in (200, 201):
                try:
                    return Response(resp.json())
                except Exception:
                    return Response([])
            return Response([])
        except Exception:
            return Response([])


supabase_wrapper = SupabaseClientWrapper(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------- PyTrader ----------
pytrader = None
pytrader_connected = False
last_connection_attempt = 0
connection_attempt_interval = 60


def connect_to_mt4():
    global pytrader, pytrader_connected, last_connection_attempt
    if not PYTRADER_AVAILABLE:
        return False
    now = time.time()
    if now - last_connection_attempt < connection_attempt_interval and not pytrader_connected:
        return False
    last_connection_attempt = now
    instrument_lookup = {pair: pair for pair in ALL_PAIRS}
    try:
        pytrader = Pytrader_API()
        pytrader.debug = False
        success = pytrader.Connect(
            server=PYTRADER_SERVER, port=PYTRADER_PORT,
            instrument_lookup=instrument_lookup,
            authorization_code=PYTRADER_AUTH_CODE
        )
        if success:
            pytrader_connected = True
            print("✅ Connected to MT4 via PyTrader.")
            return True
        print("❌ PyTrader connection failed.")
        pytrader_connected = False
        return False
    except Exception as e:
        print(f"❌ PyTrader connection error: {e}")
        pytrader_connected = False
        return False


trade_monitor_thread = None
trade_monitor_enabled = True
trade_monitor_interval = 10   # 10s for accurate monitoring

auto_trade_thread = None
auto_trade_enabled = True

_models_cache = {}


def get_model(pair, model_type):
    if model_type != 'lightgbm':
        return None
    key = f"{pair}_{model_type}"
    if key in _models_cache:
        return _models_cache[key]
    try:
        from lightgbm_model import LightGBMModel
        model = LightGBMModel(
            tp_mult=LGB_TP_MULT,
            sl_mult=LGB_SL_MULT,
            time_horizon=LGB_TIME_HORIZON,
            feature_columns=FEATURE_COLUMNS,
            supabase_client=supabase_wrapper,
            table_name='lightgbm_models'
        )
        if model:
            _models_cache[key] = model
        return model
    except Exception as e:
        print(f"⚠️ get_model({pair}) failed: {e}")
        return None


def preload_models():
    for pair in ALL_PAIRS:
        try:
            get_model(pair, 'lightgbm')
        except Exception as e:
            print(f"⚠️ Preload failed for {pair}: {e}")


# ---------- Indicators / signals ----------
def detect_trend(df, ma_long=200):
    if len(df) < ma_long:
        return 'neutral'
    sma = df['close'].rolling(ma_long).mean().iloc[-1]
    curr = df['close'].iloc[-1]
    if curr > sma:
        return 'uptrend'
    elif curr < sma:
        return 'downtrend'
    return 'neutral'


def compute_rule_signal_simple(df, min_confidence=0.7):
    candle_patterns = detect_candlestick_patterns(df)
    candle_signal, candle_conf = get_pattern_signal(candle_patterns)
    chart_patterns = detect_chart_patterns(df, lookback=40) if len(df) >= 40 else []
    trend = detect_trend(df, ma_long=200)
    signal = 'HOLD'
    conf = 0.0
    if candle_signal != 'HOLD':
        signal = candle_signal
        conf = candle_conf
        for pat in chart_patterns:
            if pat in ['double_bottom', 'inverse_head_shoulders', 'ascending_triangle'] and signal == 'BUY':
                conf = min(1.0, conf + 0.15)
            elif pat in ['double_top', 'head_shoulders', 'descending_triangle'] and signal == 'SELL':
                conf = min(1.0, conf + 0.15)
        if signal == 'BUY' and trend == 'uptrend':
            conf = min(1.0, conf + 0.1)
        elif signal == 'SELL' and trend == 'downtrend':
            conf = min(1.0, conf + 0.1)
    else:
        if chart_patterns:
            bullish = ['double_bottom', 'inverse_head_shoulders', 'ascending_triangle', 'falling_wedge']
            bearish = ['double_top', 'head_shoulders', 'descending_triangle', 'rising_wedge']
            b = sum(1 for p in chart_patterns if p in bullish)
            be = sum(1 for p in chart_patterns if p in bearish)
            if b > be:
                signal = 'BUY'
                conf = 0.5 + 0.3 * (b / (b + be))
            elif be > b:
                signal = 'SELL'
                conf = 0.5 + 0.3 * (be / (b + be))
            if signal == 'BUY' and trend == 'uptrend':
                conf = min(1.0, conf + 0.2)
            elif signal == 'SELL' and trend == 'downtrend':
                conf = min(1.0, conf + 0.2)
    if conf >= min_confidence and signal != 'HOLD':
        return signal, conf
    return 'HOLD', 0.0


def bollinger_bands_signal(df, min_confidence=0.7):
    if len(df) < 20:
        return 'HOLD', 0.0
    if df['close'].iloc[-1] <= df['bb_lower'].iloc[-1]:
        return 'BUY', 0.75
    elif df['close'].iloc[-1] >= df['bb_upper'].iloc[-1]:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def williams_r_signal(df, min_confidence=0.7):
    if len(df) < 14:
        return 'HOLD', 0.0
    w = df['williams_r'].iloc[-1]
    if w < -80:
        return 'BUY', 0.7 + (-80 - w) / 20 * 0.1
    elif w > -20:
        return 'SELL', 0.7 + (w + 20) / 20 * 0.1
    return 'HOLD', 0.0


def cci_signal(df, min_confidence=0.7):
    if len(df) < 20:
        return 'HOLD', 0.0
    cci = df['cci_20'].iloc[-1]
    if cci < -100:
        return 'BUY', 0.7 + min(0.2, (-100 - cci) / 200 * 0.2)
    elif cci > 100:
        return 'SELL', 0.7 + min(0.2, (cci - 100) / 200 * 0.2)
    return 'HOLD', 0.0


def stochastic_signal(df, min_confidence=0.7):
    if len(df) < 14:
        return 'HOLD', 0.0
    stoch_k = df['stoch_k'].iloc[-1]
    stoch_d = df['stoch_d'].iloc[-1]
    prev_k = df['stoch_k'].iloc[-2]
    prev_d = df['stoch_d'].iloc[-2]
    if stoch_k < 20 and stoch_k > stoch_d and prev_k <= prev_d:
        return 'BUY', 0.7
    elif stoch_k > 80 and stoch_k < stoch_d and prev_k >= prev_d:
        return 'SELL', 0.7
    return 'HOLD', 0.0


def pairs_trading_signal(df, min_confidence=0.7, lookback=20, z_thresh=2.0):
    if 'secondary_df' not in df.attrs:
        return 'HOLD', 0.0
    second_df = df.attrs['secondary_df']
    if len(df) < lookback or len(second_df) < lookback:
        return 'HOLD', 0.0
    common_idx = df.index.intersection(second_df.index)
    if len(common_idx) < lookback:
        return 'HOLD', 0.0
    price1 = df.loc[common_idx, 'close']
    price2 = second_df.loc[common_idx, 'close']
    spread = price1 / price2
    std = spread.rolling(lookback).std().iloc[-1]
    if std == 0 or np.isnan(std):
        return 'HOLD', 0.0
    z = (spread.iloc[-1] - spread.rolling(lookback).mean().iloc[-1]) / std
    if z < -z_thresh:
        return 'BUY', min(1.0, 0.7 + (abs(z) - z_thresh) / z_thresh * 0.2)
    elif z > z_thresh:
        return 'SELL', min(1.0, 0.7 + (z - z_thresh) / z_thresh * 0.2)
    return 'HOLD', 0.0


def macd_signal(df, min_confidence=0.7):
    if len(df) < 26:
        return 'HOLD', 0.0
    if 'macd_signal' not in df.columns or df['macd_signal'].isna().iloc[-1]:
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
    else:
        macd_line = df['macd']
        signal_line = df['macd_signal']
    if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
        return 'BUY', 0.75
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def rsi_signal(df, min_confidence=0.7):
    if len(df) < 14:
        return 'HOLD', 0.0
    rsi = df['rsi_14'].iloc[-1]
    if rsi < 30:
        return 'BUY', 0.7 + (30 - rsi) / 30 * 0.2
    elif rsi > 70:
        return 'SELL', 0.7 + (rsi - 70) / 30 * 0.2
    return 'HOLD', 0.0


def ensemble_signal(df, min_confidence=0.7):
    signals, confidences = [], []
    for fn in [bollinger_bands_signal, williams_r_signal, cci_signal,
               stochastic_signal, pairs_trading_signal]:
        s, c = fn(df)
        if s != 'HOLD':
            signals.append(s)
            confidences.append(c)
    if not signals:
        return 'HOLD', 0.0
    buy = sum(1 for s in signals if s == 'BUY')
    sell = sum(1 for s in signals if s == 'SELL')
    avg_conf = sum(confidences) / len(confidences)
    if buy > sell:
        return 'BUY', min(1.0, avg_conf * (0.8 + 0.2 * buy / (buy + sell)))
    elif sell > buy:
        return 'SELL', min(1.0, avg_conf * (0.8 + 0.2 * sell / (buy + sell)))
    return 'HOLD', 0.0


# ---------- Data fetching ----------
_data_cache = {}
_cache_ttl = 3600
_equity_cache = {}


def get_date_ranges(interval='1h'):
    now = datetime.now()
    if interval in ('1m', '5m', '15m', '30m'):
        days_back = 7
    elif interval in ('1h', '4h'):
        days_back = 30
    elif interval == '1d':
        days_back = 180
    else:
        days_back = 730
    return (now - timedelta(days=days_back)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


def fetch_equity_indices(start, end):
    cache_key = f"{start}_{end}"
    if cache_key in _equity_cache:
        return _equity_cache[cache_key].copy()
    symbols = {
        'sp500': '^GSPC', 'dax': '^GDAXI', 'ftse': '^FTSE',
        'nikkei': '^N225', 'asx': '^AXJO', 'hsi': '^HSI', 'dxy': 'DX-Y.NYB'
    }
    combined = pd.DataFrame()
    for name, symbol in symbols.items():
        try:
            data = yf.download(symbol, start=start, end=end, progress=False, timeout=30)
            if not data.empty:
                ps = data['Adj Close'] if 'Adj Close' in data.columns else data['Close']
                if isinstance(ps, pd.DataFrame):
                    ps = ps.iloc[:, 0]
                ps.name = name
                combined = ps.to_frame() if combined.empty else combined.join(ps, how='outer')
        except Exception as e:
            print(f"⚠️ Could not fetch {name}: {e}")
    combined = combined.ffill().dropna(how='all')
    _equity_cache[cache_key] = combined
    return combined


def _merge_external_data(df, equity_df=None):
    if df.empty or equity_df is None or equity_df.empty:
        return df
    df = df.copy().reset_index()
    date_col = 'Date' if 'Date' in df.columns else ('Datetime' if 'Datetime' in df.columns else df.columns[0])
    df[date_col] = pd.to_datetime(df[date_col], utc=True, errors='coerce').dt.tz_localize(None)
    eq = equity_df.copy()
    if not isinstance(eq.index, pd.DatetimeIndex):
        eq.index = pd.to_datetime(eq.index, utc=True, errors='coerce').tz_localize(None)
    else:
        try:
            eq.index = eq.index.tz_localize(None)
        except Exception:
            pass
    df = pd.merge_asof(df.sort_values(date_col), eq.sort_index(),
                       left_on=date_col, right_index=True, direction='backward')
    for col in eq.columns:
        if col in df.columns:
            df[col] = df[col].ffill()
    return df.set_index(date_col)


def fetch_data(pair, start, end, interval, max_retries=2):
    pair = normalize_pair(pair)
    ticker = pair + '=X'
    cache_key = f"{ticker}_{start}_{end}_{interval}"
    now = time.time()
    if cache_key in _data_cache:
        if (now - _data_cache[cache_key]['timestamp']) < _cache_ttl:
            return _data_cache[cache_key]['data'].copy()
    for attempt in range(max_retries):
        try:
            data = yf.download(
                ticker, start=start, end=end, interval=interval,
                progress=False, timeout=30, auto_adjust=False,
                threads=False, ignore_tz=True
            )
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                if 'Adj Close' in data.columns:
                    data = data.drop(columns=['Adj Close'])
                # Ensure standard columns
                rename_map = {c: c.lower() for c in data.columns}
                data = data.rename(columns=rename_map)
                for col in ['open', 'high', 'low', 'close']:
                    if col not in data.columns and 'close' in data.columns:
                        data[col] = data['close']
                if 'volume' not in data.columns:
                    data['volume'] = 0
                data = data[['open', 'high', 'low', 'close', 'volume']]
                _data_cache[cache_key] = {'data': data.copy(), 'timestamp': now}
                return data
        except Exception as e:
            print(f"⚠️ Fetch attempt {attempt + 1} failed for {ticker}: {e}")
            time.sleep(0.5)
    return pd.DataFrame()


def get_live_entry_price(pair, signal):
    symbol = normalize_pair(pair)
    price = get_live_price_twelve(symbol)
    if price is not None:
        # Simulate bid/ask spread (~1 pip)
        spread = 0.0001
        if signal == 'BUY':
            return price + spread / 2, True
        else:
            return price - spread / 2, True
    global pytrader, pytrader_connected
    if not pytrader_connected:
        if not connect_to_mt4():
            return None, False
    if symbol not in pytrader.instrument_conversion_list:
        pytrader.instrument_conversion_list[symbol] = symbol
    try:
        quote = pytrader.Get_last_ask_bid(symbol)
        if quote and isinstance(quote, dict) and 'ask' in quote and 'bid' in quote:
            return (quote['ask'], True) if signal == 'BUY' else (quote['bid'], True)
    except Exception as e:
        print(f"⚠️ PyTrader error for {symbol}: {e}")
    return None, False


def get_live_bid_ask(pair):
    symbol = normalize_pair(pair)
    global pytrader, pytrader_connected
    if not pytrader_connected:
        if not connect_to_mt4():
            return None, None
    if symbol not in pytrader.instrument_conversion_list:
        pytrader.instrument_conversion_list[symbol] = symbol
    try:
        quote = pytrader.Get_last_ask_bid(symbol)
        if quote and 'bid' in quote and 'ask' in quote:
            return quote['bid'], quote['ask']
    except Exception as e:
        print(f"⚠️ PyTrader bid/ask error for {symbol}: {e}")
    return None, None


def get_valid_lot_size(pair, requested_volume):
    global pytrader, pytrader_connected
    symbol = normalize_pair(pair)
    if not pytrader_connected:
        connect_to_mt4()
    try:
        if pytrader_connected and symbol in pytrader.instrument_conversion_list:
            info = pytrader.Get_instrument_info(symbol)
            if info:
                min_lot = max(float(info.get('min_lotsize', 0.01)), MIN_VOLUME)
                max_lot = min(float(info.get('max_lotsize', 10.0)), MAX_VOLUME)
                step = float(info.get('lot_step', 0.01))
                v = max(min_lot, min(max_lot, requested_volume))
                v = round(v / step) * step
                return max(v, min_lot)
    except Exception:
        pass
    # Fallback
    min_lot = max(MIN_VOLUME, 0.01)
    max_lot = min(MAX_VOLUME, 10.0)
    v = max(min_lot, min(max_lot, requested_volume))
    return round(v, 2)


def adjust_sl_tp(pair, price, sl, tp, ratio=REWARD_RATIO):
    global pytrader, pytrader_connected
    symbol = normalize_pair(pair)
    if not pytrader_connected:
        connect_to_mt4()
    digits = 5
    if pair.upper().endswith('JPY'):
        digits = 3
    try:
        if pytrader_connected and symbol in pytrader.instrument_conversion_list:
            info = pytrader.Get_instrument_info(symbol)
            if info:
                digits = int(info.get('digits', digits))
    except Exception:
        pass
    price = round(price, digits)
    sl = round(sl, digits)
    tp = round(tp, digits)
    return sl, tp


def validate_sl_tp(pair, price, sl, tp):
    if sl is None or tp is None:
        return False, "SL/TP missing"
    if sl == 0 or tp == 0:
        return False, "SL/TP zero"
    if sl < price and tp > price:
        return True, "OK"
    elif sl > price and tp < price:
        return True, "OK"
    return False, "SL and TP on same side of price"


def compute_profit(entry, exit_price, pair, volume):
    try:
        entry = float(entry)
        exit_price = float(exit_price)
        volume = float(volume) if volume else 0.01
    except (TypeError, ValueError):
        return 0.0
    pair = normalize_pair(pair)
    # Try PyTrader tick info
    global pytrader, pytrader_connected
    try:
        symbol = pair
        if pytrader_connected and symbol in pytrader.instrument_conversion_list:
            info = pytrader.Get_instrument_info(symbol)
            if info:
                tick_size = info.get('tick_size')
                tick_value = info.get('tick_value')
                if tick_size and tick_value and tick_size != 0:
                    return ((exit_price - entry) / tick_size) * tick_value * volume
    except Exception:
        pass
    # Fallback: pip-based
    pip_size = 0.01 if pair.endswith('JPY') else 0.0001
    pips = (exit_price - entry) / pip_size
    return pips * 10.0 * volume


def is_trade_ready(pair, price, signal, atr, df,
                   spread_threshold=0.0005, max_price_dev=0.01,
                   min_atr_ratio=0.3, max_atr_ratio=3.0, lookback=20):
    if len(df) > 0:
        last_close = df['close'].iloc[-1]
        if last_close != 0:
            dev = abs(price - last_close) / last_close
            if dev > max_price_dev:
                return False, f"Price deviated {dev:.3%}"
    if 'atr' not in df.columns:
        return True, "Ready"
    atr_series = df['atr'].dropna()
    if len(atr_series) >= lookback:
        avg_atr = atr_series.iloc[-lookback:].mean()
        if avg_atr > 0:
            ratio = atr / avg_atr
            if ratio < min_atr_ratio or ratio > max_atr_ratio:
                return False, f"ATR ratio {ratio:.2f} outside range"
    return True, "Ready"


# ---------- Features ----------
def add_features(df):
    if df.empty or len(df) < 20:
        return df
    df = df.copy()
    df['rsi_14'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9'] if macd is not None and 'MACD_12_26_9' in macd.columns else 0
    df['macd_signal'] = macd['MACDs_12_26_9'] if macd is not None and 'MACDs_12_26_9' in macd.columns else np.nan
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=ATR_LENGTH)
    df['atr_14'] = df['atr']
    sma = df['close'].rolling(20).mean()
    std = df['close'].rolling(20).std()
    df['bb_upper'] = sma + 2 * std
    df['bb_middle'] = sma
    df['bb_lower'] = sma - 2 * std
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
    df['bb_width'] = df['bb_width'].replace([np.inf, -np.inf], np.nan)
    df['roc_10'] = ta.roc(df['close'], length=10)
    df['roc_20'] = ta.roc(df['close'], length=20)
    ret = df['close'].pct_change()
    df['returns_std_10'] = ret.rolling(10).std()
    df['returns_skew_10'] = ret.rolling(10).skew()
    df['returns_kurt_10'] = ret.rolling(10).kurt()
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3)
    if stoch is not None:
        df['stoch_k'] = stoch.get('STOCHk_14_3_3', np.nan)
        df['stoch_d'] = stoch.get('STOCHd_14_3_3', np.nan)
    else:
        df['stoch_k'] = df['stoch_d'] = np.nan
    df['williams_r'] = ta.willr(df['high'], df['low'], df['close'], length=14)
    df['cci_20'] = ta.cci(df['high'], df['low'], df['close'], length=20)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['adx_14'] = adx['ADX_14'] if adx is not None and 'ADX_14' in adx.columns else np.nan
    df['volatility_20'] = ret.rolling(20).std()
    df['volatility_ratio'] = df['volatility_20'] / df['volatility_20'].rolling(10).mean()
    df['volatility_ratio'] = df['volatility_ratio'].replace([np.inf, -np.inf], np.nan)
    for lag in [1, 2]:
        df[f'open_prev_{lag}'] = df['open'].shift(lag)
        df[f'high_prev_{lag}'] = df['high'].shift(lag)
        df[f'low_prev_{lag}'] = df['low'].shift(lag)
        df[f'close_prev_{lag}'] = df['close'].shift(lag)
    df = df.dropna(subset=['atr', 'rsi_14'])
    return df


# ---------- ATR SL/TP ----------
def compute_atr_sl_tp(price, pair, signal, atr, df,
                      sl_mult=None, tp_mult=None, min_rr=MIN_RR,
                      force_tp_percent=None):
    sl_mult = sl_mult if sl_mult is not None else ATR_MULTIPLIER_SL
    tp_mult = tp_mult if tp_mult is not None else ATR_MULTIPLIER_TP
    sl_distance = atr * sl_mult

    if force_tp_percent is not None and force_tp_percent > 0:
        if signal == 'BUY':
            tp = price * (1 + force_tp_percent)
        else:
            tp = price * (1 - force_tp_percent)
        min_tp_distance = min_rr * sl_distance
        if signal == 'BUY':
            if tp - price < min_tp_distance:
                tp = price + min_tp_distance
            sl = price - sl_distance
        else:
            if price - tp < min_tp_distance:
                tp = price - min_tp_distance
            sl = price + sl_distance
        tp_distance = abs(tp - price)
    else:
        tp_distance = atr * tp_mult
        if tp_distance < min_rr * sl_distance:
            tp_distance = min_rr * sl_distance
        if signal == 'BUY':
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance
    return sl, tp, sl_distance, tp_distance


def get_effective_rr(pair):
    ok, rows = supabase_request('GET', f'trades?pair=eq.{pair}&result=neq.pending')
    if not ok or not rows:
        return MIN_RR, False
    total = len(rows)
    wins = sum(1 for r in rows if r['result'] == 'win')
    if total < 10:
        return MIN_RR, False
    win_rate = wins / total
    if win_rate > WIN_RATE_THRESHOLD:
        return LOW_RR_ALLOWED, True
    return MIN_RR, False


# ---------- Process pair ----------
def process_pair(pair, interval, atr_period, risk_mult, reward_ratio, model_type=None):
    pair = normalize_pair(pair)
    interval = normalize_timeframe(interval)
    if model_type is None:
        model_type = PAIR_MODEL_MAP.get(pair, 'lightgbm')

    recent_start, recent_end = get_date_ranges(interval)
    try:
        df = fetch_data(pair, recent_start, recent_end, interval)
        if df.empty or len(df) < 60:
            return {
                "pair": pair, "signal": "HOLD", "confidence": 0.0,
                "price": None, "tp": None, "sl": None, "atr": None,
                "can_trade": False, "can_trade_reason": "No data",
                "trade_ready": False, "trade_ready_reason": "No data",
                "volume_ok": False, "volume_reason": "No data",
                "chart": {"dates": [], "prices": [], "signal_point": None},
                "model_used": model_type, "source": model_type,
                "ml_conf": 0.0, "error": None
            }

        equity_df = fetch_equity_indices(recent_start, recent_end)
        if not equity_df.empty:
            df = _merge_external_data(df, equity_df=equity_df)
        df = add_features(df)

        if model_type in ('pairs_trading', 'ensemble') and pair in PAIRS_TRADING_CORRELATED:
            sec_pair = normalize_pair(PAIRS_TRADING_CORRELATED[pair])
            sec_df = fetch_data(sec_pair, recent_start, recent_end, interval)
            if not sec_df.empty:
                df.attrs['secondary_df'] = sec_df

        signal = 'HOLD'
        conf = 0.0
        conf_threshold = CONFIDENCE_THRESHOLD

        if model_type == 'rule':
            signal, conf = compute_rule_signal_simple(df, min_confidence=conf_threshold)
        elif model_type == 'ensemble':
            signal, conf = ensemble_signal(df, min_confidence=conf_threshold)
        elif model_type == 'bollinger':
            signal, conf = bollinger_bands_signal(df)
        elif model_type == 'williams_r':
            signal, conf = williams_r_signal(df)
        elif model_type == 'cci':
            signal, conf = cci_signal(df)
        elif model_type == 'stochastic':
            signal, conf = stochastic_signal(df)
        elif model_type == 'pairs_trading':
            signal, conf = pairs_trading_signal(df)
        elif model_type == 'macd':
            signal, conf = macd_signal(df)
        elif model_type == 'rsi':
            signal, conf = rsi_signal(df)
        elif model_type == 'lightgbm':
            model = get_model(pair, model_type)
            if model is None:
                signal, conf = 'HOLD', 0.0
            else:
                signal, conf = model.predict(df, min_confidence=LGB_MIN_CONFIDENCE)
                if conf < conf_threshold:
                    signal = 'HOLD'
                    conf = 0.0
        else:
            signal, conf = compute_rule_signal_simple(df, min_confidence=conf_threshold)

        current_atr = float(df['atr'].iloc[-1]) if 'atr' in df.columns and not df['atr'].isna().iloc[-1] else 0.0001
        current_price = float(df['close'].iloc[-1])

        # Volume sizing
        if conf >= 0.85:
            vol_mult = 1.0
        elif conf >= 0.80:
            vol_mult = 0.7
        else:
            vol_mult = 0.5
        requested_vol = max(MIN_VOLUME, min(MAX_VOLUME, TRADE_VOLUME * vol_mult))
        valid_vol = get_valid_lot_size(pair, requested_vol)
        volume_ok = valid_vol > 0
        volume_reason = "OK" if volume_ok else "Invalid volume"

        # Live price
        if signal != 'HOLD':
            live_price, live_ok = get_live_entry_price(pair, signal)
            reference_price = live_price if live_ok and live_price else current_price
        else:
            reference_price = current_price

        # SL / TP
        if signal != 'HOLD':
            min_rr, _ = get_effective_rr(pair)
            sl, tp, _, _ = compute_atr_sl_tp(
                reference_price, pair, signal, current_atr, df,
                min_rr=min_rr, force_tp_percent=FORCE_TP_PERCENT
            )
            adjusted_sl, adjusted_tp = adjust_sl_tp(pair, reference_price, sl, tp, ratio=REWARD_RATIO)
            if adjusted_sl is None or adjusted_tp is None:
                can_trade = False
                reason = "Cannot adjust SL/TP"
            else:
                sl, tp = adjusted_sl, adjusted_tp
                can_trade, reason = validate_sl_tp(pair, reference_price, sl, tp)
        else:
            can_trade = False
            reason = "No signal"
            sl, tp = None, None

        ready, ready_reason = False, "Not applicable"
        if signal != 'HOLD' and can_trade and volume_ok:
            ready, ready_reason = is_trade_ready(pair, reference_price, signal, current_atr, df)

        # Chart data
        chart_slice = df.iloc[-100:] if len(df) >= 100 else df
        chart_dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d)
                       for d in chart_slice.index]
        chart_prices = [float(p) for p in chart_slice['close'].tolist()]
        chart_data = {
            "dates": chart_dates,
            "prices": chart_prices,
            "signal_point": {
                "date": chart_dates[-1] if chart_dates else "",
                "price": float(reference_price),
                "signal": signal
            } if signal != "HOLD" else None
        }

        return {
            "pair": pair,
            "signal": signal,
            "confidence": round(conf, 3) if signal != 'HOLD' else 0.0,
            "price": round(float(reference_price), 5),
            "tp": round(float(tp), 5) if tp is not None else None,
            "sl": round(float(sl), 5) if sl is not None else None,
            "atr": round(float(current_atr), 5),
            "can_trade": can_trade,
            "can_trade_reason": reason,
            "trade_ready": ready,
            "trade_ready_reason": ready_reason,
            "volume_ok": volume_ok,
            "volume_reason": volume_reason,
            "chart": chart_data,
            "model_used": model_type,
            "source": model_type,
            "ml_conf": round(conf, 3),
            "error": None
        }
    except Exception as e:
        print(f"❌ Error processing {pair}: {e}")
        traceback.print_exc()
        return {"pair": pair, "error": str(e)[:150]}


# ---------- Trade execution ----------
def execute_trade_with_atr(pair, signal, price, df, atr, volume=TRADE_VOLUME):
    global pytrader, pytrader_connected
    if not PYTRADER_AVAILABLE:
        return {"success": False, "error": "PyTrader not available"}
    if not pytrader_connected:
        if not connect_to_mt4():
            return {"success": False, "error": "Could not connect to MT4"}
    symbol = normalize_pair(pair)
    if symbol not in pytrader.instrument_conversion_list:
        pytrader.instrument_conversion_list[symbol] = symbol

    valid_volume = get_valid_lot_size(pair, volume)
    if valid_volume <= 0:
        return {"success": False, "error": f"Volume invalid: {volume}"}

    min_rr, _ = get_effective_rr(pair)
    sl, tp, _, _ = compute_atr_sl_tp(
        price, pair, signal, atr, df,
        min_rr=min_rr, force_tp_percent=FORCE_TP_PERCENT
    )
    adjusted_sl, adjusted_tp = adjust_sl_tp(pair, price, sl, tp, ratio=REWARD_RATIO)
    if adjusted_sl is None or adjusted_tp is None:
        return {"success": False, "error": "Invalid SL/TP"}
    valid, reason = validate_sl_tp(pair, price, adjusted_sl, adjusted_tp)
    if not valid:
        return {"success": False, "error": f"SL/TP invalid: {reason}"}

    try:
        ordertype = "buy" if signal.upper() == "BUY" else "sell"
        ticket = pytrader.Open_order(
            instrument=symbol, ordertype=ordertype, volume=valid_volume,
            openprice=0.0, slippage=5, magicnumber=0,
            stoploss=adjusted_sl, takeprofit=adjusted_tp,
            comment=f"{signal} {pair}", market=False
        )
        if ticket == -1:
            return {"success": False, "error": f"Order failed: {pytrader.order_return_message}"}
        return {
            "success": True, "order_id": ticket,
            "message": f"{signal} {pair} executed, ticket {ticket}",
            "volume": valid_volume, "sl": adjusted_sl, "tp": adjusted_tp
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def close_trade(trade):
    global pytrader, pytrader_connected
    if not pytrader_connected:
        if not connect_to_mt4():
            return False
    try:
        ticket = trade.get('order_id')
        if not ticket:
            return False
        try:
            ticket_int = int(ticket)
        except (TypeError, ValueError):
            return False
        success = pytrader.Close_position_by_ticket(ticket_int)
        if success:
            return True
        # Fallback: open opposite market order
        bid, ask = get_live_bid_ask(trade['pair'])
        if bid is None or ask is None:
            return False
        volume = float(trade.get('volume', 0.01))
        symbol = normalize_pair(trade['pair'])
        if trade['signal'] == 'BUY':
            close_price = bid
            order_type = 'sell'
        else:
            close_price = ask
            order_type = 'buy'
        ticket_close = pytrader.Open_order(
            instrument=symbol, ordertype=order_type, volume=volume,
            openprice=close_price, slippage=5, magicnumber=0,
            stoploss=0, takeprofit=0,
            comment=f"Close #{ticket}", market=True
        )
        return ticket_close != -1
    except Exception as e:
        print(f"Close trade error: {e}")
        return False


# ---------- Profit / trailing ----------
def get_profit_percentage(trade, current_price):
    """Profit as % of distance from entry → TP."""
    try:
        entry = float(trade['entry_price'])
        tp = trade.get('tp')
        if tp is None:
            return None
        tp = float(tp)
        if tp == entry:
            return None
        if trade['signal'] == 'BUY':
            if current_price <= entry:
                return 0.0
            total = tp - entry
            if total <= 0:
                return None
            return (current_price - entry) / total * 100.0
        else:
            if current_price >= entry:
                return 0.0
            total = entry - tp
            if total <= 0:
                return None
            return (entry - current_price) / total * 100.0
    except (TypeError, ValueError):
        return None


def update_trailing_stop(trade, current_price):
    """
    Silent percentage-based trailing stop ladder:
      50% → lock 30%
      70% → lock 50%
      90% → lock 70%
    Only tightens (never loosens) the SL. Returns new SL or None.
    """
    if not TRAILING_STOP_ACTIVE:
        return None
    try:
        entry = float(trade['entry_price'])
        signal = trade['signal']
        tp = trade.get('tp')
        current_sl = float(trade['sl']) if trade.get('sl') is not None else None
        if tp is None or current_sl is None:
            return None
        tp = float(tp)
        if tp == entry:
            return None

        if signal == 'BUY':
            total_dist = tp - entry
            if total_dist <= 0:
                return None
            current_profit = current_price - entry
            if current_profit <= 0:
                return None
            profit_pct = current_profit / total_dist
            new_sl = None
            for threshold, lock_pct in [(0.5, 0.3), (0.7, 0.5), (0.9, 0.7)]:
                if profit_pct >= threshold:
                    new_sl = entry + lock_pct * total_dist
                    break
            if new_sl is None:
                return None
            if new_sl > tp:
                new_sl = tp
            if new_sl > current_sl + 1e-9:
                return round(new_sl, 5)
        else:
            total_dist = entry - tp
            if total_dist <= 0:
                return None
            current_profit = entry - current_price
            if current_profit <= 0:
                return None
            profit_pct = current_profit / total_dist
            new_sl = None
            for threshold, lock_pct in [(0.5, 0.3), (0.7, 0.5), (0.9, 0.7)]:
                if profit_pct >= threshold:
                    new_sl = entry - lock_pct * total_dist
                    break
            if new_sl is None:
                return None
            if new_sl < tp:
                new_sl = tp
            if new_sl < current_sl - 1e-9:
                return round(new_sl, 5)
    except (TypeError, ValueError) as e:
        print(f"⚠️ trailing stop calc error: {e}")
    return None


# ---------- Trade monitor ----------
def has_pending_trade(pair):
    ok, rows = supabase_request('GET', f'trades?pair=eq.{pair}&result=eq.pending')
    return ok and rows and len(rows) > 0


def _get_current_price_for_trade(trade):
    """Get current market price. Uses signal side to pick ask/bid."""
    pair = normalize_pair(trade['pair'])
    signal = trade.get('signal', 'BUY')

    # First try Twelve Data (fast, no MT4 needed)
    raw = get_live_price_twelve(pair)
    if raw is not None:
        return float(raw), True

    # Fallback to MT4
    price, ok = get_live_entry_price(pair, signal)
    if ok and price is not None:
        return float(price), True
    return None, False


def update_open_trades():
    """
    Monitor all pending trades:
      1. Silent FORCE TP: if profit_pct >= FORCE_TP_PERCENT*100 (30%) → close
      2. Silent TRAILING STOP: tighten SL per ladder
    """
    ok, rows = supabase_request('GET', 'trades?result=eq.pending')
    if not ok or not rows:
        return
    for trade in rows:
        pair = normalize_pair(trade.get('pair', ''))
        if pair not in ALL_PAIRS:
            continue

        price, price_ok = _get_current_price_for_trade(trade)
        if not price_ok or price is None:
            continue

        # ---- 1. FORCE TP ----
        if FORCE_TP_PERCENT > 0:
            profit_pct = get_profit_percentage(trade, price)
            if profit_pct is not None and profit_pct >= (FORCE_TP_PERCENT * 100):
                print(f"🎯 FORCE TP: {pair} @ {profit_pct:.1f}% → closing")
                if close_trade(trade):
                    pnl = compute_profit(
                        float(trade['entry_price']), price, pair,
                        float(trade.get('volume', 0.01))
                    )
                    update_trade_result(trade['id'], 'closed_force_tp', pnl)
                    print(f"✅ Closed {pair} (force TP) PnL=${pnl:.2f}")
                else:
                    print(f"⚠️ Force TP close failed for {pair}")
                continue

        # ---- 2. TRAILING STOP ----
        if TRAILING_STOP_ACTIVE:
            new_sl = update_trailing_stop(trade, price)
            if new_sl is not None and abs(new_sl - float(trade.get('sl') or 0)) > 1e-7:
                print(f"🔧 {pair}: SL {trade.get('sl')} → {new_sl} (price={price})")
                supabase_request('PATCH', f'trades?id=eq.{trade["id"]}', {'sl': new_sl})
                if pytrader_connected:
                    try:
                        ticket = int(trade.get('order_id') or 0)
                        tp_val = float(trade.get('tp') or 0)
                        pytrader.Set_sl_and_tp_for_position(
                            ticket=ticket, stoploss=float(new_sl), takeprofit=tp_val
                        )
                    except Exception as e:
                        print(f"⚠️ MT4 SL modify failed: {e}")


def trade_monitor_loop():
    global trade_monitor_enabled
    while trade_monitor_enabled:
        try:
            update_open_trades()
        except Exception as e:
            print(f"⚠️ Trade monitor error: {e}")
            traceback.print_exc()
        time.sleep(trade_monitor_interval)


def start_trade_monitor():
    global trade_monitor_thread
    if trade_monitor_thread is None or not trade_monitor_thread.is_alive():
        trade_monitor_thread = threading.Thread(target=trade_monitor_loop, daemon=True)
        trade_monitor_thread.start()
        print(f"📊 Trade monitor started ({trade_monitor_interval}s interval, "
              f"silent trailing + silent {FORCE_TP_PERCENT*100:.0f}% force TP).")


# ---------- Auto-trade ----------
def auto_trade_loop():
    global auto_trade_enabled
    while auto_trade_enabled:
        try:
            if AUTO_TRADE_ENABLED and PYTRADER_AVAILABLE:
                print("🔄 Auto-trade cycle started")
                for pair in AUTO_TRADE_PAIRS:
                    if has_pending_trade(pair):
                        print(f"⏩ Skipping {pair} – pending trade exists.")
                        continue
                    model_type = PAIR_MODEL_MAP.get(pair, 'lightgbm')
                    sig = process_pair(pair, interval='h1', atr_period=ATR_LENGTH,
                                       risk_mult=RISK_ATR, reward_ratio=REWARD_RATIO,
                                       model_type=model_type)
                    if sig is None:
                        continue
                    if (sig['signal'] in ('BUY', 'SELL')
                            and sig.get('can_trade')
                            and sig.get('trade_ready')
                            and sig.get('volume_ok')):
                        df = fetch_data(pair,
                                        (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
                                        datetime.now().strftime('%Y-%m-%d'), '1h')
                        if not df.empty:
                            atr_series = ta.atr(df['high'], df['low'], df['close'], length=ATR_LENGTH)
                            current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0001
                            trade_res = execute_trade_with_atr(
                                pair=sig['pair'], signal=sig['signal'], price=sig['price'],
                                df=df, atr=current_atr,
                                volume=TRADE_VOLUME
                            )
                            if trade_res['success']:
                                log_trade(
                                    sig['pair'], sig['signal'], sig['price'],
                                    trade_res['tp'], trade_res['sl'], 'pending', 0.0,
                                    source=sig['model_used'],
                                    ml_conf=sig.get('ml_conf', 0.0),
                                    order_id=trade_res.get('order_id'),
                                    volume=trade_res.get('volume', TRADE_VOLUME)
                                )
                                print(f"✅ Auto-trade: {sig['signal']} {sig['pair']}")
                            else:
                                print(f"❌ Auto-trade failed: {trade_res.get('error')}")
                print("✅ Auto-trade cycle completed.")
        except Exception as e:
            print(f"❌ Auto-trade loop error: {e}")
            traceback.print_exc()
        time.sleep(AUTO_TRADE_INTERVAL_MINUTES * 60)


def start_auto_trade():
    global auto_trade_thread
    if auto_trade_thread is None or not auto_trade_thread.is_alive():
        if AUTO_TRADE_ENABLED and PYTRADER_AVAILABLE:
            auto_trade_thread = threading.Thread(target=auto_trade_loop, daemon=True)
            auto_trade_thread.start()
            print(f"🚀 Auto-trade thread started ({AUTO_TRADE_INTERVAL_MINUTES} min).")
        else:
            print("ℹ️ Auto-trading not started.")


# ---------- Logging helpers ----------
def log_trade(pair, signal, price, tp, sl, result, pnl, source='lightgbm',
              ml_conf=0.0, rule_conf=0.0, order_id=None, volume=None):
    data = {
        'pair': pair, 'signal': signal, 'entry_price': price,
        'tp': tp, 'sl': sl, 'result': result, 'pnl': pnl,
        'timestamp': datetime.now().isoformat(),
        'source': source, 'ml_conf': ml_conf, 'rule_conf': rule_conf,
        'order_id': str(order_id) if order_id is not None else None,
        'volume': volume or TRADE_VOLUME
    }
    data = {k: v for k, v in data.items() if v is not None}
    ok, err = supabase_request('POST', 'trades', data)
    if not ok:
        print(f"❌ log_trade failed: {err}")


def update_trade_result(trade_id, result, pnl):
    supabase_request('PATCH', f'trades?id=eq.{trade_id}', {'result': result, 'pnl': pnl})


def get_min_confidence():
    ok, result = supabase_request('GET', 'config?key=eq.min_confidence')
    if ok and result:
        try:
            return float(result[0].get('value', 0.7))
        except (TypeError, ValueError):
            return 0.7
    return 0.7


def table_exists(table_name):
    ok, _ = supabase_request('GET', table_name + '?limit=1')
    return ok


def init_db():
    if not table_exists('trades') or not table_exists('config'):
        print("\n⚠️  Tables 'trades' and/or 'config' are missing.")
        print("Please create them manually in your Supabase SQL Editor.")
    else:
        print("✅ Tables 'trades' and 'config' exist.")


# ---------- Retraining ----------
_RETRAIN_INTERVAL_HOURS = 24
_RETRAIN_PAIRS = [f"{p}=X" for p in ALL_PAIRS]
_retraining_lock = threading.Lock()
_retraining_thread = None
_auto_retrain_enabled = True


def retrain_model():
    with _retraining_lock:
        print("🔄 Starting LightGBM retrain...")
        try:
            now = datetime.now()
            start_of_period = datetime(now.year - 1, 1, 1).strftime('%Y-%m-%d')
            end = now.strftime('%Y-%m-%d')
            for pair in _RETRAIN_PAIRS:
                df = fetch_data(pair, start_of_period, end, '1h')
                if df.empty:
                    continue
                equity_df = fetch_equity_indices(start_of_period, end)
                if not equity_df.empty:
                    df = _merge_external_data(df, equity_df=equity_df)
                df = add_features(df)
                if df.empty:
                    continue
                model = get_model(normalize_pair(pair), 'lightgbm')
                if model:
                    try:
                        model.train(df)
                    except Exception as e:
                        print(f"⚠️ Train failed for {pair}: {e}")
            print("✅ LightGBM retrain completed.")
            return True
        except Exception as e:
            print(f"❌ Training error: {e}")
            traceback.print_exc()
            return False


def auto_retrain_loop():
    while True:
        if _auto_retrain_enabled:
            retrain_model()
        time.sleep(_RETRAIN_INTERVAL_HOURS * 3600)


def start_auto_retrain_thread():
    global _retraining_thread
    if _retraining_thread is None or not _retraining_thread.is_alive():
        _retraining_thread = threading.Thread(target=auto_retrain_loop, daemon=True)
        _retraining_thread.start()
        print("🚀 Auto-retrain thread started (daily).")


# ============================================================
# Flask routes
# ============================================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/open_trades', methods=['GET'])
def get_open_trades():
    """
    Return open positions with:
      - live current price
      - profit % (distance to TP)
      - PnL in USD
    """
    ok, rows = supabase_request('GET', 'trades?result=eq.pending')
    if not ok or not rows:
        return jsonify([])

    result = []
    for trade in rows:
        pair = normalize_pair(trade.get('pair', ''))
        # Get current price
        price, ok_price = _get_current_price_for_trade(trade)
        if not ok_price:
            price = None

        profit_pct = get_profit_percentage(trade, price) if price else None
        pnl = 0.0
        if price:
            try:
                vol = float(trade.get('volume') or 0.01)
            except (TypeError, ValueError):
                vol = 0.01
            pnl = compute_profit(float(trade['entry_price']), price, pair, vol)

        result.append({
            'id': trade['id'],
            'pair': pair,
            'signal': trade['signal'],
            'entry': float(trade['entry_price']),
            'sl': float(trade['sl']) if trade.get('sl') is not None else None,
            'tp': float(trade['tp']) if trade.get('tp') is not None else None,
            'current_price': float(price) if price else None,
            'profit_pct': round(profit_pct, 2) if profit_pct is not None else None,
            'pnl': round(pnl, 2),
            'volume': float(trade.get('volume') or 0.01),
            'time': trade.get('timestamp', ''),
            'source': trade.get('source', 'lightgbm')
        })
    return jsonify(result)


@app.route('/api/signals', methods=['POST'])
def get_signals():
    data = request.get_json() or {}
    pairs_raw = data.get('pairs', ','.join(ALL_PAIRS))
    pair_list = [normalize_pair(p.strip().upper()) for p in pairs_raw.split(',') if p.strip()]
    interval = normalize_timeframe(data.get('interval', 'h1'))
    atr_period = int(data.get('atr_period', ATR_LENGTH))
    risk_mult = float(data.get('risk_mult', RISK_ATR))
    results = []
    for pair in pair_list:
        model_type = data.get('model_type') or PAIR_MODEL_MAP.get(pair, 'lightgbm')
        res = process_pair(pair, interval, atr_period, risk_mult, REWARD_RATIO, model_type=model_type)
        if res:
            results.append(res)
    return jsonify(results)


@app.route('/api/autotrade', methods=['POST'])
def auto_trade():
    data = request.get_json() or {}
    pairs_raw = data.get('pairs', ','.join(ALL_PAIRS))
    pair_list = [normalize_pair(p.strip().upper()) for p in pairs_raw.split(',') if p.strip()]
    interval = normalize_timeframe(data.get('interval', 'h1'))
    atr_period = int(data.get('atr_period', ATR_LENGTH))
    risk_mult = float(data.get('risk_mult', RISK_ATR))
    volume = float(data.get('volume', TRADE_VOLUME))
    results = []

    for pair in pair_list:
        model_type = data.get('model_type') or PAIR_MODEL_MAP.get(pair, 'lightgbm')
        res = process_pair(pair, interval, atr_period, risk_mult, REWARD_RATIO, model_type=model_type)
        if not res:
            continue

        if (res['signal'] in ('BUY', 'SELL')
                and res.get('can_trade')
                and res.get('trade_ready')
                and res.get('volume_ok')):

            df = fetch_data(pair,
                            (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
                            datetime.now().strftime('%Y-%m-%d'), '1h')
            if not df.empty:
                atr_series = ta.atr(df['high'], df['low'], df['close'], length=ATR_LENGTH)
                current_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0001
                trade_res = execute_trade_with_atr(
                    pair=res['pair'], signal=res['signal'], price=res['price'],
                    df=df, atr=current_atr, volume=volume
                )
                res['trade'] = trade_res
                if trade_res['success']:
                    log_trade(
                        res['pair'], res['signal'], res['price'],
                        trade_res['tp'], trade_res['sl'], 'pending', 0.0,
                        source=model_type, ml_conf=res.get('ml_conf', 0.0),
                        order_id=trade_res.get('order_id'),
                        volume=trade_res.get('volume', volume)
                    )
            else:
                res['trade'] = {"success": False, "error": "Cannot fetch ATR data"}
        else:
            res['trade'] = {"success": False, "error": "Conditions not met"}
        results.append(res)
    return jsonify(results)


@app.route('/api/update_trade', methods=['POST'])
def update_trade():
    data = request.get_json() or {}
    trade_id = data.get('trade_id')
    result = data.get('result')
    pnl = data.get('pnl', 0.0)
    if not trade_id:
        return jsonify({"success": False, "error": "trade_id required"})
    try:
        update_trade_result(trade_id, result, pnl)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/close_trade', methods=['POST'])
def close_trade_endpoint():
    data = request.get_json() or {}
    trade_id = data.get('trade_id')
    if not trade_id:
        return jsonify({"success": False, "error": "trade_id required"}), 400

    ok, rows = supabase_request('GET', f'trades?id=eq.{trade_id}')
    if not ok or not rows:
        return jsonify({"success": False, "error": "Trade not found"}), 404

    trade = rows[0]
    if trade['result'] != 'pending':
        return jsonify({"success": False, "error": "Trade already closed"}), 400

    pair = normalize_pair(trade['pair'])
    price, ok = _get_current_price_for_trade(trade)
    if not ok or price is None:
        return jsonify({"success": False, "error": "Cannot get current price"}), 400

    try:
        vol = float(trade.get('volume') or 0.01)
    except (TypeError, ValueError):
        vol = 0.01

    pnl = compute_profit(float(trade['entry_price']), price, pair, vol)
    closed = close_trade(trade)
    result_status = 'closed_manual' if closed else 'closed_manual_failed'
    update_trade_result(trade_id, result_status, pnl)
    return jsonify({
        "success": True,
        "closed": closed,
        "pnl": round(pnl, 2),
        "result": result_status
    })


@app.route('/api/retrain', methods=['POST'])
def retrain_endpoint():
    try:
        success = retrain_model()
        return jsonify({'success': success, 'message': 'Retraining completed' if success else 'Retraining failed'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global CONFIDENCE_THRESHOLD, MIN_VOLUME, MAX_VOLUME, PROFIT_CLOSE_PCT, TRADE_VOLUME
    if request.method == 'POST':
        data = request.get_json() or {}
        if 'confidence_threshold' in data:
            try:
                val = float(data['confidence_threshold'])
                if 0.5 <= val <= 1.0:
                    CONFIDENCE_THRESHOLD = val
            except (TypeError, ValueError):
                pass
        if 'trade_volume' in data:
            try:
                val = float(data['trade_volume'])
                if val >= 0.01:
                    TRADE_VOLUME = val
            except (TypeError, ValueError):
                pass
        if 'min_volume' in data:
            try:
                val = float(data['min_volume'])
                if val >= 0.0:
                    MIN_VOLUME = val
            except (TypeError, ValueError):
                pass
        if 'max_volume' in data:
            try:
                val = float(data['max_volume'])
                if val >= MIN_VOLUME:
                    MAX_VOLUME = val
            except (TypeError, ValueError):
                pass
        if 'profit_close_pct' in data:
            try:
                val = float(data['profit_close_pct'])
                if 0.0 <= val <= 1.0:
                    PROFIT_CLOSE_PCT = val
            except (TypeError, ValueError):
                pass
        return jsonify({"success": True})
    else:
        return jsonify({
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "trade_volume": TRADE_VOLUME,
            "min_volume": MIN_VOLUME,
            "max_volume": MAX_VOLUME,
            "profit_close_pct": PROFIT_CLOSE_PCT
        })


@app.route('/api/ensemble_status')
def ensemble_status():
    status = {}
    for pair in ALL_PAIRS:
        model = PAIR_MODEL_MAP.get(pair, 'lightgbm')
        ok, rows = supabase_request('GET', f'trades?pair=eq.{pair}&result=neq.pending')
        model_stats = {}
        if ok and rows:
            for r in rows:
                src = r.get('source', 'unknown')
                model_stats.setdefault(src, {'wins': 0, 'total': 0})
                model_stats[src]['total'] += 1
                if r['result'] == 'win':
                    model_stats[src]['wins'] += 1
            for src in model_stats:
                t = model_stats[src]['total']
                model_stats[src]['win_rate'] = model_stats[src]['wins'] / t if t > 0 else 0
        status[pair] = {'selected': model, 'stats': model_stats}
    return jsonify(status)


@app.route('/api/set_model', methods=['POST'])
def set_model():
    data = request.get_json() or {}
    pair = normalize_pair(data.get('pair', ''))
    model_type = data.get('model_type')
    if not pair or not model_type:
        return jsonify({"success": False, "error": "pair and model_type required"}), 400
    if pair not in ALL_PAIRS:
        return jsonify({"success": False, "error": f"Pair {pair} not allowed"}), 400
    allowed_models = ['rule', 'ensemble', 'bollinger', 'williams_r', 'cci',
                      'stochastic', 'pairs_trading', 'macd', 'rsi', 'lightgbm']
    if model_type not in allowed_models:
        return jsonify({"success": False, "error": f"Model {model_type} not supported"}), 400
    PAIR_MODEL_MAP[pair] = model_type
    return jsonify({"success": True, "pair": pair, "model": model_type})


# ---------- Startup ----------
if __name__ == '__main__':
    init_db()
    print(f"✅ Database ready. Min confidence: {get_min_confidence()}")
    print(f"🔧 Model mapping:")
    for pair, model in PAIR_MODEL_MAP.items():
        print(f"   {pair}: {model}")
    print(f"📊 ATR length: {ATR_LENGTH}, SL mult: {ATR_MULTIPLIER_SL}, TP mult: {ATR_MULTIPLIER_TP}")
    print(f"🔄 Silent trailing stop: {'ON' if TRAILING_STOP_ACTIVE else 'OFF'} "
          f"(locks 30%/50%/70% at 50/70/90%)")
    print(f"🎯 Silent force TP at {FORCE_TP_PERCENT*100:.0f}% of entry→TP distance")
    print(f"📈 Min RR: {MIN_RR}")
    print(f"📊 LightGBM: TP={LGB_TP_MULT}, SL={LGB_SL_MULT}, horizon={LGB_TIME_HORIZON}")
    print(f"🔰 Filters: Confidence={CONFIDENCE_THRESHOLD:.2f}, Volume={TRADE_VOLUME:.2f}")

    if PYTRADER_AVAILABLE:
        connect_to_mt4()

    if TWELVE_DATA_API_KEY:
        test_price = get_live_price_twelve('EURUSD')
        if test_price:
            print(f"✅ Twelve Data works: EURUSD = {test_price}")
        else:
            print("⚠️ Twelve Data test failed – will fall back to MT4/yfinance")

    preload_models()
    start_auto_retrain_thread()
    start_trade_monitor()
    start_auto_trade()

    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)