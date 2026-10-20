"use client";

import Link from "next/link";
import { useState } from "react";
import { CATEGORY_LABELS, Sku, errorMessage, formatUnits, inventoryApi, stockLevel, warehouseName } from "../../../lib/inventory";
import { useApiResource } from "../../../lib/use-api-resource";
import { Alert, AlertState, INPUT_CLASS, REFRESH_BUTTON_CLASS, StockBadge } from "../../../ui/inventory-ui";

// Stock por SKU — GET /inventory/products.

function otherWarehouses(sku: Sku) {
  return Object.entries(sku.stock_by_warehouse).filter(([code, units]) => code !== sku.warehouse && units !== 0);
}

function ActionLink({ label, href, sku }: { label: string; href: string; sku: Sku }) {
  return (
    <Link
      href={`${href}?sku_id=${encodeURIComponent(sku.id)}`}
      aria-label={`${label} de ${sku.sku}`}
      className="inline-flex items-center justify-center whitespace-nowrap rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200"
    >
      {label}
    </Link>
  );
}

export function ProductsClient() {
  const [alert, setAlert] = useState<AlertState>(null);
  const { data: skus, loaded, loading, reload } = useApiResource(inventoryApi.listSkus, [] as Sku[], {
    onError: (error) => setAlert({ type: "error", message: `No se pudo cargar el stock. ${errorMessage(error)}` }),
  });
  const [warehouse, setWarehouse] = useState("");
  const [level, setLevel] = useState("");
  const [search, setSearch] = useState("");

  // Cada pulsación de "Actualizar" vuelve a pedir el stock.
  function load() {
    setAlert(null);
    reload();
  }

  function matchesFilters(sku: Sku) {
    const key = stockLevel(sku.current_stock).key;
    if (warehouse && sku.warehouse !== warehouse) return false;
    if (level === "attention" && key === "ok") return false;
    if (level === "out" && key !== "out") return false;
    const term = search.trim().toLowerCase();
    return !term || [sku.sku, sku.name, sku.client_name].some((value) => value.toLowerCase().includes(term));
  }

  const visible = skus.filter(matchesFilters);
  const levels = skus.map((sku) => stockLevel(sku.current_stock).key);

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Inventario · Los Ángeles y Zaragoza</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">Stock por SKU</h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Stock calculado a partir de las entradas y salidas registradas. Cada almacén tiene su propia cifra: nunca se suman. Desde
          cada SKU puedes registrar una recepción de mercancía o una salida de stock.
        </p>
      </section>

      <section className="mt-6 grid gap-3 sm:grid-cols-3" aria-label="Resumen del stock">
        <div className="rounded-2xl border border-cyan-200 bg-white p-4 shadow-sm">
          <p className="text-sm font-semibold text-slate-600">SKUs registrados</p>
          <p id="totalCount" className="mt-1 text-3xl font-black text-slate-900">{loaded ? String(skus.length) : "—"}</p>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 shadow-sm">
          <p className="text-sm font-semibold text-amber-900">! Stock bajo (1–49 unidades)</p>
          <p id="lowCount" className="mt-1 text-3xl font-black text-amber-900">
            {loaded ? String(levels.filter((key) => key === "low").length) : "—"}
          </p>
        </div>
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 shadow-sm">
          <p className="text-sm font-semibold text-red-800">✕ Sin stock (0 unidades)</p>
          <p id="outCount" className="mt-1 text-3xl font-black text-red-800">
            {loaded ? String(levels.filter((key) => key === "out").length) : "—"}
          </p>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="list-title">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 id="list-title" className="text-xl font-bold text-slate-900">SKUs</h2>
            <p id="resultsCount" className="mt-1 text-sm text-slate-600" aria-live="polite">
              {loaded && skus.length ? `Mostrando ${visible.length} de ${skus.length} SKUs.` : ""}
            </p>
            <p className="mt-2 flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-emerald-800">✓ Stock OK: 50 o más</span>
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-amber-900">! Stock bajo: 1–49</span>
              <span className="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-red-800">✕ Sin stock: 0</span>
            </p>
          </div>

          <form id="filtersForm" className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end" onSubmit={(event) => event.preventDefault()}>
            <label className="block text-sm font-semibold text-slate-700">
              Almacén
              <select id="warehouseFilter" name="warehouse" value={warehouse} onChange={(event) => setWarehouse(event.target.value)} className={`${INPUT_CLASS} sm:w-44`}>
                <option value="">Todos</option>
                <option value="LA">Los Ángeles</option>
                <option value="ZGZ">Zaragoza</option>
              </select>
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Nivel de stock
              <select id="levelFilter" name="level" value={level} onChange={(event) => setLevel(event.target.value)} className={`${INPUT_CLASS} sm:w-48`}>
                <option value="">Todos</option>
                <option value="attention">Bajo o sin stock</option>
                <option value="out">Solo sin stock</option>
              </select>
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Buscar
              <input
                id="searchFilter"
                name="search"
                type="search"
                placeholder="SKU, nombre o marca"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className={`${INPUT_CLASS} sm:w-56`}
              />
            </label>
            <button id="refreshButton" type="button" disabled={loading} onClick={load} className={REFRESH_BUTTON_CLASS}>
              Actualizar
            </button>
          </form>
        </div>

        <Alert id="listAlert" alert={alert} wrapperClass="mt-5" />
        <p id="listLoading" className="mt-5 text-sm font-semibold text-cyan-800" hidden={!loading}>
          Cargando stock…
        </p>

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full divide-y divide-cyan-100 text-left text-sm">
            <thead className="bg-cyan-50 text-xs font-bold uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-3">SKU</th>
                <th scope="col" className="px-3 py-3">Nombre</th>
                <th scope="col" className="px-3 py-3">Marca cliente</th>
                <th scope="col" className="px-3 py-3">Categoría</th>
                <th scope="col" className="px-3 py-3">Almacén</th>
                <th scope="col" className="px-3 py-3">Stock actual</th>
                <th scope="col" className="px-3 py-3">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody id="skuTableBody" className="divide-y divide-cyan-50">
              {visible.map((sku) => {
                const skuLevel = stockLevel(sku.current_stock);
                const tint = { out: "bg-red-50/60", low: "bg-amber-50/60", ok: "" }[skuLevel.key];
                return (
                  <tr key={sku.id} data-sku-id={sku.id} data-level={skuLevel.key} className={`align-top ${tint}`}>
                    <td className="whitespace-nowrap px-3 py-3 font-mono text-xs font-bold text-slate-900">{sku.sku}</td>
                    <td className="px-3 py-3 font-semibold text-slate-900">{sku.name}</td>
                    <td className="px-3 py-3 text-slate-700">{sku.client_name}</td>
                    <td className="px-3 py-3 text-slate-700">{CATEGORY_LABELS[sku.category] || sku.category}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-700">{warehouseName(sku.warehouse)}</td>
                    <td className="px-3 py-3">
                      <StockBadge units={sku.current_stock} />
                      {otherWarehouses(sku).map(([code, units]) => (
                        <p key={code} className="mt-1 text-xs text-slate-500">{`En ${warehouseName(code)}: ${formatUnits(units)}`}</p>
                      ))}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-2">
                        <ActionLink label="Registrar entrada" href="/inventory/orders/inbound" sku={sku} />
                        <ActionLink label="Registrar salida" href="/inventory/orders/outbound" sku={sku} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p
          id="emptyState"
          hidden={!loaded || visible.length > 0}
          className="mt-5 rounded-xl border border-dashed border-cyan-200 p-6 text-center text-sm text-slate-600"
        >
          {skus.length ? "Ningún SKU coincide con los filtros." : "Todavía no hay SKUs registrados."}
        </p>
      </section>
    </main>
  );
}
