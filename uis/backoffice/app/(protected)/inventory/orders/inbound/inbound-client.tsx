"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";
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
  warehouseName,
} from "../../../../lib/inventory";
import { useApiResource } from "../../../../lib/use-api-resource";
import { Alert, AlertState, FieldError, INPUT_CLASS, SUBMIT_BUTTON_CLASS, SkuOptions, useFocusField } from "../../../../ui/inventory-ui";

// Recepción de mercancía — POST /inventory/orders/inbound (StockEntry).

type Form = { sku_id: string; warehouse: string; quantity: string; reference: string };
const EMPTY_FORM: Form = { sku_id: "", warehouse: "", quantity: "", reference: "" };
const FIELD_ORDER: Array<keyof Form> = ["sku_id", "warehouse", "quantity", "reference"];

function validate(form: Form): FieldErrors {
  const errors: FieldErrors = {};
  if (!form.sku_id) errors.sku_id = "Elige el SKU recibido.";
  if (!form.warehouse) errors.warehouse = "Elige el almacén que recibe la mercancía.";
  if (positiveInteger(form.quantity) === null) errors.quantity = "Introduce un número entero de unidades mayor que 0.";
  if (!form.reference.trim()) errors.reference = "Indica la referencia de despacho del cliente (p. ej. PO-2024-0098).";
  return errors;
}

