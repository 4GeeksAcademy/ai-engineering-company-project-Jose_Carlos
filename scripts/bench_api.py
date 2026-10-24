"""Mide la latencia de los endpoints de lectura de la API (hito 13: caching).

Uso (desde la raíz del repo, con la API arrancada):
    BENCH_EMAIL=cea@example.com BENCH_PASSWORD=... uv run python scripts/bench_api.py --label antes-seed
    uv run python scripts/bench_api.py --label con-cache --runs 20

- Inicia sesión una vez y repite cada petición (misma URL, mismos query params) `--runs` veces.
- La primera petición de cada URL se guarda aparte (`first_ms`): con caché es el MISS y
  las siguientes son HIT; sin caché suele ser algo más lenta por el "calentamiento".
- Guarda el resultado en docs/caching/bench-<label>.json y muestra una tabla en consola.
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "docs" / "caching"

# (nombre, ruta con query params). {me} se sustituye por el id del usuario de la sesión.
ENDPOINTS = [
    ("root", "/"),
    ("auth_me", "/auth/me"),
    ("users_me", "/users/{me}"),
    ("profiles_me", "/profiles/me"),
    ("profiles_id", "/profiles/{me}"),
    ("suppliers", "/suppliers"),
    ("suppliers_filtered", "/suppliers?country=USA&category=carrier_last_mile"),
    ("supplier_detail", "/suppliers/1"),
    ("incidents", "/api/incidents"),
    ("incidents_filtered", "/api/incidents?status=open&branch=la_warehouse"),
    ("incidents_summary", "/api/incidents/summary"),
    ("incidents_semantic_status", "/api/incidents/semantic-status"),
    ("incidents_search", "/api/incidents/search?q=paquete%20perdido%20sin%20escaneos&limit=20"),
    ("incidents_duplicates", "/api/incidents/duplicates"),
    ("incident_detail", "/api/incidents/1"),
    ("incident_similar", "/api/incidents/1/similar"),
    ("inventory_products", "/inventory/products"),
    ("inventory_product_detail", "/inventory/products/1"),
    ("inventory_orders", "/inventory/orders"),
]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=10, help="Peticiones por endpoint (por defecto 10).")
    parser.add_argument("--slow-runs", type=int, default=3, help="Peticiones para los que tardan más de 5 s.")
    parser.add_argument("--label", required=True, help="Nombre de la medición (antes-seed, con-seed, con-cache...).")
    parser.add_argument("--only", nargs="*", help="Medir solo estos endpoints (por nombre).")
    args = parser.parse_args()

    email = os.getenv("BENCH_EMAIL", "cea@example.com")
    password = os.getenv("BENCH_PASSWORD")
    if not password:
        sys.exit("Define BENCH_PASSWORD con la contraseña del usuario de pruebas.")

    with httpx.Client(base_url=args.base_url, timeout=300) as client:
        login = client.post("/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        me = client.get("/auth/me").json()["id"]

        results = []
        for name, path in ENDPOINTS:
            if args.only and name not in args.only:
                continue
            url = path.format(me=me)
            timings, status, size = [], None, 0
            runs = args.runs
            run = 0
            while run < runs:
                start = time.perf_counter()
                response = client.get(url)
                timings.append((time.perf_counter() - start) * 1000)
                status, size = response.status_code, len(response.content)
                if run == 0 and timings[0] > 5000:
                    runs = min(runs, args.slow_runs)
                run += 1
            rest = timings[1:] or timings
            row = {
                "name": name,
                "url": url.replace(me, "{me}"),
                "status": status,
                "bytes": size,
                "runs": len(timings),
                "first_ms": round(timings[0], 1),
                "median_rest_ms": round(statistics.median(rest), 1),
                "p95_ms": round(percentile(timings, 95), 1),
                "min_ms": round(min(timings), 1),
                "max_ms": round(max(timings), 1),
            }
            results.append(row)
            print(
                f"{name:28} {status} {size/1024:8.1f} KB  1ª {row['first_ms']:9.1f} ms  "
                f"mediana resto {row['median_rest_ms']:9.1f} ms  p95 {row['p95_ms']:9.1f} ms  (n={row['runs']})",
                flush=True,
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"bench-{args.label}.json"
    output.write_text(json.dumps({"label": args.label, "base_url": args.base_url, "results": results}, indent=2), encoding="utf-8")
    print(f"\nGuardado en {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
