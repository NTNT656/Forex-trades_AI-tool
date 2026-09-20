# forward_test.py – Lightweight forward test (LightGBM + classic strategies)

import os
import requests
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from datetime import datetime, timedelta
from dotenv import load_dotenv

from lightgbm_model import LightGBMModel
from patterns_light import detect_candlestick_patterns, get_pattern_signal, detect_chart_patterns

warnings.filterwarnings('ignore')
load_dotenv()

CONFIDENCE_THRESHOLD = 0.70
MIN_VOLUME = 0.01
MAX_VOLUME = 1.00
MIN_VOLATILITY_RATIO = 0.002
MAX_VOLATILITY_RATIO = 0.020
VOLATILITY_THRESHOLD = 0.010
HIGH_VOL_SL_MULT = 1.5
HIGH_VOL_TP_MULT = 2.5
LOW_VOL_SL_MULT = 2.0
LOW_VOL_TP_MULT = 3.0

ALL_PAIRS = ['EURUSD', 'GBPUSD', 'AUDUSD', 'USDCAD', 'USDCHF',
             'EURGBP', 'EURJPY', 'NZDUSD', 'GBPJPY', 'USDJPY']

PAIRS_TRADING_CORRELATED = {
    'EURUSD': 'GBPUSD', 'GBPUSD': 'EURUSD',
    'AUDUSD': 'NZDUSD', 'NZDUSD': 'AUDUSD',
    'USDJPY': 'EURJPY', 'EURJPY': 'USDJPY',
}

ATR_LENGTH = 14
TRAILING_STOP_ACTIVE = True
VOLATILITY_FILTER = 0.8
MIN_RR = 2.0
WIN_RATE_THRESHOLD = 0.6
LOW_RR_ALLOWED = 1.2

LGB_TP_MULT = 0.02
LGB_SL_MULT = 0.012
LGB_TIME_HORIZON = 30
LGB_MIN_CONFIDENCE = 0.55

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

INITIAL_BALANCE = 10000.0
LOT_SIZE = 0.30
SPREAD = 0.0001
COMMISSION_PER_LOT = 5.0

TEST_START = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
TEST_END = datetime.now().strftime('%Y-%m-%d')
INTERVAL = '1h'


# ---------- Supabase minimal client (for loading models) ----------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if SUPABASE_URL and not SUPABASE_URL.endswith('/'):
    SUPABASE_URL += '/'
if SUPABASE_URL and 'rest/v1' not in SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.rstrip('/') + '/rest/v1/'


class TableWrapper:
    def __init__(self, base_url, key, table_name):
        self.base_url, self.key, self.table_name = base_url, key, table_name
        self.filters = {}
        self.order_by = None
        self.limit_val = None

    def select(self, fields):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, col, desc=False):
        self.order_by = (col, desc)
        return self

    def limit(self, n):
        self.limit_val = n
        return self

    def execute(self):
        url = self.base_url + self.table_name
        params = {k: f'eq.{v}' for k, v in self.filters.items()}
        if self.order_by:
            params['order'] = f'{self.order_by[0]}.desc' if self.order_by[1] else f'{self.order_by[0]}.asc'
        if self.limit_val:
            params['limit'] = self.limit_val
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        resp = requests.get(url, params=params, headers=headers)

        class R:
            def __init__(self, data): self.data = data

        return R(resp.json() if resp.status_code == 200 else [])


class SupabaseWrapper:
    def __init__(self, url, key):
        self.url, self.key = url, key

    def table(self, name):
        return TableWrapper(self.url, self.key, name)


