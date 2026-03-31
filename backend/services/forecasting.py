"""Forecasting services with champion-challenger model selection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class ForecastOutput:
    predictions: List[Dict]
    metrics: Dict


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create time-series features for machine learning models."""
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values("date")

    data["dayofweek"] = data["date"].dt.dayofweek
    data["dayofmonth"] = data["date"].dt.day
    data["month"] = data["date"].dt.month
    data["quarter"] = data["date"].dt.quarter
    data["year"] = data["date"].dt.year
    data["weekofyear"] = data["date"].dt.isocalendar().week.astype(int)
    data["is_weekend"] = (data["dayofweek"] >= 5).astype(int)

    for lag in [1, 7, 14, 30]:
        data[f"lag_{lag}"] = data["sales"].shift(lag)

    for window in [7, 14, 30]:
        shifted = data["sales"].shift(1)
        data[f"rolling_mean_{window}"] = shifted.rolling(window).mean()
        data[f"rolling_std_{window}"] = shifted.rolling(window).std()

    return data


def _wmape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.abs(y_true).sum()
    if denom == 0:
        return float(np.abs(y_true - y_pred).mean())
    return float(np.abs(y_true - y_pred).sum() / denom)


def _smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.abs(y_true) + np.abs(y_pred)
    denom = np.where(denom == 0, 1, denom)
    return float(np.mean(2 * np.abs(y_true - y_pred) / denom))


def _seasonal_naive_forecast(train_values: np.ndarray, horizon: int, season: int = 7) -> np.ndarray:
    if len(train_values) < season:
        base = np.mean(train_values) if len(train_values) else 0
        return np.full(horizon, base)

    forecast = []
    history = train_values.tolist()
    for _ in range(horizon):
        pred = history[-season]
        forecast.append(pred)
        history.append(pred)
    return np.array(forecast)


def _simple_weighted_forecast(train_values: np.ndarray, horizon: int) -> np.ndarray:
    if len(train_values) == 0:
        return np.zeros(horizon)

    avg_sales = float(np.mean(train_values))
    last_week = float(np.mean(train_values[-7:])) if len(train_values) >= 7 else avg_sales
    last_month = float(np.mean(train_values[-30:])) if len(train_values) >= 30 else avg_sales
    base_sales = last_week * 0.5 + last_month * 0.3 + avg_sales * 0.2

    values = []
    for i in range(horizon):
        dow = i % 7
        weekend_factor = 0.8 if dow >= 5 else 1.0
        values.append(base_sales * weekend_factor)
    return np.array(values)


def _train_lightgbm(df_with_features: pd.DataFrame):
    try:
        import lightgbm as lgb
    except Exception:
        return None, None, None

    data = df_with_features.dropna().copy()
    if len(data) < 60:
        return None, None, None

    feature_cols = [col for col in data.columns if col not in ["date", "sales"]]
    x = data[feature_cols]
    y = data["sales"]

    split = int(len(x) * 0.8)
    if split <= 30 or split >= len(x):
        return None, None, None

    x_train, x_val = x.iloc[:split], x.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    model = lgb.LGBMRegressor(
        objective="regression",
        metric="l2",
        boosting_type="gbdt",
        num_leaves=31,
        learning_rate=0.05,
        feature_fraction=0.9,
        bagging_fraction=0.9,
        bagging_freq=3,
        n_estimators=400,
        verbose=-1,
    )
    model.fit(x_train, y_train, eval_set=[(x_val, y_val)])

    val_pred = model.predict(x_val)
    metrics = {
        "wmape": round(_wmape(y_val.to_numpy(), val_pred), 4),
        "smape": round(_smape(y_val.to_numpy(), val_pred), 4),
        "rmse": round(float(np.sqrt(np.mean((y_val.to_numpy() - val_pred) ** 2))), 4),
    }
    return model, feature_cols, metrics


def _predict_with_lgbm(model, feature_cols: List[str], df_with_features: pd.DataFrame, horizon: int) -> np.ndarray:
    work = df_with_features.dropna().copy()
    if work.empty:
        return np.zeros(horizon)

    recent = work.tail(30).copy()
    last_date = pd.to_datetime(work["date"].max())

    results = []
    for i in range(horizon):
        next_date = last_date + timedelta(days=i + 1)
        feat = {
            "dayofweek": next_date.dayofweek,
            "dayofmonth": next_date.day,
            "month": next_date.month,
            "quarter": next_date.quarter,
            "year": next_date.year,
            "weekofyear": next_date.isocalendar().week,
            "is_weekend": 1 if next_date.dayofweek >= 5 else 0,
        }

        for lag in [1, 7, 14, 30]:
            feat[f"lag_{lag}"] = float(recent["sales"].iloc[-lag]) if len(recent) >= lag else float(recent["sales"].mean())

        for window in [7, 14, 30]:
            if len(recent) >= window:
                tail = recent["sales"].iloc[-window:]
                feat[f"rolling_mean_{window}"] = float(tail.mean())
                feat[f"rolling_std_{window}"] = float(tail.std() if tail.std() == tail.std() else 0)
            else:
                feat[f"rolling_mean_{window}"] = float(recent["sales"].mean())
                feat[f"rolling_std_{window}"] = float(recent["sales"].std() if recent["sales"].std() == recent["sales"].std() else 0)

        x_pred = pd.DataFrame([feat])[feature_cols]
        pred = max(0.0, float(model.predict(x_pred)[0]))
        results.append(pred)

        recent = pd.concat([recent, pd.DataFrame([{"date": next_date, "sales": pred}])], ignore_index=True).tail(30)

    return np.array(results)


