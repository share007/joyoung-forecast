"""Data import helpers for flexible CSV/Excel ingestion and column inference."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO, StringIO
import math
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

@dataclass
class ParsedUpload:
    data: List[Dict]
    detected_columns: Dict[str, Optional[str]]
    summary: Dict
    sheet_name: Optional[str]


PRODUCT_PATTERNS = [r"sku", r"product.*code", r"code", r"产品编码", r"物料", r"货号", r"编码"]
DATE_PATTERNS = [r"date", r"日期", r"day", r"time", r"month", r"月份"]
SALES_PATTERNS = [
    r"sales",
    r"sale",
    r"qty",
    r"quantity",
    r"volume",
    r"销量",
    r"销售量",
    r"销售数量",
    r"数量",
]


def normalize_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data = data.dropna(how="all")
    raw_cols = [str(col).strip() for col in data.columns]
    # Keep column names unique to avoid ambiguous DataFrame indexing when headers repeat.
    seen: Dict[str, int] = {}
    unique_cols: List[str] = []
    for col in raw_cols:
        base = col or "unnamed"
        count = seen.get(base, 0) + 1
        seen[base] = count
        unique_cols.append(base if count == 1 else f"{base}_{count}")
    data.columns = unique_cols
    return data


def _pick_by_patterns(columns: List[str], patterns: List[str]) -> Optional[str]:
    for col in columns:
        lowered = col.strip().lower()
        for pat in patterns:
            if re.search(pat, lowered):
                return col
    return None


def _infer_by_type(df: pd.DataFrame, kind: str) -> Optional[str]:
    columns = df.columns.tolist()
    if kind == "date":
        best_col = None
        best_score = 0.0
        for col in columns:
            parsed = pd.to_datetime(df[col], errors="coerce")
            score = parsed.notna().mean()
            if score > best_score:
                best_score = score
                best_col = col
        return best_col if best_score >= 0.5 else None

    if kind == "sales":
        best_col = None
        best_score = -1.0
        for col in columns:
            numeric = pd.to_numeric(df[col], errors="coerce")
            valid_ratio = numeric.notna().mean()
            if valid_ratio < 0.5:
                continue
            variance = float(numeric.fillna(0).var())
            score = valid_ratio + min(1.0, variance / 1_000_000)
            if score > best_score:
                best_score = score
                best_col = col
        return best_col

    if kind == "product_code":
        object_cols = [col for col in columns if df[col].dtype == "object"]
        if not object_cols:
            return columns[0] if columns else None
        object_cols.sort(key=lambda c: df[c].nunique(dropna=True), reverse=True)
        return object_cols[0]

    return None


def infer_column_mapping(df: pd.DataFrame, override: Optional[Dict[str, str]] = None) -> Dict[str, Optional[str]]:
    """Infer product_code/date/sales columns from flexible schemas."""
    override = override or {}
    columns = df.columns.tolist()

    product_code_col = override.get("product_code")
    date_col = override.get("date")
    sales_col = override.get("sales")

    if product_code_col not in columns:
        product_code_col = _pick_by_patterns(columns, PRODUCT_PATTERNS) or _infer_by_type(df, "product_code")

    if date_col not in columns:
        date_col = _pick_by_patterns(columns, DATE_PATTERNS) or _infer_by_type(df, "date")

    if sales_col not in columns:
        sales_col = _pick_by_patterns(columns, SALES_PATTERNS) or _infer_by_type(df, "sales")

    return {
        "product_code": product_code_col,
        "date": date_col,
        "sales": sales_col,
    }


def rows_to_json_ready(df: pd.DataFrame) -> List[Dict]:
    # Convert all values to JSON-safe primitives to avoid intermittent
    # Timestamp/numpy serialization errors during import persistence.
    def scalar_to_json_safe(value):
        if value is None:
            return None

        if isinstance(value, np.generic):
            value = value.item()

        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, pd.Timedelta):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, float):
            return value if math.isfinite(value) else None

        if pd.isna(value):
            return None

        return value

    safe_records: List[Dict] = []
    columns = [str(col) for col in df.columns]
    for row in df.itertuples(index=False, name=None):
        record: Dict[str, object] = {}
        for idx, value in enumerate(row):
            record[columns[idx]] = scalar_to_json_safe(value)
        safe_records.append(record)
    return safe_records


def parse_upload_file(filename: str, content: bytes, preferred_sheet: Optional[str] = None) -> ParsedUpload:
    """Parse CSV/Excel file without requiring fixed field names."""
    if filename.lower().endswith(".csv"):
        df = normalize_raw_df(pd.read_csv(StringIO(content.decode("utf-8"))))
        detected = infer_column_mapping(df)
        return ParsedUpload(
            data=rows_to_json_ready(df),
            detected_columns=detected,
            summary=_build_summary(df, detected),
            sheet_name=None,
        )

    if filename.lower().endswith((".xls", ".xlsx")):
        workbook = pd.read_excel(BytesIO(content), sheet_name=None)
        if not workbook:
            raise ValueError("Excel 文件无可用工作表")

        sheets = list(workbook.keys())
        candidates = sheets
        if preferred_sheet and preferred_sheet in workbook:
            candidates = [preferred_sheet] + [s for s in sheets if s != preferred_sheet]

        last_error = None
        for sheet_name in candidates:
            try:
                df = normalize_raw_df(workbook[sheet_name])
                if df.empty:
                    continue
                detected = infer_column_mapping(df)
                return ParsedUpload(
                    data=rows_to_json_ready(df),
                    detected_columns=detected,
                    summary=_build_summary(df, detected),
                    sheet_name=sheet_name,
                )
            except Exception as exc:
                last_error = exc

        raise ValueError(f"Excel 解析失败，未找到可用工作表。最后错误: {last_error}")

    raise ValueError("仅支持 CSV、XLS、XLSX 文件")


def _build_summary(df: pd.DataFrame, detected: Dict[str, Optional[str]]) -> Dict:
    date_col = detected.get("date")
    sales_col = detected.get("sales")

    date_range = ""
    if date_col and date_col in df.columns:
        parsed_date = pd.to_datetime(df[date_col], errors="coerce")
        valid_date = parsed_date.dropna()
        if not valid_date.empty:
            date_range = f"{valid_date.min().strftime('%Y-%m-%d')} ~ {valid_date.max().strftime('%Y-%m-%d')}"

    total_sales = 0.0
    avg_sales = 0.0
    if sales_col and sales_col in df.columns:
        parsed_sales = pd.to_numeric(df[sales_col], errors="coerce").fillna(0)
        total_sales = float(parsed_sales.sum())
        avg_sales = float(parsed_sales.mean()) if len(parsed_sales) else 0.0

    return {
        "total_records": int(len(df)),
        "date_range": date_range,
        "total_sales": round(total_sales, 2),
        "avg_daily_sales": round(avg_sales, 2),
        "columns": df.columns.tolist(),
        "detected_columns": detected,
    }
