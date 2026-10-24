"use client";

import { ReactNode, useMemo, useRef } from "react";
import { Sku, WAREHOUSE_NAMES, formatUnits, skuOptionLabel, stockLevel, warehouseName } from "../lib/inventory";

// Piezas de interfaz compartidas por las pantallas de inventario. No hacen peticiones.

/** Etiqueta de color con el stock (o, con showLevel, con el nivel: "Stock bajo"…). */
export function StockBadge({ units, showLevel = false }: { units: number; showLevel?: boolean }) {
  const level = stockLevel(units);
  return (
    <span
      data-level={level.key}
      title={level.label}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-sm font-bold ${level.badge}`}
    >
      <span>{level.icon}</span>
      <span>{showLevel ? level.label : formatUnits(units)}</span>
    </span>
  );
}

export type AlertType = "success" | "error" | "warning" | "info";
export type AlertState = { type: AlertType; message: string } | null;

const ALERT_STYLES: Record<AlertType, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  error: "border-red-200 bg-red-50 text-red-700",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-cyan-200 bg-cyan-50 text-cyan-900",
};

export function Alert({ id, alert, role = "alert", wrapperClass }: { id: string; alert: AlertState; role?: string; wrapperClass: string }) {
  return (
    <div
      id={id}
      role={role}
      aria-live={role === "status" ? "polite" : undefined}
      data-type={alert?.type}
      hidden={!alert}
      className={alert ? `${wrapperClass} rounded-xl border p-4 text-sm ${ALERT_STYLES[alert.type]}` : wrapperClass}
    >
      {alert?.message ?? ""}
    </div>
  );
}

/** Ref del formulario y función que lleva el foco a un campo (por `name`) cuando React ya ha pintado los errores. */
export function useFocusField() {
  const formRef = useRef<HTMLFormElement>(null);
  function focusField(field: string | null | undefined) {
    if (!field) return;
    window.setTimeout(() => formRef.current?.querySelector<HTMLElement>(`[name="${field}"]`)?.focus(), 0);
  }
  return { formRef, focusField };
}

/** Error de un campo: <p data-error-for="campo"> debajo del input. */
export function FieldError({ field, message }: { field: string; message?: string }) {
  return (
    <p data-error-for={field} hidden={!message} className="mt-1 text-sm font-semibold text-red-700">
      {message ?? ""}
    </p>
  );
}

/** Opciones del selector de SKU: por nombre, agrupadas por almacén. */
export function SkuOptions({ skus }: { skus: Sku[] }) {
  // Ordenar ~760 SKUs con localeCompare("es") y montar sus <option> cuesta ~1,5 ms, y el
  // formulario que lo contiene se vuelve a pintar con cada tecla. `skus` es el estado de
  // useApiResource: solo cambia al recargar el catálogo, y solo entonces se recalcula.
  const groups = useMemo(() => {
    const sorted = [...skus].sort((a, b) => a.name.localeCompare(b.name, "es") || a.sku.localeCompare(b.sku));
    const result: ReactNode[] = [];
    for (const code of Object.keys(WAREHOUSE_NAMES)) {
      const items = sorted.filter((item) => item.warehouse === code);
      if (!items.length) continue;
      result.push(
        <optgroup key={code} label={`Almacén ${warehouseName(code)}`}>
          {items.map((sku) => (
            <option key={sku.id} value={String(sku.id)}>
              {skuOptionLabel(sku)}
            </option>
          ))}
        </optgroup>,
      );
    }
    return result;
  }, [skus]);
  return (
    <>
      <option value="">Selecciona un SKU…</option>
      {groups}
    </>
  );
}

export const INPUT_CLASS =
  "mt-1 block w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200 aria-[invalid=true]:border-red-400 aria-[invalid=true]:ring-red-100";

export const REFRESH_BUTTON_CLASS =
  "inline-flex items-center justify-center rounded-lg border border-cyan-300 bg-white px-4 py-2 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:opacity-60";

export const SUBMIT_BUTTON_CLASS =
  "inline-flex items-center justify-center rounded-lg bg-cyan-700 px-5 py-3 font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-300";
