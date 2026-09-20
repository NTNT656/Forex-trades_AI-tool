# backtest.py – Lightweight walk-forward backtest with LightGBM + classic strategies
# REMOVED: SVM, HMM, ARIMA, SR Trend, SMC, scipy-dependent chart patterns
# KEPT: LightGBM, classic indicators, ensemble

import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

from lightgbm_model import LightGBMModel
from patterns_light import detect_candlestick_patterns, get_pattern_signal, detect_chart_patterns

# ---------- Configuration ----------
PAIRS = [
    'EURUSD=X', 'GBPUSD=X', 'AUDUSD=X', 'USDCAD=X', 'USDCHF=X',
    'EURGBP=X', 'EURJPY=X', 'NZDUSD=X', 'GBPJPY=X', 'USDJPY=X'
]
START_DATE = '2020-01-01'
END_DATE = datetime.now().strftime('%Y-%m-%d')
INTERVAL = '1d'
INITIAL_BALANCE = 10000
LOT_SIZE = 0.30
SPREAD = 0.0001
COMMISSION_PER_LOT = 5.0

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
PROFIT_CLOSE_PCT = 0.30

ATR_LENGTH = 14
ATR_MULTIPLIER_SL = 2.5
ATR_MULTIPLIER_TP = 2.0
TRAILING_STOP_ACTIVE = True
TRAILING_STEP = 0.5
VOLATILITY_FILTER = 0.8
MIN_RR = 2.0
WIN_RATE_THRESHOLD = 0.6
LOW_RR_ALLOWED = 1.2

LGB_TP_MULT = 0.02
LGB_SL_MULT = 0.012
LGB_TIME_HORIZON = 30
LGB_MIN_CONFIDENCE = 0.55

INITIAL_TRAIN_BARS = 1500
TEST_BARS = 300
STEP = 300

PAIRS_TRADING_CORRELATED = {
    'EURUSD=X': 'GBPUSD=X', 'GBPUSD=X': 'EURUSD=X',
    'AUDUSD=X': 'NZDUSD=X', 'NZDUSD=X': 'AUDUSD=X',
    'USDJPY=X': 'EURJPY=X', 'EURJPY=X': 'USDJPY=X',
}

