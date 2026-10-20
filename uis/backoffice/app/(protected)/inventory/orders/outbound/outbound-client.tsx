"use client";

// Salida de stock — POST /inventory/orders/outbound (StockExit): despacho a cliente o pérdida.
//
// Al elegir un SKU se pide su stock actual a la API (GET /inventory/products/{id}) y se muestra
// el disponible en el almacén de salida antes de enviar. Si la cantidad lo supera, se avisa en el
// cliente; la regla real la aplica la API, que responde 400 y su mensaje se muestra junto al campo.

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useRef, useState } from "react";
import { SessionExpiredError } from "../../../../lib/auth";
import {
  FieldErrors,
  InventoryApiError,
  InventoryOrder,
  Sku,
  errorMessage,
  formatUnits,
  inventoryApi,
  positiveInteger,
  stockLevel,
  warehouseName,
} from "../../../../lib/inventory";
import { useApiResource } from "../../../../lib/use-api-resource";
import { Alert, AlertState, FieldError, INPUT_CLASS, SUBMIT_BUTTON_CLASS, SkuOptions, StockBadge, useFocusField } from "../../../../ui/inventory-ui";

type Form = { sku_id: string; warehouse: string; exit_type: "dispatch" | "loss"; tracking_number: string; quantity: string };
const EMPTY_FORM: Form = { sku_id: "", warehouse: "", exit_type: "dispatch", tracking_number: "", quantity: "" };
// Campos con hueco para su error, en el orden en que se validan.
const FIELD_ORDER = ["sku_id", "warehouse", "exit_type", "tracking_number", "quantity"];

type StockState = { status: "idle" | "loading" | "ready" | "error"; sku: Sku | null; error: string | null };
const IDLE_STOCK: StockState = { status: "idle", sku: null, error: null };

function validate(form: Form): FieldErrors {
  const errors: FieldErrors = {};
  if (!form.sku_id) errors.sku_id = "Elige el SKU que sale.";
  if (!form.warehouse) errors.warehouse = "Elige el almacén del que sale la mercancía.";
  if (form.exit_type === "dispatch" && !form.tracking_number.trim()) {
    errors.tracking_number = "Introduce el número de seguimiento del transportista: es obligatorio en un despacho.";
  }
  if (positiveInteger(form.quantity) === null) errors.quantity = "Introduce un número entero de unidades mayor que 0.";
  return errors;
}

