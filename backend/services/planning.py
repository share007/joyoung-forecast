"""Production and replenishment planning service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np


@dataclass
class PlanningInput:
    product_name: str
    current_stock: float
    in_transit: float
    lead_time_days: int
    service_level: float
    moq: float
    pack_size: float


def _z_score(service_level: float) -> float:
    # Common service levels in supply planning.
    table = {
        0.90: 1.28,
        0.95: 1.65,
        0.97: 1.88,
        0.98: 2.05,
        0.99: 2.33,
    }
    rounded = round(service_level, 2)
    return table.get(rounded, 1.65)


def build_recommendation(
    planning_input: PlanningInput,
    predictions: List[Dict],
    historical_sales: List[Dict],
) -> Dict:
    if not predictions:
        return {
            "product_name": planning_input.product_name,
            "production_recommendation": 0,
            "replenishment_recommendation": 0,
            "safety_stock": 0,
            "stock_cover_days": 0,
            "risk_level": "unknown",
        }

    demand_values = np.array([float(p["predicted_sales"]) for p in predictions], dtype=float)
    forecast_demand = float(demand_values.sum())

    hist = np.array([float(x.get("sales", 0)) for x in historical_sales], dtype=float)
    if len(hist) == 0:
        hist = demand_values

    daily_std = float(np.std(hist[-90:])) if len(hist) >= 2 else float(np.std(demand_values))
    z = _z_score(planning_input.service_level)
    lt = max(1, int(planning_input.lead_time_days))
    safety_stock = max(0.0, z * daily_std * np.sqrt(lt))

    available = float(planning_input.current_stock) + float(planning_input.in_transit)
    gross_required = forecast_demand + safety_stock
    net_required = max(0.0, gross_required - available)

    production_qty = _apply_rounding_rules(net_required, planning_input.moq, planning_input.pack_size)
    replenish_qty = _apply_rounding_rules(max(0.0, production_qty * 0.6), planning_input.moq, planning_input.pack_size)

    avg_daily = max(1e-6, float(demand_values.mean()))
    cover_days = available / avg_daily

    risk_level = "low"
    if cover_days < 7:
        risk_level = "high"
    elif cover_days < 14:
        risk_level = "medium"

    return {
        "product_name": planning_input.product_name,
        "forecast_demand": round(forecast_demand, 2),
        "available_stock": round(available, 2),
        "safety_stock": round(safety_stock, 2),
        "production_recommendation": round(production_qty, 2),
        "replenishment_recommendation": round(replenish_qty, 2),
        "stock_cover_days": round(cover_days, 1),
        "risk_level": risk_level,
        "parameters": {
            "lead_time_days": lt,
            "service_level": planning_input.service_level,
            "moq": planning_input.moq,
            "pack_size": planning_input.pack_size,
        },
    }


def _apply_rounding_rules(quantity: float, moq: float, pack_size: float) -> float:
    if quantity <= 0:
        return 0.0

    qty = quantity
    if moq > 0:
        qty = max(qty, moq)

    if pack_size > 0:
        qty = np.ceil(qty / pack_size) * pack_size

    return float(qty)