FEATURES = [
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


# ---------- Data fetching ----------
_equity_cache = {}


def fetch_equity_data(start_date, end_date):
    cache_key = f"{start_date}_{end_date}"
    if cache_key in _equity_cache:
        return _equity_cache[cache_key]
    symbols = {
        'sp500': '^GSPC', 'dax': '^GDAXI', 'ftse': '^FTSE',
        'nikkei': '^N225', 'asx': '^AXJO', 'hsi': '^HSI', 'dxy': 'DX-Y.NYB'
    }
    combined = pd.DataFrame()
    for name, symbol in symbols.items():
        try:
            data = yf.download(symbol, start=start_date, end=end_date, progress=False, timeout=60)
            if not data.empty:
                price_series = data['Adj Close'] if 'Adj Close' in data.columns else data['Close']
                if isinstance(price_series, pd.DataFrame):
                    price_series = price_series.iloc[:, 0]
                price_series.name = name
                combined = price_series.to_frame() if combined.empty else combined.join(price_series, how='outer')
        except Exception as e:
            print(f"⚠️ Could not fetch {name}: {e}")
            combined[name] = np.nan
    combined = combined.ffill().dropna(how='all')
    _equity_cache[cache_key] = combined
    return combined


def fetch_data(pair, start, end, interval):
    tickers = [pair, pair.replace('=X', '')]
    data = pd.DataFrame()
    for ticker in tickers:
        try:
            data = yf.download(ticker, start=start, end=end, interval=interval,
                               progress=False, auto_adjust=False, timeout=60,
                               multi_level_index=False)
            if not data.empty:
                break
        except Exception:
            continue
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.columns = [c.lower() for c in data.columns]
    for c in ['open', 'high', 'low', 'close']:
        if c not in data.columns:
            data[c] = data.get('close', np.nan)
    return data[['open', 'high', 'low', 'close']]


def add_features(df):
    if df.empty or len(df) < 20:
        return pd.DataFrame()
    df = df.copy()
    df['rsi_14'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd'] = macd['MACD_12_26_9'] if macd is not None else 0
    df['macd_signal'] = macd['MACDs_12_26_9'] if macd is not None and 'MACDs_12_26_9' in macd.columns else np.nan
    df['atr_14'] = ta.atr(df['high'], df['low'], df['close'], length=14)
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
    for c in FEATURES:
        if c not in df.columns:
            df[c] = 0.0
    df = df.replace([np.inf, -np.inf], np.nan)
    usable = [c for c in FEATURES if c in df.columns]
    df = df.dropna(subset=usable)
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


def compute_rule_signal(df, min_confidence=0.0):
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
    elif chart_patterns:
        bullish = ['double_bottom', 'inverse_head_shoulders', 'ascending_triangle']
        bearish = ['double_top', 'head_shoulders', 'descending_triangle']
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


def sma_crossover_signal(df, min_confidence=0.7):
    if len(df) < 50:
        return 'HOLD', 0.0
    sma20 = df['close'].rolling(20).mean()
    sma50 = df['close'].rolling(50).mean()
    if sma20.iloc[-1] > sma50.iloc[-1] and sma20.iloc[-2] <= sma50.iloc[-2]:
        return 'BUY', 0.8
    elif sma20.iloc[-1] < sma50.iloc[-1] and sma20.iloc[-2] >= sma50.iloc[-2]:
        return 'SELL', 0.8
    return 'HOLD', 0.0


def ema_crossover_signal(df, min_confidence=0.7):
    if len(df) < 26:
        return 'HOLD', 0.0
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    if ema12.iloc[-1] > ema26.iloc[-1] and ema12.iloc[-2] <= ema26.iloc[-2]:
        return 'BUY', 0.75
    elif ema12.iloc[-1] < ema26.iloc[-1] and ema12.iloc[-2] >= ema26.iloc[-2]:
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


def bollinger_bands_signal(df, min_confidence=0.7):
    if len(df) < 20:
        return 'HOLD', 0.0
    bb_lower = df['bb_lower'].iloc[-1]
    bb_upper = df['bb_upper'].iloc[-1]
    price = df['close'].iloc[-1]
    if price <= bb_lower:
        return 'BUY', 0.75
    elif price >= bb_upper:
        return 'SELL', 0.75
    return 'HOLD', 0.0


def donchian_breakout_signal(df, min_confidence=0.7, lookback=20):
    if len(df) < lookback:
        return 'HOLD', 0.0
    high = df['high'].iloc[-lookback:-1].max()
    low = df['low'].iloc[-lookback:-1].min()
    price = df['close'].iloc[-1]
    if price > high:
        return 'BUY', 0.8
    elif price < low:
        return 'SELL', 0.8
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


def williams_r_signal(df, min_confidence=0.7):
    if len(df) < 14:
        return 'HOLD', 0.0
    w = df['williams_r'].iloc[-1]
    if w < -80:
        return 'BUY', 0.7
    elif w > -20:
        return 'SELL', 0.7
    return 'HOLD', 0.0


def cci_signal(df, min_confidence=0.7):
    if len(df) < 20:
        return 'HOLD', 0.0
    cci = df['cci_20'].iloc[-1]
    if cci < -100:
        return 'BUY', 0.7
    elif cci > 100:
        return 'SELL', 0.7
    return 'HOLD', 0.0


def roc_signal(df, min_confidence=0.7, period=10):
    if len(df) < period:
        return 'HOLD', 0.0
    roc = df['close'].pct_change(period) * 100
    if roc.iloc[-1] > 0 and roc.iloc[-2] <= 0:
        return 'BUY', 0.7
    elif roc.iloc[-1] < 0 and roc.iloc[-2] >= 0:
        return 'SELL', 0.7
    return 'HOLD', 0.0


def pairs_trading_signal(first_df, second_df, lookback=20, z_thresh=2.0):
    if len(first_df) < lookback or len(second_df) < lookback:
        return 'HOLD', 0.0
    common_idx = first_df.index.intersection(second_df.index)
    if len(common_idx) < lookback:
        return 'HOLD', 0.0
    price1 = first_df.loc[common_idx, 'close']
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


# ---------- Walk-forward engine ----------
def run_walk_forward(pair, start, end, interval,
                     initial_train, test_bars, step,
                     model_type='lightgbm'):
    df = fetch_data(pair, start, end, interval)
    if df.empty:
        return None
    equity_df = fetch_equity_data(start, end)
    if not equity_df.empty:
        df = df.reset_index()
        date_col = 'Date' if 'Date' in df.columns else df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        equity_df = equity_df.copy()
        equity_df.index = pd.to_datetime(equity_df.index)
        df = df.merge(equity_df, left_on=date_col, right_index=True, how='left')
        for c in equity_df.columns:
            if c in df.columns:
                df[c] = df[c].ffill()
        df = df.set_index(date_col)

    df = add_features(df)
    if df.empty or len(df) < initial_train + test_bars:
        print(f"Not enough data for {pair}")
        return None

    df.attrs['pair'] = pair

    secondary_df = None
    if model_type == 'pairs_trading' and pair in PAIRS_TRADING_CORRELATED:
        secondary_df = fetch_data(PAIRS_TRADING_CORRELATED[pair], start, end, interval)

    results = []
    train_end = initial_train
    test_start = train_end
    test_end = test_start + test_bars
    iteration = 1

    while test_end <= len(df):
        train_df = df.iloc[0:train_end].copy()
        test_df = df.iloc[test_start:test_end].copy()

        signal_funcs = {}
        signal_funcs['rule'] = compute_rule_signal
        signal_funcs['sma_crossover'] = sma_crossover_signal
        signal_funcs['ema_crossover'] = ema_crossover_signal
        signal_funcs['rsi'] = rsi_signal
        signal_funcs['macd'] = macd_signal
        signal_funcs['bollinger'] = bollinger_bands_signal
        signal_funcs['donchian'] = donchian_breakout_signal
        signal_funcs['stochastic'] = stochastic_signal
        signal_funcs['williams_r'] = williams_r_signal
        signal_funcs['cci'] = cci_signal
        signal_funcs['roc'] = roc_signal

        # LightGBM
        lgb_model = LightGBMModel(
            tp_mult=LGB_TP_MULT, sl_mult=LGB_SL_MULT,
            time_horizon=LGB_TIME_HORIZON,
            feature_columns=FEATURES,
            supabase_client=None
        )
        if lgb_model.train(train_df):
            def signal_func_lgb(df, min_confidence):
                sig, conf = lgb_model.predict(df, min_confidence=LGB_MIN_CONFIDENCE)
                if conf < min_confidence:
                    return 'HOLD', 0.0
                return sig, conf
            signal_funcs['lightgbm'] = signal_func_lgb
        else:
            signal_funcs['lightgbm'] = None

        if secondary_df is not None:
            def signal_func_pairs(df, min_confidence):
                common_idx = df.index.intersection(secondary_df.index)
                if len(common_idx) < 20:
                    return 'HOLD', 0.0
                return pairs_trading_signal(df.loc[common_idx], secondary_df.loc[common_idx], min_confidence=min_confidence)
            signal_funcs['pairs_trading'] = signal_func_pairs
        else:
            signal_funcs['pairs_trading'] = None

        if model_type in signal_funcs and signal_funcs[model_type] is not None:
            current_signal_func = signal_funcs[model_type]
        else:
            current_signal_func = signal_funcs['rule']

        trades = []
        in_position = False
        entry_price = 0.0
        sl = 0.0
        tp = 0.0
        signal = 'HOLD'
        balance = INITIAL_BALANCE
        trade_history = []

        for i in range(60, len(test_df)):
            window = test_df.iloc[:i + 1]
            current_price = test_df['close'].iloc[i]
            current_atr = test_df['atr_14'].iloc[i]

            if in_position:
                hit = False
                if PROFIT_CLOSE_PCT > 0:
                    total = tp - entry_price if signal == 'BUY' else entry_price - tp
                    if total > 0:
                        cur_profit = current_price - entry_price if signal == 'BUY' else entry_price - current_price
                        if cur_profit / total >= PROFIT_CLOSE_PCT:
                            exit_price = current_price - SPREAD if signal == 'BUY' else current_price + SPREAD
                            pnl_pct = (exit_price - entry_price) / entry_price * 100 if signal == 'BUY' else (entry_price - exit_price) / entry_price * 100
                            trades[-1].update({'exit_price': exit_price, 'pnl': pnl_pct,
                                               'net_pnl': pnl_pct - COMMISSION_PER_LOT * 2,
                                               'exit_time': test_df.index[i],
                                               'exit_reason': f'early_{int(PROFIT_CLOSE_PCT*100)}%'})
                            in_position = False
                            trade_history.append({'net_pnl': trades[-1]['net_pnl']})
                            continue

                if signal == 'BUY':
                    if current_price >= tp or current_price <= sl:
                        exit_price = current_price - SPREAD
                        pnl_pct = (exit_price - entry_price) / entry_price * 100
                        trades[-1].update({'exit_price': exit_price, 'pnl': pnl_pct,
                                           'net_pnl': pnl_pct - COMMISSION_PER_LOT * 2,
                                           'exit_time': test_df.index[i],
                                           'exit_reason': 'TP' if current_price >= tp else 'SL'})
                        hit = True
                else:
                    if current_price <= tp or current_price >= sl:
                        exit_price = current_price + SPREAD
                        pnl_pct = (entry_price - exit_price) / entry_price * 100
                        trades[-1].update({'exit_price': exit_price, 'pnl': pnl_pct,
                                           'net_pnl': pnl_pct - COMMISSION_PER_LOT * 2,
                                           'exit_time': test_df.index[i],
                                           'exit_reason': 'TP' if current_price <= tp else 'SL'})
                        hit = True
                if hit:
                    in_position = False
                    trade_history.append({'net_pnl': trades[-1]['net_pnl']})

            if not in_position:
                sig, conf = current_signal_func(window, min_confidence=CONFIDENCE_THRESHOLD)
                if sig != 'HOLD':
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
                        'entry_time': test_df.index[i],
                        'entry_price': entry_price,
                        'signal': signal,
                        'sl': sl,
                        'tp': tp,
                        'exit_price': np.nan,
                        'pnl': 0.0,
                        'net_pnl': 0.0,
                        'exit_time': np.nan,
                        'confidence': conf,
                        'exit_reason': 'open'
                    })

        if trades:
            df_trades = pd.DataFrame(trades)
            wins = df_trades[df_trades['net_pnl'] > 0]
            win_rate = len(wins) / len(df_trades) * 100
            total_pnl = df_trades['net_pnl'].sum()
        else:
            win_rate = 0
            total_pnl = 0

        results.append({
            'iteration': iteration, 'trades': len(trades),
            'win_rate': win_rate, 'total_pnl': total_pnl
        })

        train_end += step
        test_start += step
        test_end += step
        iteration += 1

    if not results:
        return None
    return pd.DataFrame(results)


