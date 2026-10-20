"use client";

import { useEffect, useState } from "react";
import { SessionExpiredError } from "../../../lib/auth";
import { EXIT_TYPE_LABELS, InventoryOrder, errorMessage, formatDateTime, formatUnits, inventoryApi, warehouseName } from "../../../lib/inventory";
import { useSession } from "../../../ui/auth-guard";
import { Alert, AlertState, INPUT_CLASS, REFRESH_BUTTON_CLASS } from "../../../ui/inventory-ui";

// Movimientos de stock — GET /inventory/orders. Solo lectura: sin acciones de edición ni borrado.

const TYPE_STYLES = {
  inbound: {
    label: "↓ Entrada",
    badge: "border-emerald-200 bg-emerald-50 text-emerald-800",
    edge: "border-l-4 border-l-emerald-400",
    quantity: "text-emerald-700",
    sign: "+",
  },
  outbound: {
    label: "↑ Salida",
    badge: "border-rose-200 bg-rose-50 text-rose-800",
    edge: "border-l-4 border-l-rose-400",
    quantity: "text-rose-700",
    sign: "−",
  },
};

function detail(order: InventoryOrder) {
  if (order.order_type === "inbound") return `Ref. ${order.reference}`;
  return order.tracking_number ? `Seguimiento ${order.tracking_number}` : "—";
}

function subtype(order: InventoryOrder) {
  return order.order_type === "inbound" ? "Recepción de mercancía" : EXIT_TYPE_LABELS[order.exit_type ?? ""] || order.exit_type;
}

export function OrdersClient() {
  // El usuario de la sesión (lo carga el guard con GET /auth/me) marca sus movimientos con "Tú".
  const currentUserId = useSession()?.user.id ?? null;
  const [orders, setOrders] = useState<InventoryOrder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [alert, setAlert] = useState<AlertState>(null);
  const [type, setType] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [search, setSearch] = useState("");
  // Cada pulsación de "Actualizar" vuelve a pedir el historial.
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    inventoryApi
      .listOrders()
      .then((list) => {
        if (cancelled) return;
        setOrders(list);
        setLoaded(true);
      })
      .catch((error) => {
        if (cancelled || error instanceof SessionExpiredError) return;
        setAlert({ type: "error", message: `No se pudo cargar el historial. ${errorMessage(error)}` });
        setLoaded(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshTick]);

  function load() {
    setLoading(true);
    setAlert(null);
    setRefreshTick((tick) => tick + 1);
  }

  function matchesFilters(order: InventoryOrder) {
    if (type && order.order_type !== type) return false;
    if (warehouse && order.warehouse !== warehouse) return false;
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return [order.sku.sku, order.sku.name, order.sku.client_name, order.reference, order.tracking_number].some(
      (value) => value && value.toLowerCase().includes(term),
    );
  }

  const visible = orders.filter(matchesFilters);
  const entries = orders.filter((order) => order.order_type === "inbound").length;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Inventario · Historial</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">Movimientos de stock</h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Todas las entradas y salidas registradas, las más recientes primero, con el SKU y la persona que registró cada una. Es un
          registro de solo lectura: los movimientos no se editan ni se borran.
        </p>
      </section>

      <section className="mt-6 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="list-title">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 id="list-title" className="text-xl font-bold text-slate-900">Movimientos</h2>
            <p id="resultsCount" className="mt-1 text-sm text-slate-600" aria-live="polite">
              {loaded && orders.length
                ? `Mostrando ${visible.length} de ${orders.length} movimientos (${entries} entradas, ${orders.length - entries} salidas).`
                : ""}
            </p>
          </div>
          <form id="filtersForm" className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end" onSubmit={(event) => event.preventDefault()}>
            <label className="block text-sm font-semibold text-slate-700">
              Tipo
              <select id="typeFilter" name="type" value={type} onChange={(event) => setType(event.target.value)} className={`${INPUT_CLASS} sm:w-40`}>
                <option value="">Todos</option>
                <option value="inbound">Entradas</option>
                <option value="outbound">Salidas</option>
              </select>
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Almacén
              <select id="warehouseFilter" name="warehouse" value={warehouse} onChange={(event) => setWarehouse(event.target.value)} className={`${INPUT_CLASS} sm:w-44`}>
                <option value="">Todos</option>
                <option value="LA">Los Ángeles</option>
                <option value="ZGZ">Zaragoza</option>
              </select>
            </label>
            <label className="block text-sm font-semibold text-slate-700">
              Buscar
              <input
                id="searchFilter"
                name="search"
                type="search"
                placeholder="SKU, nombre o referencia"
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
          Cargando movimientos…
        </p>

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full divide-y divide-cyan-100 text-left text-sm">
            <thead className="bg-cyan-50 text-xs font-bold uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-3 py-3">Fecha</th>
                <th scope="col" className="px-3 py-3">Tipo</th>
                <th scope="col" className="px-3 py-3">SKU</th>
                <th scope="col" className="px-3 py-3 text-right">Unidades</th>
                <th scope="col" className="px-3 py-3">Almacén</th>
                <th scope="col" className="px-3 py-3">Referencia / seguimiento</th>
                <th scope="col" className="px-3 py-3">Registrado por</th>
              </tr>
            </thead>
            <tbody id="ordersTableBody" className="divide-y divide-cyan-50">
              {visible.map((order) => {
                const style = TYPE_STYLES[order.order_type];
                return (
                  <tr key={`${order.order_type}-${order.id}`} data-order-type={order.order_type} className="align-top">
                    <td title={order.created_at} className={`whitespace-nowrap px-3 py-3 text-slate-700 ${style.edge}`}>
                      {formatDateTime(order.created_at)}
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold ${style.badge}`}>{style.label}</span>
                      <p className="mt-1 text-xs text-slate-500">{subtype(order)}</p>
                    </td>
                    <td className="px-3 py-3">
                      <p className="font-mono text-xs font-bold text-slate-900">{order.sku.sku}</p>
                      <p className="text-slate-800">{order.sku.name}</p>
                      <p className="text-xs text-slate-500">{order.sku.client_name}</p>
                    </td>
                    <td
                      aria-label={`${order.order_type === "inbound" ? "Entran" : "Salen"} ${formatUnits(order.quantity)}`}
                      className={`whitespace-nowrap px-3 py-3 text-right font-bold ${style.quantity}`}
                    >
                      {`${style.sign}${Number(order.quantity).toLocaleString("es-ES")}`}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-slate-700">{warehouseName(order.warehouse)}</td>
                    <td className="px-3 py-3 font-mono text-xs text-slate-700">{detail(order)}</td>
                    <td className="px-3 py-3">
                      <p className="break-all font-mono text-xs text-slate-700">{order.user_uuid}</p>
                      {currentUserId && order.user_uuid === currentUserId && (
                        <span className="mt-1 inline-block rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-bold text-cyan-800">Tú</span>
                      )}
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
          {orders.length ? "Ningún movimiento coincide con los filtros." : "Todavía no hay movimientos de stock registrados."}
        </p>
      </section>
    </main>
  );
}