supabase = SupabaseWrapper(SUPABASE_URL, SUPABASE_SERVICE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_KEY else None


def fetch_data(pair, start, end, interval='1h'):
    if not pair.endswith('=X'):
        pair = pair + '=X'
    try:
        data = yf.download(pair, start=start, end=end, interval=interval,
                           progress=False, timeout=60, auto_adjust=False,
                           threads=True, ignore_tz=True)
        if not data.empty:
            if 'Adj Close' in data.columns:
                data = data.drop(columns=['Adj Close'])
            data.columns = ['open', 'high', 'low', 'close', 'volume']
            return data
    except Exception as e:
        print(f"Error fetching {pair}: {e}")
    return pd.DataFrame()


def add_features(df):
    if df.empty or len(df) < 20:
        return df
    df = df.copy()
    df['rsi_14'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9'] if macd is not None else 0
    df['macd_signal'] = macd['MACDs_12_26_9'] if macd is not None and 'MACDs_12_26_9' in macd.columns else np.nan
    df['atr_14'] = ta.atr(df['high'], df['low'], df['close'], length=ATR_LENGTH)
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
    df['adx_14'] = adx['ADX_14'] if adx is not None else np.nan
    df['volatility_20'] = ret.rolling(20).std()
    df['volatility_ratio'] = df['volatility_20'] / df['volatility_20'].rolling(10).mean()
    df['volatility_ratio'] = df['volatility_ratio'].replace([np.inf, -np.inf], np.nan)
    for lag in [1, 2]:
        df[f'open_prev_{lag}'] = df['open'].shift(lag)
        df[f'high_prev_{lag}'] = df['high'].shift(lag)
        df[f'low_prev_{lag}'] = df['low'].shift(lag)
        df[f'close_prev_{lag}'] = df['close'].shift(lag)
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = df[col].ffill()
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(0)
    return df


# ---------- Signal functions ----------
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


def compute_rule_signal(df, min_confidence=CONFIDENCE_THRESHOLD):
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
            if pat in ['double_bottom', 'inverse_head_shoulders'] and signal == 'BUY':
                conf = min(1.0, conf + 0.15)
            elif pat in ['double_top', 'head_shoulders'] and signal == 'SELL':
                conf = min(1.0, conf + 0.15)
        if signal == 'BUY' and trend == 'uptrend':
            conf = min(1.0, conf + 0.1)
        elif signal == 'SELL' and trend == 'downtrend':
            conf = min(1.0, conf + 0.1)
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
        return 'BUY', 0.75
    elif w > -20:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def cci_signal(df, min_confidence=0.7):
    if len(df) < 20:
        return 'HOLD', 0.0
    cci = df['cci_20'].iloc[-1]
    if cci < -100:
        return 'BUY', 0.75
    elif cci > 100:
        return 'SELL', 0.75
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


def rsi_signal(df, min_confidence=0.7):
    if len(df) < 14:
        return 'HOLD', 0.0
    rsi = df['rsi_14'].iloc[-1]
    if rsi < 30:
        return 'BUY', 0.75
    elif rsi > 70:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def macd_signal(df, min_confidence=0.7):
    if len(df) < 26:
        return 'HOLD', 0.0
    macd_line = df['macd']
    signal_line = df['macd_signal']
    if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
        return 'BUY', 0.75
    elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def ensemble_signal(df, secondary_df=None, min_confidence=0.7):
    signals, confidences = [], []
    for fn in [bollinger_bands_signal, williams_r_signal, cci_signal, stochastic_signal]:
        s, c = fn(df)
        if s != 'HOLD':
            signals.append(s); confidences.append(c)
    if secondary_df is not None and len(df) > 20 and len(secondary_df) > 20:
        common_idx = df.index.intersection(secondary_df.index)
        if len(common_idx) >= 20:
            p1 = df.loc[common_idx, 'close']
            p2 = secondary_df.loc[common_idx, 'close']
            spread = p1 / p2
            std = spread.rolling(20).std().iloc[-1]
            if std and not np.isnan(std):
                z = (spread.iloc[-1] - spread.rolling(20).mean().iloc[-1]) / std
                if z < -2:
                    signals.append('BUY'); confidences.append(0.75)
                elif z > 2:
                    signals.append('SELL'); confidences.append(0.75)
    if not signals:
        return 'HOLD', 0.0
    buy = sum(1 for s in signals if s == 'BUY')
    sell = sum(1 for s in signals if s == 'SELL')
    if buy > sell:
        return 'BUY', np.mean(confidences)
    elif sell > buy:
        return 'SELL', np.mean(confidences)
    return 'HOLD', 0.0


# ---------- Forward test ----------
def run_forward_test(pair, start_date, end_date, interval='1h',
                     model_type='lightgbm', profit_close_pct=0.30):
    close_threshold = profit_close_pct * 100 if profit_close_pct < 1.0 else 0
    print(f"\n--- {pair} (model={model_type}, close at {close_threshold}%) ---")

    df = fetch_data(pair, start_date, end_date, interval)
    if df.empty:
        return None
    df = add_features(df)
    if df.empty or len(df) < 60:
        return None

    secondary_df = None
    if model_type in ('pairs_trading', 'ensemble') and pair in PAIRS_TRADING_CORRELATED:
        secondary_df = fetch_data(PAIRS_TRADING_CORRELATED[pair], start_date, end_date, interval)

    model = None
    signal_func = None

    if model_type == 'lightgbm':
        model = LightGBMModel(
            tp_mult=LGB_TP_MULT, sl_mult=LGB_SL_MULT,
            time_horizon=LGB_TIME_HORIZON,
            feature_columns=FEATURE_COLUMNS,
            supabase_client=supabase
        )
        if model.model is None:
            print(f"  No trained LightGBM for {pair}, skipping")
            return None
    elif model_type == 'rule':
        signal_func = compute_rule_signal
    elif model_type == 'bollinger':
        signal_func = bollinger_bands_signal
    elif model_type == 'williams_r':
        signal_func = williams_r_signal
    elif model_type == 'cci':
        signal_func = cci_signal
    elif model_type == 'stochastic':
        signal_func = stochastic_signal
    elif model_type == 'rsi':
        signal_func = rsi_signal
    elif model_type == 'macd':
        signal_func = macd_signal
    elif model_type == 'ensemble':
        pass
    else:
        print(f"Unknown strategy {model_type}")
        return None

    balance = INITIAL_BALANCE
    in_position = False
    entry_price = 0.0; sl = 0.0; tp = 0.0; signal = 'HOLD'
    trades = []
    volume = LOT_SIZE

    for i in range(60, len(df)):
        window = df.iloc[:i + 1]
        current_price = df['close'].iloc[i]
        current_atr = df['atr_14'].iloc[i]

        if model_type == 'ensemble':
            sig, conf = ensemble_signal(window, secondary_df=secondary_df)
        elif model_type == 'lightgbm' and model is not None:
            sig, conf = model.predict(window, min_confidence=LGB_MIN_CONFIDENCE)
            if conf < CONFIDENCE_THRESHOLD:
                sig = 'HOLD'
        elif signal_func is not None:
            sig, conf = signal_func(window, min_confidence=CONFIDENCE_THRESHOLD)
        else:
            sig, conf = 'HOLD', 0.0

        if in_position:
            if close_threshold > 0:
                total = tp - entry_price if signal == 'BUY' else entry_price - tp
                if total > 0:
                    cur_profit = current_price - entry_price if signal == 'BUY' else entry_price - current_price
                    if cur_profit / total * 100 >= close_threshold:
                        exit_price = current_price - SPREAD if signal == 'BUY' else current_price + SPREAD
                        pnl_pct = (exit_price - entry_price) / entry_price * 100 if signal == 'BUY' else (entry_price - exit_price) / entry_price * 100
                        trades[-1].update({'exit_price': exit_price, 'pnl': pnl_pct,
                                           'net_pnl': pnl_pct - COMMISSION_PER_LOT * 2,
                                           'exit_time': df.index[i],
                                           'exit_reason': f'early_{int(close_threshold)}%'})
                        in_position = False
                        continue

            if signal == 'BUY':
                if current_price >= tp:
                    exit_price = current_price - SPREAD
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                elif current_price <= sl:
                    exit_price = current_price - SPREAD
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    exit_price = None
            else:
                if current_price <= tp:
                    exit_price = current_price + SPREAD
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                elif current_price >= sl:
                    exit_price = current_price + SPREAD
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                else:
                    exit_price = None

            if exit_price is not None:
                trades[-1].update({'exit_price': exit_price, 'pnl': pnl_pct,
                                   'net_pnl': pnl_pct - COMMISSION_PER_LOT * 2,
                                   'exit_time': df.index[i],
                                   'exit_reason': 'TP' if (signal == 'BUY' and current_price >= tp) or (signal == 'SELL' and current_price <= tp) else 'SL'})
                in_position = False

        if not in_position and sig != 'HOLD':
            vol_ratio = current_atr / current_price if current_price > 0 else 0
            if vol_ratio < MIN_VOLATILITY_RATIO or vol_ratio > MAX_VOLATILITY_RATIO:
                continue
            sl_dist = current_atr * ATR_MULTIPLIER_SL
            tp_dist = current_atr * ATR_MULTIPLIER_TP
            if tp_dist < MIN_RR * sl_dist:
                tp_dist = MIN_RR * sl_dist
            if sig == 'BUY':
                sl = current_price - sl_dist
                tp = current_price + tp_dist
                entry_price = current_price + SPREAD
            else:
                sl = current_price + sl_dist
                tp = current_price - tp_dist
                entry_price = current_price - SPREAD
            signal = sig
            in_position = True
            trades.append({
                'entry_time': df.index[i], 'entry_price': entry_price,
                'signal': signal, 'sl': sl, 'tp': tp,
                'exit_price': np.nan, 'pnl': 0.0, 'net_pnl': 0.0,
                'exit_time': np.nan, 'confidence': conf,
                'model_used': model_type, 'exit_reason': 'open', 'volume': volume
            })

    if not trades:
        print("No trades.")
        return None

    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['net_pnl'] > 0]
    win_rate = len(wins) / len(df_trades) * 100
    total_pnl = df_trades['net_pnl'].sum()
    print(f"Trades: {len(df_trades)}, Win rate: {win_rate:.1f}%, PnL: {total_pnl:.2f}%")
    return {
        'pair': pair, 'model': model_type,
        'trades': len(df_trades), 'win_rate': win_rate,
        'total_pnl': total_pnl
    }


if __name__ == '__main__':
    strategies = ['lightgbm', 'rule', 'bollinger', 'williams_r', 'cci',
                  'stochastic', 'rsi', 'macd', 'ensemble']

    all_results = {}
    for model_type in strategies:
        print(f"\n{'='*60}\nSTRATEGY: {model_type.upper()}\n{'='*60}")
        results = []
        for pair in ALL_PAIRS:
            res = run_forward_test(pair, TEST_START, TEST_END, INTERVAL,
                                   model_type=model_type, profit_close_pct=0.30)
            if res:
                results.append(res)
        if results:
            df_res = pd.DataFrame(results)
            all_results[model_type] = {
                'trades': df_res['trades'].sum(),
                'pnl': df_res['total_pnl'].sum(),
                'win_rate': df_res['win_rate'].mean()
            }

    print("\n\n========== COMPARISON ==========")
    for m, s in all_results.items():
        print(f"{m.upper():15s} | trades={s['trades']:4d} | win_rate={s['win_rate']:5.1f}% | PnL={s['pnl']:8.2f}%")