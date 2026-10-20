"use client";

import { STATUS_COLORS, Translate } from "../lib/incidents";

// Piezas de interfaz compartidas por el gestor (/incidents) y el registro (/incidents/new).

export function StatusBadge({ status, t, title }: { status: string; t: Translate; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex whitespace-nowrap rounded-full px-3 py-1 text-xs font-bold ring-1 ${STATUS_COLORS[status] || ""}`}
    >
      {t(`status.${status}`)}
    </span>
  );
}

/** Opciones de un <select> con los valores de un campo (y, opcionalmente, una opción vacía). */
export function FieldOptions({
  values,
  group,
  placeholderKey,
  t,
}: {
  values: readonly string[];
  group: string;
  placeholderKey?: string;
  t: Translate;
}) {
  return (
    <>
      {placeholderKey && <option value="">{t(placeholderKey)}</option>}
      {values.map((value) => (
        <option key={value} value={value}>
          {t(`${group}.${value}`)}
        </option>
      ))}
    </>
  );
}

export function Spinner({ className = "h-5 w-5 animate-spin", id }: { className?: string; id?: string }) {
  return (
    <svg id={id} className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4Z" />
    </svg>
  );
}

/** Botón "Reintentar" para los paneles que muestran su error en línea. */
export function InlineRetry({ onRetry, t }: { onRetry: () => void; t: Translate }) {
  return (
    <button
      type="button"
      onClick={onRetry}
      className="ml-1 min-h-11 rounded-lg border border-cyan-300 bg-white px-3 py-1 text-sm font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200"
    >
      {t("common.retry")}
    </button>
  );
}
