# lightgbm_model.py – Lightweight LightGBM with Supabase persistence
# UPDATED: Optional ONNX export/inference, no sklearn dependency for inference.

import numpy as np
import pandas as pd
import lightgbm as lgb
import joblib
import io
import base64
import pickle
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Optional ONNX support
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# Optional skl2onnx for conversion
try:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    SKL2ONNX_AVAILABLE = True
except ImportError:
    SKL2ONNX_AVAILABLE = False


class LightGBMModel:
    def __init__(self,
                 tp_mult=0.02,
                 sl_mult=0.012,
                 time_horizon=30,
                 feature_columns=None,
                 lgb_params=None,
                 supabase_client=None,
                 table_name='lightgbm_models'):
        self.tp_mult = tp_mult
        self.sl_mult = sl_mult
        self.time_horizon = time_horizon
        self.feature_columns = feature_columns or []
        self.model = None
        self.onnx_session = None
        self.scaler_mean = None
        self.scaler_std = None
        self.supabase = supabase_client
        self.table_name = table_name

        if lgb_params is None:
            self.lgb_params = {
                'boosting_type': 'gbdt',
                'num_leaves': 15,
                'max_depth': 5,
                'learning_rate': 0.01,
                'n_estimators': 1000,
                'reg_alpha': 2.0,
                'reg_lambda': 15.0,
                'subsample': 0.8,
                'feature_fraction': 0.8,
                'min_child_samples': 30,
                'objective': 'binary',
                'metric': 'binary_logloss',
                'verbose': -1,
                'random_state': 42
            }
        else:
            self.lgb_params = lgb_params

        if self.supabase:
            self.load_from_supabase()

    # ---------- Simple numpy-based scaler (no sklearn) ----------
    def _fit_scaler(self, X):
        self.scaler_mean = X.mean(axis=0)
        self.scaler_std = X.std(axis=0)
        self.scaler_std[self.scaler_std == 0] = 1.0

    def _transform(self, X):
        if self.scaler_mean is None:
            return X
        return (X - self.scaler_mean) / self.scaler_std

    # ---------- Triple-barrier labels ----------
    def _triple_barrier_labels(self, df):
        prices = df['close'].values
        labels = np.zeros(len(prices), dtype=int)
        for i in range(len(prices) - self.time_horizon):
            entry = prices[i]
            tp = entry * (1 + self.tp_mult)
            sl = entry * (1 - self.sl_mult)
            for j in range(1, self.time_horizon + 1):
                price = prices[i + j]
                if price >= tp:
                    labels[i] = 1
                    break
                elif price <= sl:
                    labels[i] = -1
                    break
        return labels

    def prepare_features(self, df):
        for col in self.feature_columns:
            if col not in df.columns:
                df[col] = 0.0
        X = df[self.feature_columns].values
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        y = self._triple_barrier_labels(df)
        mask = y != 0
        X_bin = X[mask]
        y_bin = (y[mask] > 0).astype(int)
        return X_bin, y_bin, X, y

    def train(self, df):
        X_bin, y_bin, _, _ = self.prepare_features(df)
        if len(X_bin) < 50:
            print("Not enough data for LightGBM training.")
            return False
        self._fit_scaler(X_bin)
        X_scaled = self._transform(X_bin)
        split = int(0.8 * len(X_scaled))
        X_train, X_val = X_scaled[:split], X_scaled[split:]
        y_train, y_val = y_bin[:split], y_bin[split:]
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        callbacks = [lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)]
        self.model = lgb.train(
            self.lgb_params,
            train_data,
            valid_sets=[val_data],
            callbacks=callbacks
        )
        if self.supabase:
            self.save_to_supabase()
        return True

    def predict(self, df, min_confidence=0.55):
        if self.model is None and self.onnx_session is None:
            return 'HOLD', 0.0
        X_bin, _, _, _ = self.prepare_features(df)
        if len(X_bin) == 0:
            return 'HOLD', 0.0
        last = X_bin[-1:].reshape(1, -1)
        last_scaled = self._transform(last)
        if self.onnx_session is not None:
            input_name = self.onnx_session.get_inputs()[0].name
            prob = float(self.onnx_session.run(None, {input_name: last_scaled.astype(np.float32)})[0][0])
        else:
            prob = float(self.model.predict(last_scaled)[0])
        if prob > min_confidence:
            return 'BUY', prob
        elif 1 - prob > min_confidence:
            return 'SELL', 1 - prob
        else:
            return 'HOLD', 0.0

    # ---------- Optional ONNX export ----------
    def export_to_onnx(self, path='lgb_model.onnx'):
        if self.model is None:
            print("No model to export.")
            return False
        if not SKL2ONNX_AVAILABLE:
            print("skl2onnx not installed. Install with: pip install skl2onnx onnxruntime")
            return False
        initial_type = [('input', FloatTensorType([None, len(self.feature_columns)]))]
        try:
            onnx_model = convert_sklearn(self.model, initial_types=initial_type)
            with open(path, 'wb') as f:
                f.write(onnx_model.SerializeToString())
            print(f"✅ ONNX model saved to {path}")
            return True
        except Exception as e:
            print(f"⚠️ ONNX export failed: {e}")
            return False

    def load_onnx(self, path='lgb_model.onnx'):
        if not ONNX_AVAILABLE:
            print("onnxruntime not installed.")
            return False
        try:
            self.onnx_session = ort.InferenceSession(path)
            print(f"✅ ONNX model loaded from {path}")
            return True
        except Exception as e:
            print(f"⚠️ Failed to load ONNX: {e}")
            return False

    # ---------- Supabase persistence ----------
    def save_to_supabase(self):
        if self.model is None or self.supabase is None:
            return False
        try:
            model_bytes = io.BytesIO()
            joblib.dump(self.model, model_bytes)
            scaler_bytes = io.BytesIO()
            joblib.dump({'mean': self.scaler_mean, 'std': self.scaler_std}, scaler_bytes)

            resp = self.supabase.table(self.table_name) \
                .select('id').order('created_at', desc=True).limit(1).execute()

            save_data = {
                'model_blob': base64.b64encode(pickle.dumps({
                    'model': model_bytes.getvalue(),
                    'scaler': scaler_bytes.getvalue()
                })).decode('utf-8'),
                'created_at': datetime.now().isoformat(),
                'version': 'lightgbm_2.0',
                'tp_mult': self.tp_mult,
                'sl_mult': self.sl_mult,
                'time_horizon': self.time_horizon
            }

            if resp.data:
                row_id = resp.data[0]['id']
                self.supabase.table(self.table_name).eq('id', row_id).update(save_data)
                print(f"✅ LightGBM updated in {self.table_name}.")
            else:
                self.supabase.table(self.table_name).insert(save_data)
                print(f"✅ LightGBM saved to {self.table_name}.")
            return True
        except Exception as e:
            print(f"❌ Save failed: {e}")
            return False

    def load_from_supabase(self):
        if self.supabase is None:
            return False
        try:
            resp = self.supabase.table(self.table_name) \
                .select('*').order('created_at', desc=True).limit(1).execute()
            if not resp.data:
                print(f"ℹ️ No LightGBM model in {self.table_name}.")
                return False
            blob_b64 = resp.data[0]['model_blob']
            data = pickle.loads(base64.b64decode(blob_b64))
            if 'model' in data and data['model'] is not None:
                self.model = joblib.load(io.BytesIO(data['model']))
                scaler = joblib.load(io.BytesIO(data['scaler']))
                self.scaler_mean = scaler['mean']
                self.scaler_std = scaler['std']
                print(f"✅ LightGBM loaded from {self.table_name}.")
                return True
            return False
        except Exception as e:
            print(f"⚠️ Load failed: {e}")
            return False