export function InboundClient() {
  const searchParams = useSearchParams();
  const { formRef, focusField: setFocusField } = useFocusField();
  const [form, setForm] = useState<Form>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [alert, setAlert] = useState<AlertState>(null);
  const [submitting, setSubmitting] = useState(false);
  const {
    data: skus,
    setData: setSkus,
    loading: skusLoading,
  } = useApiResource(inventoryApi.listSkus, [] as Sku[], {
    key: searchParams.toString(),
    onLoaded: (list) => {
      // La fila del stock lleva ?sku_id=: se preselecciona ese SKU y su almacén.
      const preselected = list.find((sku) => String(sku.id) === searchParams.get("sku_id"));
      if (preselected) setForm((current) => ({ ...current, sku_id: String(preselected.id), warehouse: preselected.warehouse }));
      if (!list.length) setAlert({ type: "warning", message: "No hay SKUs registrados todavía: no se puede registrar ninguna entrada." });
    },
    onError: (error) => setAlert({ type: "error", message: `No se pudo cargar la lista de SKUs. ${errorMessage(error)}` }),
  });

  const selectedSku = skus.find((sku) => String(sku.id) === form.sku_id) ?? null;

  function hint() {
    if (!selectedSku) return "";
    const warehouse = form.warehouse || selectedSku.warehouse;
    const units = selectedSku.stock_by_warehouse[warehouse] ?? 0;
    let text = `Stock actual en ${warehouseName(warehouse)}: ${formatUnits(units)}.`;
    if (warehouse !== selectedSku.warehouse) {
      text += ` Este SKU está registrado en ${warehouseName(selectedSku.warehouse)}: la entrada sumará stock en ${warehouseName(warehouse)}.`;
    }
    return text;
  }

  function onSkuChange(skuId: string) {
    const sku = skus.find((item) => String(item.id) === skuId);
    // El almacén receptor por defecto es el del SKU; se puede cambiar si llega a otro almacén.
    setForm((current) => ({ ...current, sku_id: skuId, warehouse: sku ? sku.warehouse : current.warehouse }));
  }

  async function confirmation(entry: InventoryOrder) {
    const base =
      `Entrada registrada: ${formatUnits(entry.quantity)} de ${entry.sku.sku} (${entry.sku.name}) ` +
      `en ${warehouseName(entry.warehouse)}, ref. ${entry.reference}.`;
    try {
      const fresh = await inventoryApi.getSku(entry.sku_id);
      setSkus((current) => current.map((sku) => (sku.id === fresh.id ? fresh : sku)));
      return `${base} Stock actual en ${warehouseName(entry.warehouse)}: ${formatUnits(fresh.stock_by_warehouse[entry.warehouse])}.`;
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
      setFocusField(FIELD_ORDER.find((field) => errors[field]) ?? null);
      return;
    }

    setSubmitting(true);
    try {
      const entry = await inventoryApi.registerEntry({
        sku_id: Number(form.sku_id),
        quantity: positiveInteger(form.quantity) as number,
        reference: form.reference.trim(),
        warehouse: form.warehouse,
      });
      const message = await confirmation(entry);
      setForm(EMPTY_FORM);
      setAlert({ type: "success", message });
      setFocusField("sku_id");
    } catch (error) {
      if (error instanceof SessionExpiredError) return;
      const apiErrors = error instanceof InventoryApiError ? error.fieldErrors : {};
      // Los errores con campo en el formulario se pintan junto a él; el resto, en el aviso.
      const unplaced = Object.entries(apiErrors)
        .filter(([field]) => !FIELD_ORDER.includes(field as keyof Form))
        .map(([, message]) => message);
      setFieldErrors(apiErrors);
      setAlert({ type: "error", message: [`No se ha registrado la entrada. ${errorMessage(error)}`, ...unplaced].join(" ") });
    } finally {
      setSubmitting(false);
    }
  }

  function set(field: keyof Form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  const invalid = (field: string) => (fieldErrors[field] ? true : undefined);

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Inventario · Entrada de stock</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">Recepción de mercancía</h1>
        <p className="mt-3 max-w-3xl text-slate-600">
          Registra un envío recibido de una marca cliente. La entrada suma las unidades al stock del almacén receptor y queda a tu
          nombre.
        </p>
      </section>

      <section className="mt-6 max-w-3xl rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="form-title">
        <h2 id="form-title" className="text-xl font-bold text-slate-900">Nueva entrada de stock</h2>
        <Alert id="formAlert" alert={alert} role="status" wrapperClass="mt-4" />

        <form id="entryForm" ref={formRef} className="mt-5 grid gap-5 md:grid-cols-2" noValidate onSubmit={onSubmit}>
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
                onChange={(event) => onSkuChange(event.target.value)}
                className={INPUT_CLASS}
              >
                <SkuOptions skus={skus} />
              </select>
              <FieldError field="sku_id" message={fieldErrors.sku_id} />
            </label>
            <p id="skuHint" className="mt-1 text-sm text-slate-600" aria-live="polite">{hint()}</p>
          </div>
          <label className="block text-sm font-semibold text-slate-700">
            Almacén receptor
            <select
              id="warehouseInput"
              name="warehouse"
              required
              value={form.warehouse}
              aria-invalid={invalid("warehouse")}
              onChange={(event) => set("warehouse", event.target.value)}
              className={INPUT_CLASS}
            >
              <option value="">Selecciona un almacén…</option>
              <option value="LA">Los Ángeles (LA)</option>
              <option value="ZGZ">Zaragoza (ZGZ)</option>
            </select>
            <FieldError field="warehouse" message={fieldErrors.warehouse} />
          </label>
          <label className="block text-sm font-semibold text-slate-700">
            Unidades recibidas
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
              onChange={(event) => set("quantity", event.target.value)}
              className={INPUT_CLASS}
            />
            <FieldError field="quantity" message={fieldErrors.quantity} />
          </label>
          <label className="block text-sm font-semibold text-slate-700 md:col-span-2">
            Referencia de despacho del cliente
            <input
              id="referenceInput"
              name="reference"
              type="text"
              maxLength={64}
              required
              placeholder="Ej.: PO-2024-0098"
              autoComplete="off"
              value={form.reference}
              aria-invalid={invalid("reference")}
              onChange={(event) => set("reference", event.target.value)}
              className={INPUT_CLASS}
            />
            <span className="mt-1 block text-xs font-normal text-slate-500">Número de orden de compra o albarán de la marca cliente.</span>
            <FieldError field="reference" message={fieldErrors.reference} />
          </label>
          <div className="flex flex-wrap items-center gap-3 md:col-span-2">
            <button id="submitButton" type="submit" disabled={submitting} className={SUBMIT_BUTTON_CLASS}>
              {submitting ? "Registrando…" : "Registrar entrada"}
            </button>
            <Link href="/inventory/products" className="text-sm font-semibold text-cyan-800 underline-offset-4 hover:underline">
              Volver al stock
            </Link>
          </div>
        </form>
      </section>
    </main>
  );
}
