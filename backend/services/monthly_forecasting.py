"""Monthly forecasting with model selection and exogenous feature relevance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as dt_date, timedelta
import importlib
import re
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


@dataclass
class CnyMonthlyProfile:
    cny_factor: float
    post_cny_factor: float
    cny_month_map: Dict[int, str]
    post_cny_month_map: Dict[int, str]
    history_years: List[int]
    history_cny_ratio_samples: List[float]
    history_post_ratio_samples: List[float]
    actual_year: Optional[int]
    actual_cny_ratio: Optional[float]
    actual_post_ratio: Optional[float]


def _profile_to_summary(profile: CnyMonthlyProfile) -> Dict:
    return {
        "cny_monthly_factor": round(profile.cny_factor, 4),
        "post_cny_monthly_factor": round(profile.post_cny_factor, 4),
        "cny_month_map": profile.cny_month_map,
        "post_cny_month_map": profile.post_cny_month_map,
        "history_cny_ratio_samples": profile.history_cny_ratio_samples,
        "history_post_cny_ratio_samples": profile.history_post_ratio_samples,
        "actual_calibration": {
            "year": profile.actual_year,
            "cny_ratio": profile.actual_cny_ratio,
            "post_cny_ratio": profile.actual_post_ratio,
        },
    }


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


def _detect_time_granularity(raw_date_series: pd.Series) -> str:
    raw = raw_date_series.astype(str).str.strip()
    month_like_ratio = raw.str.match(r"^\d{4}[-/]\d{1,2}$", na=False).mean()

    parsed = pd.to_datetime(raw_date_series, errors="coerce")
    valid = parsed.dropna()
    if valid.empty:
        return "daily"

    unique_dates = int(valid.dt.normalize().nunique())
    unique_months = int(valid.dt.to_period("M").nunique())
    day_one_ratio = float((valid.dt.day == 1).mean())

    if month_like_ratio >= 0.8:
        return "monthly"
    if day_one_ratio >= 0.95 and unique_months > 0 and unique_dates <= unique_months + 1:
        return "monthly"
    return "daily"


def _in_618_window(d: dt_date) -> bool:
    if d.month == 5 and d.day >= 20:
        return True
    if d.month == 6 and d.day <= 20:
        return True
    return False


def _in_double11_window(d: dt_date) -> bool:
    if d.month == 10 and d.day >= 20:
        return True
    if d.month == 11 and d.day <= 11:
        return True
    return False


def _build_spring_festival_dates(years: List[int]) -> set[dt_date]:
    if holidays is None:
        return set()

    cn = holidays.country_holidays("CN", years=years)
    spring_dates: set[dt_date] = set()
    for d, name in cn.items():
        text = str(name)
        if "春节" in text or "Chinese New Year" in text or "Spring Festival" in text or "Lunar New Year" in text:
            spring_dates.add(d)
    return spring_dates


def resolve_cny_months(years: List[int]) -> set[str]:
    years = sorted({int(y) for y in years if y})
    if not years:
        return set()

    spring_dates = _build_spring_festival_dates(years)
    if not spring_dates:
        # Fallback approximation: CNY usually falls in Jan/Feb.
        return {f"{y}-01" for y in years} | {f"{y}-02" for y in years}

    months: set[str] = set()
    for sf in spring_dates:
        start = sf - timedelta(days=10)
        end = sf + timedelta(days=10)
        cursor = start
        while cursor <= end:
            months.add(f"{cursor.year}-{cursor.month:02d}")
            cursor += timedelta(days=1)
    return months


def _build_cny_month_map(years: List[int]) -> Dict[int, str]:
    year_list = sorted({int(y) for y in years if y})
    if not year_list:
        return {}

    spring_dates = _build_spring_festival_dates(year_list)
    if not spring_dates:
        return {y: f"{y}-02" for y in year_list}

    mapping: Dict[int, str] = {}
    for y in year_list:
        counts: Dict[str, int] = {}
        year_spring_dates = [d for d in spring_dates if d.year == y]
        for sf in year_spring_dates:
            start = sf - timedelta(days=10)
            end = sf + timedelta(days=10)
            cursor = start
            while cursor <= end:
                if cursor.year == y:
                    key = f"{cursor.year}-{cursor.month:02d}"
                    counts[key] = counts.get(key, 0) + 1
                cursor += timedelta(days=1)

        if counts:
            mapping[y] = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]
        else:
            mapping[y] = f"{y}-02"

    return mapping


def _next_month_str(month_str: str) -> str:
    p = pd.Period(month_str, freq="M")
    return str(p + 1)


def _prev_month_str(month_str: str) -> str:
    p = pd.Period(month_str, freq="M")
    return str(p - 1)


def _monthly_ratio_samples(
    month_sales: Dict[str, float],
    cny_month_map: Dict[int, str],
) -> Tuple[List[float], List[float]]:
    cny_samples: List[float] = []
    post_samples: List[float] = []

    for year, cny_month in sorted(cny_month_map.items()):
        cny_val = float(month_sales.get(cny_month, 0.0))
        if cny_val <= 0:
            continue

        prev_month = _prev_month_str(cny_month)
        post_month = _next_month_str(cny_month)
        prev_val = float(month_sales.get(prev_month, 0.0))
        post_val = float(month_sales.get(post_month, 0.0))

        baseline_candidates = [v for v in [prev_val, post_val] if v > 0]
        if not baseline_candidates:
            continue

        baseline = float(np.mean(baseline_candidates))
        if baseline <= 0:
            continue

        cny_samples.append(float(np.clip(cny_val / baseline, 0.35, 1.2)))
        post_samples.append(float(np.clip(post_val / baseline if post_val > 0 else 1.0, 0.7, 1.6)))

    return cny_samples, post_samples


def _estimate_cny_monthly_profile(
    history: pd.DataFrame,
    cny_adjustment_strength: float,
    actual_rows: Optional[List[Dict]] = None,
    target_years: Optional[List[int]] = None,
) -> CnyMonthlyProfile:
    work = history[["date", "sales"]].copy()
    work["period"] = work["date"].dt.to_period("M").astype(str)
    month_sales_hist = {
        str(k): float(v)
        for k, v in work.groupby("period")["sales"].sum().to_dict().items()
    }

    history_years = sorted({int(p[:4]) for p in month_sales_hist.keys() if re.match(r"^\d{4}-\d{2}$", p)})
    base_years = history_years + [int(y) for y in (target_years or []) if y]
    cny_month_map = _build_cny_month_map(base_years)
    post_cny_month_map = {y: _next_month_str(m) for y, m in cny_month_map.items()}

    hist_cny_samples, hist_post_samples = _monthly_ratio_samples(month_sales_hist, cny_month_map)
    hist_cny = float(np.median(hist_cny_samples)) if hist_cny_samples else 0.88
    hist_post = float(np.median(hist_post_samples)) if hist_post_samples else 1.08

    actual_year: Optional[int] = None
    actual_cny_ratio: Optional[float] = None
    actual_post_ratio: Optional[float] = None

    if actual_rows:
        actual_month_sales: Dict[str, float] = {}
        for row in actual_rows:
            month = str(row.get("month", "")).strip()
            sales = float(row.get("sales", 0) or 0)
            if not re.match(r"^\d{4}-\d{2}$", month):
                continue
            actual_month_sales[month] = actual_month_sales.get(month, 0.0) + max(0.0, sales)

        actual_years = sorted({int(m[:4]) for m in actual_month_sales.keys()})
        if actual_years:
            actual_year = actual_years[-1]
            merged_map = _build_cny_month_map(base_years + actual_years)
            actual_map = {actual_year: merged_map.get(actual_year, f"{actual_year}-02")}
            cny_samples, post_samples = _monthly_ratio_samples(actual_month_sales, actual_map)
            if cny_samples:
                actual_cny_ratio = float(np.median(cny_samples))
            if post_samples:
                actual_post_ratio = float(np.median(post_samples))

    # Blend long-term history with the latest actual year when available.
    if actual_cny_ratio is not None:
        cny_base = 0.55 * hist_cny + 0.45 * actual_cny_ratio
    else:
        cny_base = hist_cny

    if actual_post_ratio is not None:
        post_base = 0.55 * hist_post + 0.45 * actual_post_ratio
    else:
        post_base = hist_post

    cny_factor = float(np.clip(cny_base * float(cny_adjustment_strength), 0.35, 1.05))
    post_cny_factor = float(np.clip(post_base * (2.0 - float(cny_adjustment_strength)), 0.85, 1.5))

    return CnyMonthlyProfile(
        cny_factor=cny_factor,
        post_cny_factor=post_cny_factor,
        cny_month_map=cny_month_map,
        post_cny_month_map=post_cny_month_map,
        history_years=history_years,
        history_cny_ratio_samples=[round(v, 4) for v in hist_cny_samples],
        history_post_ratio_samples=[round(v, 4) for v in hist_post_samples],
        actual_year=actual_year,
        actual_cny_ratio=round(actual_cny_ratio, 4) if actual_cny_ratio is not None else None,
        actual_post_ratio=round(actual_post_ratio, 4) if actual_post_ratio is not None else None,
    )


def _detect_group_column(data: pd.DataFrame, cat_cols: List[str]) -> Optional[str]:
    candidates = [col for col in cat_cols if col in data.columns]
    if not candidates:
        return None

    ranked_patterns = [
        r"channel|渠道|渠道类型|店铺渠道|platform",
        r"category|品类|类目|品线|系列",
    ]
    for pat in ranked_patterns:
        for col in candidates:
            if re.search(pat, str(col).lower()):
                return col

    # Fallback: choose the most stable low-cardinality categorical feature.
    best_col = None
    best_score = -1.0
    for col in candidates:
        non_na = data[col].dropna().astype(str)
        if non_na.empty:
            continue
        nunique = int(non_na.nunique())
        if nunique <= 1 or nunique > 30:
            continue
        score = float(len(non_na)) / float(nunique)
        if score > best_score:
            best_score = score
            best_col = col
    return best_col


def _build_product_group_map(data: pd.DataFrame, group_col: Optional[str]) -> Dict[str, str]:
    if not group_col or group_col not in data.columns:
        return {}

    subset = data[["product_code", group_col]].copy()
    subset["product_code"] = subset["product_code"].astype(str)
    subset[group_col] = subset[group_col].astype(str).str.strip()
    subset = subset[subset[group_col] != ""]
    if subset.empty:
        return {}

    group_map: Dict[str, str] = {}
    for code, grp in subset.groupby("product_code"):
        mode = grp[group_col].mode()
        if mode.empty:
            continue
        group_map[str(code)] = str(mode.iloc[0])
    return group_map


def _estimate_grouped_cny_profiles(
    history: pd.DataFrame,
    cny_adjustment_strength: float,
    actual_rows: Optional[List[Dict]] = None,
    product_group_map: Optional[Dict[str, str]] = None,
    target_years: Optional[List[int]] = None,
) -> Tuple[CnyMonthlyProfile, Dict[str, CnyMonthlyProfile]]:
    global_profile = _estimate_cny_monthly_profile(
        history=history,
        cny_adjustment_strength=cny_adjustment_strength,
        actual_rows=actual_rows,
        target_years=target_years,
    )

    if not product_group_map:
        return global_profile, {}

    grouped: Dict[str, CnyMonthlyProfile] = {}
    all_actual_rows = actual_rows or []
    group_names = sorted({g for g in product_group_map.values() if g})
    for group_name in group_names:
        code_set = {code for code, g in product_group_map.items() if g == group_name}
        if not code_set:
            continue

        group_history = history[history["product_code"].astype(str).isin(code_set)]
        if group_history.empty:
            continue

        if group_history["date"].dt.to_period("M").nunique() < 6:
            continue

        group_actual_rows = [
            row for row in all_actual_rows
            if str(row.get("product_code", "")) in code_set
        ]
        grouped[group_name] = _estimate_cny_monthly_profile(
            history=group_history,
            cny_adjustment_strength=cny_adjustment_strength,
            actual_rows=group_actual_rows,
            target_years=target_years,
        )

    return global_profile, grouped


def _pick_profile_for_code(
    product_code: str,
    default_profile: CnyMonthlyProfile,
    product_group_map: Optional[Dict[str, str]] = None,
    grouped_profiles: Optional[Dict[str, CnyMonthlyProfile]] = None,
) -> CnyMonthlyProfile:
    if not product_group_map or not grouped_profiles:
        return default_profile

    group_name = product_group_map.get(str(product_code))
    if not group_name:
        return default_profile
    return grouped_profiles.get(group_name, default_profile)


def _apply_monthly_profile_to_rows(
    rows: List[Dict],
    default_profile: CnyMonthlyProfile,
    product_group_map: Optional[Dict[str, str]] = None,
    grouped_profiles: Optional[Dict[str, CnyMonthlyProfile]] = None,
) -> List[Dict]:
    out: List[Dict] = []
    for row in rows:
        code = str(row.get("product_code", ""))
        month_key = str(row.get("month", ""))
        profile = _pick_profile_for_code(
            product_code=code,
            default_profile=default_profile,
            product_group_map=product_group_map,
            grouped_profiles=grouped_profiles,
        )

        factor = 1.0
        if month_key in set(profile.cny_month_map.values()):
            factor *= float(profile.cny_factor)
        elif month_key in set(profile.post_cny_month_map.values()):
            factor *= float(profile.post_cny_factor)

        adjusted = dict(row)
        if factor != 1.0:
            adjusted["sales"] = round(max(0.0, float(adjusted.get("sales", 0.0)) * factor), 2)
            adjusted["lower_bound"] = round(max(0.0, float(adjusted.get("lower_bound", 0.0)) * factor), 2)
            adjusted["upper_bound"] = round(max(0.0, float(adjusted.get("upper_bound", 0.0)) * factor), 2)
        out.append(adjusted)
    return out


def _in_cny_window(d: dt_date, spring_dates: set[dt_date]) -> bool:
    if not spring_dates:
        # Fallback approximation if holiday lib is unavailable.
        return (d.month == 1 and d.day >= 20) or (d.month == 2 and d.day <= 15)

    for sf in spring_dates:
        if abs((d - sf).days) <= 10:
            return True
    return False


def _add_event_flags(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    valid_dates = out["date"].dropna()
    years = sorted({int(y) for y in valid_dates.dt.year.unique().tolist()})
    if years:
        years = [min(years) - 1] + years + [max(years) + 1]
    spring_dates = _build_spring_festival_dates(years)

    out["is_618"] = out["date"].dt.date.apply(lambda d: 1 if _in_618_window(d) else 0)
    out["is_double11"] = out["date"].dt.date.apply(lambda d: 1 if _in_double11_window(d) else 0)
    out["is_cny_window"] = out["date"].dt.date.apply(lambda d: 1 if _in_cny_window(d, spring_dates) else 0)
    return out


def _prepare_daily(
    raw_rows: List[Dict],
    column_mapping: Optional[Dict[str, str]] = None,
    lifecycle_map: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
) -> Tuple[pd.DataFrame, Dict[str, str], List[str], List[str], str]:
    if not raw_rows:
        raise ValueError("没有可用的导入数据")

    df = pd.DataFrame(raw_rows)
    mapping = infer_column_mapping(df, override=column_mapping)
    granularity = _detect_time_granularity(df[mapping["date"]])

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

    if granularity == "monthly":
        work["month"] = work["date"].dt.to_period("M")
        daily = work.groupby(["product_code", "month"], as_index=False).agg(agg_spec)
        daily["date"] = daily["month"].dt.to_timestamp()
        daily = daily.drop(columns=["month"])
    else:
        daily = work.groupby(["product_code", "date"], as_index=False).agg(agg_spec)
    daily = daily.sort_values(["product_code", "date"])

    mapping_result = {
        "product_code": mapping["product_code"],
        "date": mapping["date"],
        "sales": mapping["sales"],
    }
    return daily, mapping_result, numeric_cols, cat_cols, granularity


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
    data = _add_event_flags(data)
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


def _safe_ratio(numerator: float, denominator: float, default: float = 1.0, low: float = 0.6, high: float = 1.8) -> float:
    if denominator <= 0:
        return default
    value = numerator / denominator
    return float(np.clip(value, low, high))


def _estimate_daily_event_factors(history: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    # history columns: product_code, date, sales
    event_df = _add_event_flags(history[["product_code", "date", "sales"]])
    factors: Dict[str, Dict[str, float]] = {}

    for code, grp in event_df.groupby("product_code"):
        grp = grp.sort_values("date")

        base_56 = grp["sales"].tail(56)
        base = float(base_56.mean()) if len(base_56) else float(grp["sales"].mean()) if len(grp) else 0.0
        if base <= 0:
            base = 1.0

        f_618 = _safe_ratio(float(grp.loc[grp["is_618"] == 1, "sales"].mean() or base), base, default=1.05, low=0.8, high=2.2)
        f_11 = _safe_ratio(float(grp.loc[grp["is_double11"] == 1, "sales"].mean() or base), base, default=1.08, low=0.8, high=2.5)
        f_cny = _safe_ratio(float(grp.loc[grp["is_cny_window"] == 1, "sales"].mean() or base), base, default=0.9, low=0.4, high=1.1)

        factors[str(code)] = {
            "promo_618": f_618,
            "promo_double11": f_11,
            "cny": f_cny,
        }

    return factors


def _train_lgbm(df: pd.DataFrame, related_numeric: List[str], encoded_cat: List[str]):
    try:
        import lightgbm as lgb
    except Exception:
        return None, None, None

    feat = _build_lag_features(df)
    feature_cols = [
        "product_idx", "dayofweek", "day", "month", "quarter", "is_weekend", "is_holiday",
        "is_618", "is_double11", "is_cny_window",
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


def _predict_baseline_daily(
    history: pd.DataFrame,
    start_month: pd.Period,
    forecast_months: int,
    cny_adjustment_strength: float,
    cny_profile: Optional[CnyMonthlyProfile] = None,
    product_group_map: Optional[Dict[str, str]] = None,
    grouped_profiles: Optional[Dict[str, CnyMonthlyProfile]] = None,
) -> pd.DataFrame:
    start_month_ts = start_month.to_timestamp()
    end = (start_month + (forecast_months - 1)).to_timestamp(how="end").normalize()
    horizon_years = list(range(int(start_month.year) - 1, int((start_month + (forecast_months - 1)).year) + 2))
    spring_dates = _build_spring_festival_dates(horizon_years)

    out: List[Dict] = []
    event_factors = _estimate_daily_event_factors(history)

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
            day = (start + pd.Timedelta(days=i)).date()
            month_key = f"{day.year}-{day.month:02d}"
            factor = 1.0
            code_factors = event_factors.get(str(code), {})
            active_profile = _pick_profile_for_code(
                product_code=str(code),
                default_profile=cny_profile if cny_profile else CnyMonthlyProfile(1.0, 1.0, {}, {}, [], [], [], None, None, None),
                product_group_map=product_group_map,
                grouped_profiles=grouped_profiles,
            )
            cny_month_set = set(active_profile.cny_month_map.values())
            post_cny_month_set = set(active_profile.post_cny_month_map.values())
            if _in_618_window(day):
                factor *= float(code_factors.get("promo_618", 1.05))
            if _in_double11_window(day):
                factor *= float(code_factors.get("promo_double11", 1.08))
            if _in_cny_window(day, spring_dates):
                factor *= float(code_factors.get("cny", 0.9)) * float(cny_adjustment_strength)
            if month_key in cny_month_set:
                factor *= float(active_profile.cny_factor)
            elif month_key in post_cny_month_set:
                factor *= float(active_profile.post_cny_factor)
            out.append({"product_code": str(code), "date": start + pd.Timedelta(days=i), "sales": max(0.0, float(v) * factor)})

    return pd.DataFrame(out)


def _predict_baseline_monthly(
    history: pd.DataFrame,
    start_month: pd.Period,
    forecast_months: int,
    cny_adjustment_strength: float,
    actual_rows: Optional[List[Dict]] = None,
    default_cny_profile: Optional[CnyMonthlyProfile] = None,
    product_group_map: Optional[Dict[str, str]] = None,
    grouped_profiles: Optional[Dict[str, CnyMonthlyProfile]] = None,
) -> List[Dict]:
    month_range = pd.period_range(start_month, start_month + (forecast_months - 1), freq="M")
    cny_months = resolve_cny_months([int(p.year) for p in month_range])
    rows: List[Dict] = []
    cny_profile = default_cny_profile or _estimate_cny_monthly_profile(
        history=history,
        cny_adjustment_strength=cny_adjustment_strength,
        actual_rows=actual_rows,
    )

    for code, grp in history.groupby("product_code"):
        grp = grp.sort_values("date").copy()
        grp["period"] = grp["date"].dt.to_period("M")
        month_sales = {p: float(v) for p, v in zip(grp["period"], grp["sales"])}

        overall_avg = float(grp["sales"].mean()) if len(grp) else 0.0
        month_index: Dict[int, float] = {}
        if overall_avg > 0:
            month_avg = grp.groupby(grp["date"].dt.month)["sales"].mean()
            for m, avg in month_avg.items():
                month_index[int(m)] = float(np.clip(avg / overall_avg, 0.6, 1.8))

        hist_vals = grp["sales"].to_numpy(dtype=float)
        sigma = float(np.std(hist_vals)) if len(hist_vals) >= 2 else max(1.0, float(np.mean(hist_vals)) * 0.2 if len(hist_vals) else 1.0)

        for idx, month in enumerate(month_range):
            if month in month_sales:
                val = month_sales[month]
            elif (month - 12) in month_sales:
                val = month_sales[month - 12]
            elif len(hist_vals) >= 3:
                val = float(np.mean(hist_vals[-3:]))
            elif len(hist_vals) >= 1:
                val = float(hist_vals[-1])
            else:
                val = 0.0

            # Apply month-level event/seasonality adjustment for monthly-granularity data.
            m = int(month.month)
            seasonal_factor = month_index.get(m, 1.0)
            val *= seasonal_factor

            # Explicit business event windows mapped to affected months.
            if m in (5, 6):
                val *= max(1.02, float((month_index.get(5, 1.0) + month_index.get(6, 1.0)) / 2.0))
            if m in (10, 11):
                val *= max(1.02, float((month_index.get(10, 1.0) + month_index.get(11, 1.0)) / 2.0))
            if str(month) in cny_months:
                cny_base = float((month_index.get(1, 1.0) + month_index.get(2, 1.0)) / 2.0)
                val *= min(float(cny_adjustment_strength), cny_base)

            month_key = str(month)
            active_profile = _pick_profile_for_code(
                product_code=str(code),
                default_profile=cny_profile,
                product_group_map=product_group_map,
                grouped_profiles=grouped_profiles,
            )
            cny_month_set = set(active_profile.cny_month_map.values())
            post_cny_month_set = set(active_profile.post_cny_month_map.values())
            if month_key in cny_month_set:
                val *= float(active_profile.cny_factor)
            elif month_key in post_cny_month_set:
                val *= float(active_profile.post_cny_factor)

            month_sales[month] = max(0.0, float(val))
            step = idx + 1
            band = 1.28 * sigma * np.sqrt(max(1, step))
            rows.append(
                {
                    "product_code": str(code),
                    "month": str(month),
                    "sales": round(month_sales[month], 2),
                    "lower_bound": round(max(0.0, month_sales[month] - band), 2),
                    "upper_bound": round(month_sales[month] + band, 2),
                }
            )

    rows.sort(key=lambda r: (r["product_code"], r["month"]))
    return rows


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
    cny_adjustment_strength: float = 0.98,
    actual_rows: Optional[List[Dict]] = None,
) -> MonthlyForecastOutput:
    # Business requirement fixed at 3 months by default.
    forecast_months = 3 if forecast_months <= 0 else forecast_months
    start_month_period = _parse_start_month(start_month)

    daily, mapping, numeric_cols, cat_cols, granularity = _prepare_daily(
        raw_rows,
        column_mapping=column_mapping,
        lifecycle_map=lifecycle_map,
    )

    history_core = daily[["product_code", "date", "sales"]]
    forecast_month_range = pd.period_range(start_month_period, start_month_period + (forecast_months - 1), freq="M")
    target_years = [int(p.year) for p in forecast_month_range]
    group_col = _detect_group_column(daily, cat_cols)
    product_group_map = _build_product_group_map(daily, group_col)
    cny_profile, grouped_profiles = _estimate_grouped_cny_profiles(
        history=history_core,
        cny_adjustment_strength=cny_adjustment_strength,
        actual_rows=actual_rows,
        product_group_map=product_group_map,
        target_years=target_years,
    )
    grouped_profile_summary = {name: _profile_to_summary(profile) for name, profile in grouped_profiles.items()}

    if granularity == "monthly":
        rows = _predict_baseline_monthly(
            history=history_core,
            start_month=start_month_period,
            forecast_months=forecast_months,
            cny_adjustment_strength=cny_adjustment_strength,
            actual_rows=actual_rows,
            default_cny_profile=cny_profile,
            product_group_map=product_group_map,
            grouped_profiles=grouped_profiles,
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
                "selected_method": "monthly_baseline",
                "selected_wmape": None,
                "window": {
                    "from_month": str(start_month_period),
                    "to_month": str(start_month_period + (forecast_months - 1)),
                },
                "input_granularity": granularity,
                "feature_selection": {
                    "numeric_candidates": numeric_cols,
                    "numeric_selected_by_correlation": [],
                    "categorical_candidates": cat_cols,
                    "holiday_feature_enabled": holidays is not None,
                },
                "event_adjustments": {
                    "promo_618_window": "05-20 to 06-20",
                    "promo_double11_window": "10-20 to 11-11",
                    "cny_window": "dynamic lunar new year period",
                    "cny_adjustment_strength": cny_adjustment_strength,
                    "group_dimension": group_col,
                    "group_count": len(grouped_profiles),
                    "group_profiles": grouped_profile_summary,
                    **_profile_to_summary(cny_profile),
                },
                "candidates": [{"method": "monthly_baseline", "wmape": None}],
            },
            rows=rows,
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
        history_core,
        start_month=start_month_period,
        forecast_months=forecast_months,
        cny_adjustment_strength=cny_adjustment_strength,
        cny_profile=cny_profile,
        product_group_map=product_group_map,
        grouped_profiles=grouped_profiles,
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
        history_core,
        selected_daily,
        start_month=start_month_period,
        forecast_months=forecast_months,
    )

    if use_lgb:
        rows = _apply_monthly_profile_to_rows(
            rows=rows,
            default_profile=cny_profile,
            product_group_map=product_group_map,
            grouped_profiles=grouped_profiles,
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
            "event_adjustments": {
                "promo_618_window": "05-20 to 06-20",
                "promo_double11_window": "10-20 to 11-11",
                "cny_window": "dynamic lunar new year period",
                "cny_adjustment_strength": cny_adjustment_strength,
                "group_dimension": group_col,
                "group_count": len(grouped_profiles),
                "group_profiles": grouped_profile_summary,
                **_profile_to_summary(cny_profile),
            },
            "input_granularity": granularity,
            "candidates": [base_eval, lgb_eval],
        },
        rows=rows,
    )