def _compose_predictions(start_date: pd.Timestamp, values: np.ndarray, residual_std: float) -> List[Dict]:
    rows = []
    sigma = max(1.0, residual_std)
    for i, pred in enumerate(values):
        date = (start_date + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        lower = max(0.0, pred - 1.28 * sigma)
        upper = pred + 1.28 * sigma
        rows.append(
            {
                "date": date,
                "predicted_sales": round(float(pred), 2),
                "lower_bound": round(float(lower), 2),
                "upper_bound": round(float(upper), 2),
            }
        )
    return rows


def forecast_with_champion_challenger(historical_data: List[Dict], forecast_days: int) -> ForecastOutput:
    """Run a champion-challenger workflow and select the best model by validation WMAPE."""
    if not historical_data:
        return ForecastOutput(predictions=[], metrics={"method": "none", "reason": "empty_data"})

    df = pd.DataFrame(historical_data)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["sales"] = pd.to_numeric(df["sales"], errors="coerce").fillna(0)
    df = df.dropna(subset=["date"]).sort_values("date")

    if len(df) < 14:
        pred_values = _simple_weighted_forecast(df["sales"].to_numpy(), forecast_days)
        predictions = _compose_predictions(df["date"].max(), pred_values, residual_std=float(np.std(df["sales"].to_numpy())))
        return ForecastOutput(
            predictions=predictions,
            metrics={"method": "weighted_baseline", "wmape": 0.0, "smape": 0.0, "rmse": 0.0},
        )

    horizon_val = min(14, max(7, len(df) // 5))
    train = df.iloc[:-horizon_val]
    valid = df.iloc[-horizon_val:]

    if train.empty or valid.empty:
        pred_values = _simple_weighted_forecast(df["sales"].to_numpy(), forecast_days)
        predictions = _compose_predictions(df["date"].max(), pred_values, residual_std=float(np.std(df["sales"].to_numpy())))
        return ForecastOutput(predictions=predictions, metrics={"method": "weighted_baseline"})

    contenders: List[Tuple[str, Dict, np.ndarray]] = []

    # Challenger 1: seasonal naive
    sn_val_pred = _seasonal_naive_forecast(train["sales"].to_numpy(), len(valid), season=7)
    sn_metrics = {
        "wmape": round(_wmape(valid["sales"].to_numpy(), sn_val_pred), 4),
        "smape": round(_smape(valid["sales"].to_numpy(), sn_val_pred), 4),
        "rmse": round(float(np.sqrt(np.mean((valid["sales"].to_numpy() - sn_val_pred) ** 2))), 4),
    }
    sn_forecast = _seasonal_naive_forecast(df["sales"].to_numpy(), forecast_days, season=7)
    contenders.append(("seasonal_naive", sn_metrics, sn_forecast))

    # Challenger 2: weighted baseline
    wb_val_pred = _simple_weighted_forecast(train["sales"].to_numpy(), len(valid))
    wb_metrics = {
        "wmape": round(_wmape(valid["sales"].to_numpy(), wb_val_pred), 4),
        "smape": round(_smape(valid["sales"].to_numpy(), wb_val_pred), 4),
        "rmse": round(float(np.sqrt(np.mean((valid["sales"].to_numpy() - wb_val_pred) ** 2))), 4),
    }
    wb_forecast = _simple_weighted_forecast(df["sales"].to_numpy(), forecast_days)
    contenders.append(("weighted_baseline", wb_metrics, wb_forecast))

    # Champion: lightgbm (if enough data and package available)
    feat_df = create_features(df)
    model, feature_cols, lgb_metrics = _train_lightgbm(feat_df)
    if model is not None and feature_cols is not None and lgb_metrics is not None:
        try:
            lgb_forecast = _predict_with_lgbm(model, feature_cols, feat_df, forecast_days)
            contenders.append(("lightgbm", lgb_metrics, lgb_forecast))
        except Exception:
            pass

    contenders.sort(key=lambda item: item[1].get("wmape", 9999))
    winner_name, winner_metrics, winner_forecast = contenders[0]

    residual_std = float(np.std(valid["sales"].to_numpy() - _seasonal_naive_forecast(train["sales"].to_numpy(), len(valid))))
    predictions = _compose_predictions(df["date"].max(), winner_forecast, residual_std)

    metrics = {
        "method": winner_name,
        "wmape": winner_metrics.get("wmape", 0),
        "smape": winner_metrics.get("smape", 0),
        "rmse": winner_metrics.get("rmse", 0),
        "candidates": [{"method": name, **m} for name, m, _ in contenders],
    }

    return ForecastOutput(predictions=predictions, metrics=metrics)
