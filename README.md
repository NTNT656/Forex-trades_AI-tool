# Pattern Trader – Lightweight Forex Signal System

A lightweight forex trading signal system built on **LightGBM** + classic technical strategies.
Runs on a small VPS (~256 MB RAM), starts in <2 seconds, with zero heavy ML dependencies.

## What Changed vs. Original

**Removed** (heavy, slow):
- ❌ SVM + HMM (`pattern_model.py`, `hmmlearn`, `scikit-learn`)
- ❌ ARIMA volatility (`arima_model.py`, `statsmodels`)
- ❌ SR Trend model (`sr_trend_model.py`, `DBSCAN`)
- ❌ scipy-dependent chart patterns (`chart_patterns.py`)
- ❌ pandas_ta-based candlestick patterns (`candlestick_patterns.py`)

**Kept/Added** (light, fast):
- ✅ **LightGBM** per pair (~200 KB each)
- ✅ **Pure numpy** pattern detection (`patterns_light.py`)
- ✅ **EWMA volatility** instead of ARIMA
- ✅ Rule-based strategies: Bollinger, Williams %R, CCI, Stochastic, MACD, RSI, Pairs, Ensemble

## Dependency Size

| Before | After |
|--------|-------|
| ~800 MB (sklearn + statsmodels + scipy + lightgbm + xgboost) | **~150 MB** (flask + lightgbm + pandas + numpy) |

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app, signal generation, auto-trade |
| `lightgbm_model.py` | LightGBM training + Supabase persistence + optional ONNX |
| `patterns_light.py` | Pure numpy pattern detection |
| `backtest.py` | Walk-forward backtest |
| `forward_test.py` | Live/recent forward test |
| `pytrader_api.py` | MT4/MT5 socket bridge (unchanged) |
| `dashboard.html`, `index.html`, `script.js`, `style.css` | Web UI |

## Setup

```bash
pip install -r requirements.txt
export SUPABASE_URL="https://xxx.supabase.co"
export SUPABASE_SERVICE_KEY="..."
python app.py