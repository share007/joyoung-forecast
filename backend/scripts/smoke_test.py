import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:8000"


def get(path: str):
    with urllib.request.urlopen(BASE_URL + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path: str, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def load_sample_rows(sample_csv: Path):
    rows = []
    with sample_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({"date": row["date"], "sales": float(row["sales"])})
    return rows


def main():
    root = get("/")
    products = get("/products")
    product_name = products[0]["name"]

    sample_csv = Path(__file__).resolve().parents[1] / "data" / "sample_sales_data.csv"
    rows = load_sample_rows(sample_csv)

    encoded_product = urllib.parse.quote(product_name)

    import_result = post(f"/products/{encoded_product}/data", rows)
    forecast_result = post(
        "/forecast",
        {
            "product_name": product_name,
            "forecast_days": 15,
            "historical_data": rows,
        },
    )
    planning_result = post(
        "/planning/recommendation",
        {
            "product_name": product_name,
            "forecast_days": 15,
            "historical_data": rows,
            "in_transit": 80,
            "lead_time_days": 10,
            "service_level": 0.95,
            "moq": 50,
            "pack_size": 10,
        },
    )
    imports_result = get(f"/products/{encoded_product}/imports")

    summary = {
        "root": root,
        "product_used": product_name,
        "imported_count": import_result.get("imported_count"),
        "forecast_method": forecast_result.get("metrics", {}).get("method"),
        "forecast_points": len(forecast_result.get("predictions", [])),
        "first_prediction": forecast_result.get("predictions", [{}])[0],
        "planning": {
            "production_recommendation": planning_result.get("recommendation", {}).get("production_recommendation"),
            "replenishment_recommendation": planning_result.get("recommendation", {}).get("replenishment_recommendation"),
            "safety_stock": planning_result.get("recommendation", {}).get("safety_stock"),
            "risk_level": planning_result.get("recommendation", {}).get("risk_level"),
        },
        "import_batches_found": len(imports_result.get("batches", [])),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
