"""Golden del analizador con el dataset real (U-A3 b) y su paso por la API (U-A4, nivel HTTP).

El golden es la salida agregada registrada en R4-B
(audit/evidence/dynamic/r4b/analyzer_component_check.output.json), copiada sin cambios en
tests/golden/analyzer_incidents_trackflow.r4b.json. Solo contiene agregados: ningún id, email ni
valor de fila. Los agregados se recalculan aquí con la misma lógica que el script de R4-B.
"""

import collections
import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts.analyze import analyzeCsv

REPO = Path(__file__).resolve().parents[1]
GOLDEN = json.loads((REPO / "tests" / "golden" / "analyzer_incidents_trackflow.r4b.json").read_text(encoding="utf-8"))
DATASET = REPO / GOLDEN["provenance"]["dataset"]
R4B = GOLDEN["r4b_output"]
EXPORT_URL = "/api/incidents/results/export"


def r4b_aggregates(results, csv_path):
    """Misma estructura que imprime audit/evidence/dynamic/r4b/analyzer_component_check.py."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        total_rows = sum(1 for _ in reader)
    error_types = collections.Counter(e for rec in results["errores"] for e in rec["errors"])
    try:
        json.dumps(results)
        json_serializable = True
    except (TypeError, ValueError):
        json_serializable = False
    return {
        "input": {"data_rows": total_rows, "column_count": len(header)},
        "result_keys": sorted(results),
        "valid": results["valid"],
        "invalid": results["invalid"],
        "valid_plus_invalid_equals_rows": results["valid"] + results["invalid"] == total_rows,
        "categories": results["categories"],
        "statuses": results["statuses"],
        "media_satisfaccion": round(results["media_satisfaccion"], 4),
        "invalid_records_listed": len(results["errores"]),
        "error_message_type_counts": dict(error_types),
        "json_serializable": json_serializable,
        "database_py_imported": any(
            str(getattr(m, "__file__", "") or "").replace("\\", "/").endswith("services/api/database.py")
            for m in list(sys.modules.values())
        ),
    }


@pytest.fixture(scope="module")
def results():
    return analyzeCsv(str(DATASET))


def test_dataset_is_the_one_analyzed_in_r4b():
    digest = hashlib.sha256(DATASET.read_bytes()).hexdigest()

    assert digest == GOLDEN["provenance"]["dataset_sha256"], "el dataset ya no es el analizado en R4-B: el golden no aplica"


def test_analyze_csv_reproduces_r4b_golden(results):
    assert r4b_aggregates(results, DATASET) == R4B


def test_breakdown_order_matches_r4b(results):
    # El orden de primera aparición determina el orden de las filas del export CSV.
    assert list(results["categories"]) == list(R4B["categories"])
    assert list(results["statuses"]) == list(R4B["statuses"])


def test_invalid_records_keep_their_shape(results):
    assert all(set(rec) == {"incident_id", "errors"} for rec in results["errores"])
    assert all(isinstance(rec["errors"], list) and rec["errors"] for rec in results["errores"])


def test_post_analyze_with_real_dataset_matches_golden(client):
    response = client.post("/analyze", files={"file": (DATASET.name, DATASET.read_bytes(), "text/csv")})

    assert response.status_code == 200
    assert response.json() == analyzeCsv(str(DATASET))
    assert r4b_aggregates(response.json(), DATASET) == R4B


def test_export_after_real_dataset_matches_golden(client):
    client.post("/analyze", files={"file": (DATASET.name, DATASET.read_bytes(), "text/csv")})

    response = client.get(EXPORT_URL)

    expected_rows = [
        "metric,value",
        f"valid_rows,{R4B['valid']}",
        f"invalid_rows,{R4B['invalid']}",
        *(f"category_{k},{v}" for k, v in R4B["categories"].items()),
        *(f"status_{k},{v}" for k, v in R4B["statuses"].items()),
        f"average_satisfaction,{R4B['media_satisfaccion']:.2f}",
    ]
    assert response.status_code == 200
    assert response.headers["content-disposition"] == "attachment; filename=results.csv"
    assert response.text == "\r\n".join(expected_rows) + "\r\n"
