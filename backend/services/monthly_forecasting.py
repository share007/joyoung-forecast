"""Monthly forecasting with model selection and exogenous feature relevance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import importlib
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from services.importer import infer_column_mapping

try:
    holidays = importlib.import_module("holidays")
except Exception:  # pragma: no cover
    holidays = None


@dataclass
class MonthlyForecastOutput:
    mapping: Dict[str, str]
    metrics: Dict
    rows: List[Dict]


def _wmape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = np.abs(y_true).sum()
    if denom == 0:
        return float(np.abs(y_true - y_pred).mean())
    return float(np.abs(y_true - y_pred).sum() / denom)


def _parse_start_month(start_month: Optional[str]) -> pd.Period:
    if start_month:
        normalized = str(start_month).strip().replace('/', '-')
        try:
            return pd.Period(normalized, freq="M")
        except Exception as exc:
            raise ValueError("start_month 格式应为 YYYY-MM，例如 2026-01") from exc
    return pd.Timestamp.today().to_period("M")


def _prepare_daily(
    raw_rows: List[Dict],
    column_mapping: Optional[Dict[str, str]] = None,
    lifecycle_map: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
) -> Tuple[pd.DataFrame, Dict[str, str], List[str], List[str]]:
    if not raw_rows:
        raise ValueError("没有可用的导入数据")

    df = pd.DataFrame(raw_rows)
    mapping = infer_column_mapping(df, override=column_mapping)

    required = ["product_code", "date", "sales"]
    missing = [k for k in required if not mapping.get(k) or mapping[k] not in df.columns]
    if missing:
        raise ValueError("无法识别关键列。请传 column_mapping: product_code/date/sales")

    # Build canonical columns first to avoid collisions when raw data already
    # contains names like "sales" while mapped source is another column.
    work = pd.DataFrame(
        {
            "product_code": df[mapping["product_code"]],
            "date": df[mapping["date"]],
            "sales": df[mapping["sales"]],
        }
    )

    mapped_source_cols = {mapping["product_code"], mapping["date"], mapping["sales"]}
    extra_df = df[[c for c in df.columns if c not in mapped_source_cols]].copy()
    extra_df.columns = [
        c if c not in {"product_code", "date", "sales"} else f"extra_{c}"
        for c in extra_df.columns
    ]
    work = pd.concat([work, extra_df], axis=1)

    work["product_code"] = work["product_code"].astype(str).str.strip()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["sales"] = pd.to_numeric(work["sales"], errors="coerce").clip(lower=0)
    work = work.dropna(subset=["product_code", "date", "sales"])

    if lifecycle_map:
        filtered_frames: List[pd.DataFrame] = []
        for code, grp in work.groupby("product_code"):
            lifecycle = lifecycle_map.get(str(code), {})
            start_raw = lifecycle.get("listing_date") if lifecycle else None
            end_raw = lifecycle.get("delisting_date") if lifecycle else None
            start = pd.to_datetime(start_raw, errors="coerce") if start_raw else None
            end = pd.to_datetime(end_raw, errors="coerce") if end_raw else None

            local = grp
            if start is not None and pd.notna(start):
                local = local[local["date"] >= start]
            if end is not None and pd.notna(end):
                local = local[local["date"] <= end]

            if not local.empty:
                filtered_frames.append(local)

        work = pd.concat(filtered_frames, ignore_index=True) if filtered_frames else pd.DataFrame(columns=work.columns)

    if work.empty:
        raise ValueError("导入数据没有可用于预测的有效记录")

    extra_cols = [c for c in work.columns if c not in ["product_code", "date", "sales"]]
    numeric_cols: List[str] = []
    cat_cols: List[str] = []

    for col in extra_cols:
        num = pd.to_numeric(work[col], errors="coerce")
        if num.notna().mean() >= 0.7:
            work[col] = num
            numeric_cols.append(col)
        else:
            work[col] = work[col].astype(str)
            if work[col].nunique(dropna=True) <= 60:
                cat_cols.append(col)

    agg_spec = {"sales": "sum"}
    for col in numeric_cols:
        agg_spec[col] = "mean"
    for col in cat_cols:
        agg_spec[col] = lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[-1]

    daily = work.groupby(["product_code", "date"], as_index=False).agg(agg_spec)
    daily = daily.sort_values(["product_code", "date"])

    mapping_result = {
        "product_code": mapping["product_code"],
        "date": mapping["date"],
        "sales": mapping["sales"],
    }
    return daily, mapping_result, numeric_cols, cat_cols


def _add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["dayofweek"] = data["date"].dt.dayofweek
    data["day"] = data["date"].dt.day
    data["month"] = data["date"].dt.month
    data["quarter"] = data["date"].dt.quarter
    data["is_weekend"] = (data["dayofweek"] >= 5).astype(int)

    if holidays is not None:
        cn = holidays.country_holidays("CN")
        data["is_holiday"] = data["date"].dt.date.apply(lambda d: 1 if d in cn else 0)
    else:
        data["is_holiday"] = data["is_weekend"]
    return data


def _encode_categories(df: pd.DataFrame, cat_cols: List[str]) -> Tuple[pd.DataFrame, List[str], Dict[str, Dict[str, int]]]:
    data = df.copy()
    encoded_cols: List[str] = []
    encoders: Dict[str, Dict[str, int]] = {}

    for col in cat_cols:
        vals = data[col].astype(str)
        mapping = {v: i for i, v in enumerate(vals.dropna().unique().tolist())}
        data[f"enc_{col}"] = vals.map(mapping).fillna(-1).astype(int)
        encoded_cols.append(f"enc_{col}")
        encoders[col] = mapping

    return data, encoded_cols, encoders


def _select_related_features(df: pd.DataFrame, numeric_cols: List[str]) -> List[str]:
    selected: List[str] = []
    for col in numeric_cols:
        c = pd.to_numeric(df[col], errors="coerce")
        if c.notna().mean() < 0.5:
            continue
        corr = c.corr(df["sales"])
        if corr is not None and not np.isnan(corr) and abs(float(corr)) >= 0.03:
            selected.append(col)
    return selected[:6]


def _build_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy().sort_values(["product_code", "date"])

    for lag in [1, 7, 14, 28]:
        data[f"lag_{lag}"] = data.groupby("product_code")["sales"].shift(lag)

    shifted = data.groupby("product_code")["sales"].shift(1)
    data["rolling_mean_7"] = shifted.groupby(data["product_code"]).rolling(7).mean().reset_index(level=0, drop=True)
    data["rolling_mean_28"] = shifted.groupby(data["product_code"]).rolling(28).mean().reset_index(level=0, drop=True)
    data["rolling_std_28"] = shifted.groupby(data["product_code"]).rolling(28).std().reset_index(level=0, drop=True)

    code_map = {c: i for i, c in enumerate(sorted(data["product_code"].unique().tolist()))}
    data["product_idx"] = data["product_code"].map(code_map).astype(int)
    return data


def _intermittent_daily(values: np.ndarray, horizon: int) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(horizon)
    non_zero = values[values > 0]
    if len(non_zero) == 0:
        return np.zeros(horizon)

    avg_demand = float(non_zero.mean())
    intervals = []
    prev = None
    for i, v in enumerate(values):
        if v > 0:
            if prev is not None:
                intervals.append(i - prev)
            prev = i
    avg_interval = float(np.mean(intervals)) if intervals else 1.0
    daily = avg_demand / max(1.0, avg_interval)
    return np.array([daily] * horizon)


def _train_lgbm(df: pd.DataFrame, related_numeric: List[str], encoded_cat: List[str]):
    try:
        import lightgbm as lgb
    except Exception:
        return None, None, None

    feat = _build_lag_features(df)
    feature_cols = [
        "product_idx", "dayofweek", "day", "month", "quarter", "is_weekend", "is_holiday",
        "lag_1", "lag_7", "lag_14", "lag_28", "rolling_mean_7", "rolling_mean_28", "rolling_std_28",
    ] + related_numeric + encoded_cat

    train = feat.dropna(subset=["lag_28", "rolling_mean_28"]).copy()
    if len(train) < 300:
        return None, None, None

    split_date = train["date"].max() - pd.Timedelta(days=56)
    tr = train[train["date"] <= split_date]
    va = train[train["date"] > split_date]
    if len(tr) < 180 or len(va) < 28:
        return None, None, None

    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=700,
        learning_rate=0.03,
        num_leaves=31,
        feature_fraction=0.9,
        bagging_fraction=0.9,
        bagging_freq=3,
        min_child_samples=20,
        verbose=-1,
    )
    model.fit(tr[feature_cols], tr["sales"], eval_set=[(va[feature_cols], va["sales"])])

    va_pred = np.clip(model.predict(va[feature_cols]), 0.0, None)
    metric = {
        "method": "global_lightgbm_daily",
        "wmape": round(_wmape(va["sales"].to_numpy(dtype=float), va_pred), 4),
    }
    return model, feature_cols, metric


def _caps_by_code(history: pd.DataFrame) -> Dict[str, float]:
    caps: Dict[str, float] = {}
    for code, grp in history.groupby("product_code"):
        values = grp["sales"].to_numpy(dtype=float)
        recent = values[-90:] if len(values) >= 90 else values
        mean = float(np.mean(recent)) if len(recent) else 0.0
        std = float(np.std(recent)) if len(recent) else 0.0
        p95 = float(np.percentile(values, 95)) if len(values) else 0.0
        caps[str(code)] = max(1.0, mean + 3.0 * std, p95 * 2.0)
    return caps


def _future_template(history: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, num_cols: List[str], cat_cols: List[str]) -> pd.DataFrame:
    rows: List[Dict] = []
    for code, grp in history.groupby("product_code"):
        grp = grp.sort_values("date")
        last_num = {}
        for col in num_cols:
            vals = pd.to_numeric(grp[col], errors="coerce").dropna()
            last_num[col] = float(vals.iloc[-1]) if not vals.empty else 0.0
        last_cat = {}
        for col in cat_cols:
            vals = grp[col].dropna().astype(str)
            last_cat[col] = vals.iloc[-1] if not vals.empty else ""

        d = start
        while d <= end:
            row = {"product_code": str(code), "date": d, "sales": np.nan}
            row.update(last_num)
            row.update(last_cat)
            rows.append(row)
            d += timedelta(days=1)
    return pd.DataFrame(rows)


def _predict_lgbm_daily(
    history: pd.DataFrame,
    model,
    feature_cols: List[str],
    num_cols: List[str],
    cat_cols: List[str],
    start_month: pd.Period,
    forecast_months: int,
) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["product_code", "date", "sales"])

    start = max(start_month.to_timestamp(), history["date"].max() + pd.Timedelta(days=1))
    end = (start_month + (forecast_months - 1)).to_timestamp(how="end").normalize()
    if start > end:
        return pd.DataFrame(columns=["product_code", "date", "sales"])

    future = _future_template(history, start, end, num_cols, cat_cols)
    full = pd.concat([history.copy(), future], ignore_index=True)
    full = _add_calendar_features(full)
    full, _, _ = _encode_categories(full, cat_cols)

    caps = _caps_by_code(history)

    for dt in sorted(future["date"].unique()):
        full = _build_lag_features(full)
        mask = full["date"] == dt
        x = full.loc[mask, feature_cols]
        pred = np.clip(model.predict(x), 0.0, None)
        codes = full.loc[mask, "product_code"].astype(str).tolist()
        pred = [min(float(v), caps.get(c, float(v))) for c, v in zip(codes, pred)]
        full.loc[mask, "sales"] = pred

    return full[full["date"] >= start][["product_code", "date", "sales"]]


def _predict_baseline_daily(history: pd.DataFrame, start_month: pd.Period, forecast_months: int) -> pd.DataFrame:
    start_month_ts = start_month.to_timestamp()
    end = (start_month + (forecast_months - 1)).to_timestamp(how="end").normalize()

    out: List[Dict] = []
    for code, grp in history.groupby("product_code"):
        grp = grp.sort_values("date")
        values = grp["sales"].to_numpy(dtype=float)
        start = max(start_month_ts, grp["date"].max() + pd.Timedelta(days=1))
        horizon = (end - start).days + 1
        if horizon <= 0:
            continue

        nz_ratio = float((values > 0).mean()) if len(values) else 0.0
        if nz_ratio < 0.15:
            preds = _intermittent_daily(values, horizon)
        else:
            if len(values) >= 7:
                hist = list(values)
                seq = []
                for _ in range(horizon):
                    v = hist[-7]
                    seq.append(v)
                    hist.append(v)
                preds = np.array(seq)
            else:
                base = float(values[-1]) if len(values) else 0.0
                preds = np.array([base] * horizon)

        for i, v in enumerate(preds):
            out.append({"product_code": str(code), "date": start + pd.Timedelta(days=i), "sales": max(0.0, float(v))})

    return pd.DataFrame(out)


def _evaluate_baseline_wmape(daily: pd.DataFrame) -> Optional[float]:
    if daily.empty:
        return None

    split_date = daily["date"].max() - pd.Timedelta(days=56)
    train = daily[daily["date"] <= split_date]
    valid = daily[daily["date"] > split_date]
    if train.empty or valid.empty:
        return None

    y_true_all: List[np.ndarray] = []
    y_pred_all: List[np.ndarray] = []

    for code, valid_grp in valid.groupby("product_code"):
        train_grp = train[train["product_code"] == code].sort_values("date")
        valid_grp = valid_grp.sort_values("date")
        if train_grp.empty or valid_grp.empty:
            continue

        hist = train_grp["sales"].to_numpy(dtype=float)
        horizon = len(valid_grp)
        nz_ratio = float((hist > 0).mean()) if len(hist) else 0.0

        if nz_ratio < 0.15:
            pred = _intermittent_daily(hist, horizon)
        else:
            if len(hist) >= 7:
                seq = []
                rolling = list(hist)
                for _ in range(horizon):
                    v = rolling[-7]
                    seq.append(v)
                    rolling.append(v)
                pred = np.array(seq, dtype=float)
            else:
                base = float(hist[-1]) if len(hist) else 0.0
                pred = np.array([base] * horizon, dtype=float)

        y_true_all.append(valid_grp["sales"].to_numpy(dtype=float))
        y_pred_all.append(np.clip(pred, 0.0, None))

    if not y_true_all:
        return None

    y_true = np.concatenate(y_true_all)
    y_pred = np.concatenate(y_pred_all)
    return _wmape(y_true, y_pred)


def _aggregate_monthly(history: pd.DataFrame, future_daily: pd.DataFrame, start_month: pd.Period, forecast_months: int) -> List[Dict]:
    history = history.copy()
    future_daily = future_daily.copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    future_daily["date"] = pd.to_datetime(future_daily["date"], errors="coerce")
    history = history.dropna(subset=["date"])
    future_daily = future_daily.dropna(subset=["date"])

    month_range = pd.period_range(start_month, start_month + (forecast_months - 1), freq="M")

    hist_window = history[history["date"].dt.to_period("M").isin(month_range)]
    combined = pd.concat([hist_window, future_daily], ignore_index=True)
    combined = combined[combined["date"].dt.to_period("M").isin(month_range)]
    combined["month"] = combined["date"].dt.to_period("M")

    rows: List[Dict] = []
    for code, grp in combined.groupby("product_code"):
        hist_code = history[history["product_code"] == code]
        sigma = float(hist_code["sales"].std()) if len(hist_code) >= 2 else max(1.0, float(hist_code["sales"].mean()) * 0.2 if len(hist_code) else 1.0)
        for month in month_range:
            val = float(grp.loc[grp["month"] == month, "sales"].sum())
            step = month.ordinal - start_month.ordinal + 1
            band = 1.28 * sigma * np.sqrt(max(1, step))
            rows.append(
                {
                    "product_code": str(code),
                    "month": str(month),
                    "sales": round(val, 2),
                    "lower_bound": round(max(0.0, val - band), 2),
                    "upper_bound": round(val + band, 2),
                }
            )

    rows.sort(key=lambda r: (r["product_code"], r["month"]))
    return rows


def forecast_next_months(
    raw_rows: List[Dict],
    forecast_months: int = 3,
    column_mapping: Optional[Dict[str, str]] = None,
    lifecycle_map: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
    start_month: Optional[str] = None,
) -> MonthlyForecastOutput:
    # Business requirement fixed at 3 months by default.
    forecast_months = 3 if forecast_months <= 0 else forecast_months
    start_month_period = _parse_start_month(start_month)

    daily, mapping, numeric_cols, cat_cols = _prepare_daily(
        raw_rows,
        column_mapping=column_mapping,
        lifecycle_map=lifecycle_map,
    )
    daily = _add_calendar_features(daily)
    daily, encoded_cat_cols, _ = _encode_categories(daily, cat_cols)
    related_numeric = _select_related_features(daily, numeric_cols)

    model, feature_cols, lgb_metric = _train_lgbm(daily, related_numeric, encoded_cat_cols)

    if model is not None and feature_cols is not None and lgb_metric is not None:
        pred_lgb = _predict_lgbm_daily(
            history=daily[["product_code", "date", "sales"] + related_numeric + cat_cols],
            model=model,
            feature_cols=feature_cols,
            num_cols=related_numeric,
            cat_cols=cat_cols,
            start_month=start_month_period,
            forecast_months=forecast_months,
        )
    else:
        pred_lgb = pd.DataFrame(columns=["product_code", "date", "sales"])
        lgb_metric = {"method": "global_lightgbm_daily", "wmape": 999.0, "status": "not_available"}

    pred_base = _predict_baseline_daily(
        daily[["product_code", "date", "sales"]],
        start_month=start_month_period,
        forecast_months=forecast_months,
    )

    lgb_eval = lgb_metric
    baseline_wmape = _evaluate_baseline_wmape(daily[["product_code", "date", "sales"]])
    base_eval = {
        "method": "intermittent_baseline",
        "wmape": round(baseline_wmape, 4) if baseline_wmape is not None else 999.0,
    }

    lgb_available = model is not None and not pred_lgb.empty and lgb_eval.get("status") != "not_available"
    lgb_score = lgb_eval.get("wmape", 999)
    base_score = base_eval.get("wmape", 999)
    use_lgb = lgb_available and lgb_score <= base_score
    selected_method = "global_lightgbm_daily" if use_lgb else "intermittent_baseline"
    selected_daily = pred_lgb if use_lgb else pred_base

    rows = _aggregate_monthly(
        daily[["product_code", "date", "sales"]],
        selected_daily,
        start_month=start_month_period,
        forecast_months=forecast_months,
    )

    if lifecycle_map:
        adjusted_rows: List[Dict] = []
        for row in rows:
            code = str(row.get("product_code"))
            month = pd.Period(str(row.get("month")), freq="M")
            lifecycle = lifecycle_map.get(code, {})
            start_raw = lifecycle.get("listing_date") if lifecycle else None
            end_raw = lifecycle.get("delisting_date") if lifecycle else None
            start = pd.to_datetime(start_raw, errors="coerce") if start_raw else None
            end = pd.to_datetime(end_raw, errors="coerce") if end_raw else None

            month_start = month.to_timestamp(how="start")
            month_end = month.to_timestamp(how="end").normalize()

            active = True
            if start is not None and pd.notna(start) and month_end < start:
                active = False
            if end is not None and pd.notna(end) and month_start > end:
                active = False

            if not active:
                adjusted = dict(row)
                adjusted["sales"] = 0.0
                adjusted["lower_bound"] = 0.0
                adjusted["upper_bound"] = 0.0
                adjusted_rows.append(adjusted)
            else:
                adjusted_rows.append(row)
        rows = adjusted_rows

    return MonthlyForecastOutput(
        mapping=mapping,
        metrics={
            "selected_method": selected_method,
            "selected_wmape": lgb_eval.get("wmape") if use_lgb else base_eval.get("wmape"),
            "window": {
                "from_month": str(start_month_period),
                "to_month": str(start_month_period + (forecast_months - 1)),
            },
            "feature_selection": {
                "numeric_candidates": numeric_cols,
                "numeric_selected_by_correlation": related_numeric,
                "categorical_candidates": cat_cols,
                "holiday_feature_enabled": holidays is not None,
            },
            "candidates": [base_eval, lgb_eval],
        },
        rows=rows,
    )
