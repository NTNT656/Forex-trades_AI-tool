# patterns_light.py – Pure numpy lightweight pattern detection
# Replaces candlestick_patterns.py and chart_patterns.py

import numpy as np
import pandas as pd


def detect_candlestick_patterns(df):
    """Detect classic candlestick patterns using pure numpy (last 3 bars)."""
    patterns = {}
    if len(df) < 3:
        return patterns
    try:
        o = df['open'].values[-3:]
        h = df['high'].values[-3:]
        l = df['low'].values[-3:]
        c = df['close'].values[-3:]

        def body(open_, close_):
            return abs(close_ - open_)

        def color(open_, close_):
            return 'green' if close_ > open_ else 'red'

        c1, c2, c3 = (o[0], c[0]), (o[1], c[1]), (o[2], c[2])

        # Morning Star
        if (color(*c1) == 'red' and body(*c1) > body(*c2) * 0.5 and
                body(*c2) < body(*c1) * 0.3 and color(*c3) == 'green' and c3[1] > c1[1]):
            patterns['MORNING_STAR'] = 'bullish'

        # Evening Star
        if (color(*c1) == 'green' and body(*c1) > body(*c2) * 0.5 and
                body(*c2) < body(*c1) * 0.3 and color(*c3) == 'red' and c3[1] < c1[1]):
            patterns['EVENING_STAR'] = 'bearish'

        # Morning Doji Star
        if (color(*c1) == 'red' and abs(c2[0] - c2[1]) < 1e-6 and
                color(*c3) == 'green' and c3[1] > c1[1]):
            patterns['MORNING_DOJI_STAR'] = 'bullish'

        # Evening Doji Star
        if (color(*c1) == 'green' and abs(c2[0] - c2[1]) < 1e-6 and
                color(*c3) == 'red' and c3[1] < c1[1]):
            patterns['EVENING_DOJI_STAR'] = 'bearish'

        # Three White Soldiers
        if (color(*c1) == 'green' and color(*c2) == 'green' and color(*c3) == 'green'
                and c1[1] < c2[1] < c3[1] and body(*c1) > 1e-3 and body(*c2) > 1e-3 and body(*c3) > 1e-3):
            patterns['THREE_WHITE_SOLDIERS'] = 'bullish'

        # Three Black Crows
        if (color(*c1) == 'red' and color(*c2) == 'red' and color(*c3) == 'red'
                and c1[1] > c2[1] > c3[1] and body(*c1) > 1e-3 and body(*c2) > 1e-3 and body(*c3) > 1e-3):
            patterns['THREE_BLACK_CROWS'] = 'bearish'

        # Bullish Engulfing
        if (color(*c1) == 'red' and color(*c2) == 'green'
                and c2[0] < c1[1] and c2[1] > c1[0]):
            patterns['BULLISH_ENGULFING'] = 'bullish'

        # Bearish Engulfing
        if (color(*c1) == 'green' and color(*c2) == 'red'
                and c2[0] > c1[1] and c2[1] < c1[0]):
            patterns['BEARISH_ENGULFING'] = 'bearish'

        # Piercing Line
        if (color(*c1) == 'red' and color(*c2) == 'green'
                and c2[0] < c1[1] and c2[1] > (c1[0] + c1[1]) / 2 and c2[1] < c1[0]):
            patterns['PIERCING_LINE'] = 'bullish'

        # Dark Cloud Cover
        if (color(*c1) == 'green' and color(*c2) == 'red'
                and c2[0] > c1[1] and c2[1] < (c1[0] + c1[1]) / 2 and c2[1] > c1[0]):
            patterns['DARK_CLOUD_COVER'] = 'bearish'

        # Hammer
        if (body(*c2) > 1e-6 and
                (min(c2[0], c2[1]) - l[1]) > 2 * body(*c2) and
                (h[1] - max(c2[0], c2[1])) < body(*c2) * 0.5):
            patterns['HAMMER'] = 'bullish'

        # Shooting Star
        if (body(*c2) > 1e-6 and
                (h[1] - max(c2[0], c2[1])) > 2 * body(*c2) and
                (min(c2[0], c2[1]) - l[1]) < body(*c2) * 0.5):
            patterns['SHOOTING_STAR'] = 'bearish'

    except Exception as e:
        print(f"⚠️ Pattern detection error: {e}")

    return patterns


def get_pattern_signal(patterns):
    """Convert detected patterns to a signal + confidence."""
    bullish = sum(1 for d in patterns.values() if d == 'bullish')
    bearish = sum(1 for d in patterns.values() if d == 'bearish')
    total = bullish + bearish
    if total == 0:
        return 'HOLD', 0.0
    if bullish > bearish:
        return 'BUY', bullish / (bullish + bearish)
    elif bearish > bullish:
        return 'SELL', bearish / (bullish + bearish)
    return 'HOLD', 0.0


def _find_peaks_troughs(price, distance=5, prominence=0.01):
    """Lightweight peak/trough detection (no scipy)."""
    peaks, troughs = [], []
    n = len(price)
    for i in range(distance, n - distance):
        window = price[i - distance:i + distance + 1]
        if price[i] == window.max() and price[i] > window.mean() * (1 + prominence):
            peaks.append(i)
        if price[i] == window.min() and price[i] < window.mean() * (1 - prominence):
            troughs.append(i)
    return np.array(peaks), np.array(troughs)


def detect_chart_patterns(df, lookback=40):
    """Detect double top/bottom and head & shoulders (pure numpy)."""
    if len(df) < lookback:
        return []
    try:
        price = df['close'].values[-lookback:]
        peaks, troughs = _find_peaks_troughs(price, distance=5, prominence=0.01)
        patterns = []

        # Double top / bottom
        if len(peaks) >= 3:
            last = peaks[-3:]
            if abs(price[last[-1]] - price[last[0]]) / price[last[0]] < 0.02:
                patterns.append('double_top')
        if len(troughs) >= 3:
            last = troughs[-3:]
            if abs(price[last[-1]] - price[last[0]]) / price[last[0]] < 0.02:
                patterns.append('double_bottom')

        # Head & shoulders (simplified)
        if len(peaks) >= 5:
            last = peaks[-5:]
            h = price[last]
            if h[-1] < h[-2] and h[-3] < h[-2]:
                if abs(h[-1] - h[-3]) / h[-3] < 0.03:
                    patterns.append('head_shoulders')
        if len(troughs) >= 5:
            last = troughs[-5:]
            l = price[last]
            if l[-1] > l[-2] and l[-3] > l[-2]:
                if abs(l[-1] - l[-3]) / l[-3] < 0.03:
                    patterns.append('inverse_head_shoulders')

        return patterns
    except Exception as e:
        print(f"⚠️ Chart pattern error: {e}")
        return []