export function OutboundClient() {
  const searchParams = useSearchParams();
  const { formRef, focusField: setFocusField } = useFocusField();
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [stock, setStock] = useState<StockState>(IDLE_STOCK);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [alert, setAlert] = useState<AlertState>(null);
  const [submitting, setSubmitting] = useState(false);
  // Tras un 400 de stock insuficiente manda el mensaje de la API: el aviso del cliente se calla
  // hasta que se cambie la cantidad, para no repetir lo mismo dos veces.
  const [apiQuantityError, setApiQuantityError] = useState(false);
  // Solo cuenta la respuesta de la última consulta de stock (el usuario puede cambiar de SKU deprisa).
  const stockRequest = useRef(0);
  const {
    data: skus,
    setData: setSkus,
    loading: skusLoading,
  } = useApiResource(inventoryApi.listSkus, [] as Sku[], {
    key: searchParams.toString(),
    onLoaded: (list) => {
      const preselected = list.find((sku) => String(sku.id) === searchParams.get("sku_id"));
      if (preselected) selectSku(String(preselected.id), list);
      if (!list.length) setAlert({ type: "warning", message: "No hay SKUs registrados todavía: no se puede registrar ninguna salida." });
    },
    onError: (error) => setAlert({ type: "error", message: `No se pudo cargar la lista de SKUs. ${errorMessage(error)}` }),
  });

  const loadStock = useCallback(async (skuId: string) => {
    const request = ++stockRequest.current;
    if (!skuId) {
      setStock(IDLE_STOCK);
      return;
    }
    setStock({ status: "loading", sku: null, error: null });
    try {
      const sku = await inventoryApi.getSku(skuId);
      if (request !== stockRequest.current) return;
      setSkus((current) => current.map((item) => (item.id === sku.id ? sku : item)));
      setStock({ status: "ready", sku, error: null });
    } catch (error) {
      if (request !== stockRequest.current || error instanceof SessionExpiredError) return;
      setStock({ status: "error", sku: null, error: errorMessage(error) });
    }
  }, [setSkus]);

  // Otro SKU, almacén o cantidad: el 400 anterior ya no aplica.
  function clearApiQuantityError() {
    if (!apiQuantityError) return;
    setApiQuantityError(false);
    setFieldErrors((current) => {
      const next = { ...current };
      delete next.quantity;
      return next;
    });
  }

  function selectSku(skuId: string, list: Sku[]) {
    const sku = list.find((item) => String(item.id) === skuId);
    // El almacén de salida por defecto es el del SKU; se puede cambiar si sale del otro almacén.
    setForm((current) => ({ ...current, sku_id: skuId, warehouse: sku ? sku.warehouse : current.warehouse }));
    loadStock(skuId);
  }

  const available = stock.status === "ready" && stock.sku && form.warehouse ? stock.sku.stock_by_warehouse[form.warehouse] ?? 0 : null;
  const quantity = positiveInteger(form.quantity);
  const showWarning = !apiQuantityError && available !== null && quantity !== null && quantity > available;
  const isDispatch = form.exit_type === "dispatch";

  async function confirmation(stockExit: InventoryOrder) {
    const what =
      stockExit.exit_type === "dispatch"
        ? `despacho de ${formatUnits(stockExit.quantity)}, seguimiento ${stockExit.tracking_number}`
        : `pérdida de ${formatUnits(stockExit.quantity)}`;
    const base = `Salida registrada: ${what} de ${stockExit.sku.sku} (${stockExit.sku.name}) desde ${warehouseName(stockExit.warehouse)}.`;
    try {
      const fresh = await inventoryApi.getSku(stockExit.sku_id);
      setSkus((current) => current.map((item) => (item.id === fresh.id ? fresh : item)));
      return `${base} Quedan ${formatUnits(fresh.stock_by_warehouse[stockExit.warehouse])} en ${warehouseName(stockExit.warehouse)}.`;
    } catch (error) {
      if (error instanceof SessionExpiredError) throw error;
      return `${base} (No se pudo consultar el stock actualizado: ${errorMessage(error)})`;
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFieldErrors({});
    setAlert(null);

    const errors = validate(form);
    if (Object.keys(errors).length) {
      setFieldErrors(errors);
      setAlert({ type: "error", message: "Revisa los campos marcados." });
      setFocusField(Object.keys(errors)[0]);
      return;
    }

    setSubmitting(true);
    try {
      const stockExit = await inventoryApi.registerExit({
        sku_id: Number(form.sku_id),
        quantity: positiveInteger(form.quantity) as number,
        exit_type: form.exit_type,
        tracking_number: isDispatch ? form.tracking_number.trim() : null,
        warehouse: form.warehouse,
      });
      const message = await confirmation(stockExit);
      setForm(EMPTY_FORM);
      setApiQuantityError(false);
      stockRequest.current++;
      setStock(IDLE_STOCK);
      setAlert({ type: "success", message });
      setFocusField("sku_id");
    } catch (error) {
      if (error instanceof SessionExpiredError) return;
      const apiErrors = error instanceof InventoryApiError ? error.fieldErrors : {};
      const unplaced = Object.entries(apiErrors)
        .filter(([field]) => !FIELD_ORDER.includes(field))
        .map(([, message]) => message);
      setFieldErrors(apiErrors);
      if (error instanceof InventoryApiError && error.kind === "insufficient_stock") {
        setApiQuantityError(true);
        // El 400 va junto al campo de cantidad; el panel se actualiza con el stock real de la API.
        setAlert({ type: "error", message: "No se ha registrado la salida: no hay stock suficiente. Revisa la cantidad." });
        setFocusField("quantity");
        loadStock(form.sku_id);
      } else {
        setAlert({ type: "error", message: [`No se ha registrado la salida. ${errorMessage(error)}`, ...unplaced].join(" ") });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const invalid = (field: string) => (fieldErrors[field] ? true : undefined);

  // ---------------------------------------------------------------- panel de stock
  function stockPanel() {
    if (stock.status === "idle") return "Selecciona un SKU para ver su stock disponible.";
    if (stock.status === "loading") return <p className="font-semibold text-cyan-800">Consultando el stock actual…</p>;
    if (stock.status === "error" || !stock.sku) {
      return (
        <>
          <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">{`No se pudo consultar el stock. ${stock.error}`}</p>
          <button
            type="button"
            onClick={() => loadStock(form.sku_id)}
            className="mt-3 rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-800 hover:bg-cyan-50"
          >
            Reintentar
          </button>
        </>
      );
    }
    const sku = stock.sku;
    const warehouse = form.warehouse || sku.warehouse;
    const units = sku.stock_by_warehouse[warehouse] ?? 0;
    return (
      <>
        <p className="font-mono text-xs font-bold text-slate-900">{sku.sku}</p>
        <p className="font-semibold text-slate-800">{sku.name}</p>
        <p className="mt-4 text-xs font-bold uppercase tracking-wide text-slate-500">{`Disponible en ${warehouseName(warehouse)}`}</p>
        <p id="availableStock" data-units={String(units)} className={`mt-1 text-4xl font-black ${stockLevel(units).text}`}>
          {formatUnits(units)}
        </p>
        <StockBadge units={units} showLevel />
        {Object.entries(sku.stock_by_warehouse)
          .filter(([code, otherUnits]) => code !== warehouse && otherUnits !== 0)
          .map(([code, otherUnits]) => (
            <p key={code} className="mt-3 text-xs text-slate-500">
              {`En ${warehouseName(code)} hay ${formatUnits(otherUnits)}, que no cuentan para esta salida.`}
            </p>
          ))}
        {units <= 0 && (
          <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 font-semibold text-red-700">
            {`No hay stock de este SKU en ${warehouseName(warehouse)}: no se puede registrar ninguna salida desde este almacén.`}
          </p>
        )}
      </>
    );
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Inventario · Salida de stock</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">Salida de stock</h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Registra un despacho a cliente final o una pérdida confirmada. Antes de enviar verás el stock disponible del SKU en el
          almacén de salida: no se puede sacar más de lo que hay.
        </p>
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="form-title">
          <h2 id="form-title" className="text-xl font-bold text-slate-900">Nueva salida de stock</h2>
          <Alert id="formAlert" alert={alert} role="status" wrapperClass="mt-4" />

          <form id="exitForm" ref={formRef} className="mt-5 grid gap-5 md:grid-cols-2" noValidate onSubmit={onSubmit}>
            <div className="md:col-span-2">
              <label className="block text-sm font-semibold text-slate-700">
                SKU
                <select
                  id="sku_idInput"
                  name="sku_id"
                  required
                  disabled={skusLoading}
                  value={form.sku_id}
                  aria-invalid={invalid("sku_id")}
                  onChange={(event) => {
                    clearApiQuantityError();
                    selectSku(event.target.value, skus);
                  }}
                  className={INPUT_CLASS}
                >
                  <SkuOptions skus={skus} />
                </select>
                <FieldError field="sku_id" message={fieldErrors.sku_id} />
              </label>
            </div>
            <label className="block text-sm font-semibold text-slate-700">
              Almacén de salida
              <select
                id="warehouseInput"
                name="warehouse"
                required
                value={form.warehouse}
                aria-invalid={invalid("warehouse")}
                onChange={(event) => {
                  clearApiQuantityError();
                  setForm((current) => ({ ...current, warehouse: event.target.value }));
                }}
                className={INPUT_CLASS}
              >
                <option value="">Selecciona un almacén…</option>
                <option value="LA">Los Ángeles (LA)</option>
                <option value="ZGZ">Zaragoza (ZGZ)</option>
              </select>
              <FieldError field="warehouse" message={fieldErrors.warehouse} />
            </label>
            <fieldset>
              <legend className="text-sm font-semibold text-slate-700">Tipo de salida</legend>
              <div className="mt-2 flex flex-wrap gap-3">
                {(
                  [
                    ["dispatch", "Despacho a cliente"],
                    ["loss", "Pérdida"],
                  ] as const
                ).map(([value, label]) => (
                  <label
                    key={value}
                    className="inline-flex items-center gap-2 rounded-lg border border-cyan-200 px-3 py-2 text-sm font-semibold text-slate-700 has-[:checked]:border-cyan-600 has-[:checked]:bg-cyan-50"
                  >
                    <input
                      type="radio"
                      name="exit_type"
                      value={value}
                      checked={form.exit_type === value}
                      onChange={() =>
                        setForm((current) => ({
                          ...current,
                          exit_type: value,
                          // Una pérdida no lleva número de seguimiento.
                          tracking_number: value === "dispatch" ? current.tracking_number : "",
                        }))
                      }
                      className="accent-cyan-700"
                    />{" "}
                    {label}
                  </label>
                ))}
              </div>
              <FieldError field="exit_type" message={fieldErrors.exit_type} />
            </fieldset>
            <label id="trackingField" className={`block text-sm font-semibold text-slate-700 md:col-span-2 ${isDispatch ? "" : "hidden"}`}>
              Número de seguimiento del transportista
              <input
                id="trackingInput"
                name="tracking_number"
                type="text"
                maxLength={64}
                placeholder="Ej.: 1Z999AA10123456784"
                autoComplete="off"
                disabled={!isDispatch}
                value={form.tracking_number}
                aria-invalid={invalid("tracking_number")}
                onChange={(event) => setForm((current) => ({ ...current, tracking_number: event.target.value }))}
                className={INPUT_CLASS}
              />
              <span className="mt-1 block text-xs font-normal text-slate-500">
                Obligatorio en un despacho. Una pérdida no lleva número de seguimiento.
              </span>
              <FieldError field="tracking_number" message={fieldErrors.tracking_number} />
            </label>
            <label className="block text-sm font-semibold text-slate-700 md:col-span-2">
              Unidades
              <input
                id="quantityInput"
                name="quantity"
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                required
                value={form.quantity}
                aria-invalid={invalid("quantity")}
                aria-describedby="quantityAvailable quantityWarning"
                onChange={(event) => {
                  clearApiQuantityError();
                  setForm((current) => ({ ...current, quantity: event.target.value }));
                }}
                className={`${INPUT_CLASS} md:w-60`}
              />
              <span
                id="quantityAvailable"
                aria-live="polite"
                className={`mt-1 block text-sm font-semibold ${available === null ? "text-slate-600" : stockLevel(available).text}`}
              >
                {available === null ? "" : `Disponible en ${warehouseName(form.warehouse)}: ${formatUnits(available)}`}
              </span>
              <p
                id="quantityWarning"
                role="status"
                hidden={!showWarning}
                className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900"
              >
                {showWarning && quantity !== null && available !== null
                  ? `Atención: quieres sacar ${formatUnits(quantity)}, pero solo hay ${formatUnits(available)} ` +
                    `en ${warehouseName(form.warehouse)}. Reduce la cantidad: la salida será rechazada.`
                  : ""}
              </p>
              <FieldError field="quantity" message={fieldErrors.quantity} />
            </label>
            <div className="flex flex-wrap items-center gap-3 md:col-span-2">
              <button id="submitButton" type="submit" disabled={submitting} className={SUBMIT_BUTTON_CLASS}>
                {submitting ? "Registrando…" : "Registrar salida"}
              </button>
              <Link href="/inventory/products" className="text-sm font-semibold text-cyan-800 underline-offset-4 hover:underline">
                Volver al stock
              </Link>
            </div>
          </form>
        </section>

        <aside className="self-start rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6" aria-labelledby="stock-title">
          <h2 id="stock-title" className="text-lg font-bold text-slate-900">Stock disponible</h2>
          <div id="stockPanel" data-status={stock.status} className="mt-3 text-sm text-slate-600" aria-live="polite">
            {stockPanel()}
          </div>
        </aside>
      </div>
    </main>
  );
}