if __name__ == '__main__':
    print("==== LIGHTWEIGHT BACKTEST ====")
    print(f"Data: {INTERVAL} from {START_DATE} to {END_DATE}")
    print(f"Train: {INITIAL_TRAIN_BARS} bars, Test: {TEST_BARS}, Step: {STEP}")

    models_to_test = ['lightgbm', 'rule', 'bollinger', 'williams_r', 'cci',
                      'stochastic', 'macd', 'rsi', 'sma_crossover',
                      'ema_crossover', 'donchian', 'roc']

    all_results = {}
    for m in models_to_test:
        print(f"\n{'='*60}\nRunning: {m.upper()}\n{'='*60}")
        pair_results = {}
        for pair in PAIRS:
            res = run_walk_forward(
                pair=pair, start=START_DATE, end=END_DATE, interval=INTERVAL,
                initial_train=INITIAL_TRAIN_BARS, test_bars=TEST_BARS, step=STEP,
                model_type=m
            )
            if res is not None:
                pair_results[pair] = res
                print(f"  {pair}: Win rate {res['win_rate'].mean():.1f}%, PnL {res['total_pnl'].sum():.2f}%")
        all_results[m] = pair_results

    print("\n\n========== FINAL COMPARISON ==========")
    for m, pair_results in all_results.items():
        total_pnl = sum(r['total_pnl'].sum() for r in pair_results.values())
        avg_wr = np.mean([r['win_rate'].mean() for r in pair_results.values()]) if pair_results else 0
        total_trades = sum(r['trades'].sum() for r in pair_results.values())
        print(f"{m.upper():15s} | trades={total_trades:4d} | win_rate={avg_wr:5.1f}% | PnL={total_pnl:8.2f}%")