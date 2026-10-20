"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { SessionExpiredError } from "../../lib/auth";
import {
  CATEGORY_LABELS,
  CURRENCY_BY_COUNTRY,
  STATUS_LABELS,
  Supplier,
  SupplierDraft,
  SupplierStatus,
  VALID_CATEGORIES,
  formatDateTime,
  formatMoney,
  suppliersApi,
} from "../../lib/suppliers";
import { Spinner } from "../../ui/incidents-common";

type Message = { type: "success" | "error"; text: string };

const FIELD_CLASS =
  "mt-1 block w-full rounded-lg border border-cyan-200 px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200";

function messageClass(base: string, message: Message | null) {
  if (!message) return `${base} hidden rounded-xl border p-4 text-sm`;
  return `${base} rounded-xl border p-4 text-sm ${
    message.type === "error" ? "border-red-200 bg-red-50 font-semibold text-red-800" : "border-cyan-200 bg-cyan-50 text-cyan-900"
  }`;
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function StatusBadge({ status }: { status: string }) {
  const colors = status === "active" ? "bg-green-100 text-green-800 ring-green-200" : "bg-amber-100 text-amber-800 ring-amber-200";
  return <span className={`inline-flex rounded-full px-3 py-1 text-xs font-bold ring-1 ${colors}`}>{STATUS_LABELS[status] || status}</span>;
}

// Editor de tarifa en línea
function RateCell({ supplier, onUpdated }: { supplier: Supplier; onUpdated: (supplier: Supplier) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(String(supplier.rate_per_shipment));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const rate = Number(value);
    if (value.trim() === "" || !Number.isFinite(rate) || rate <= 0) {
      setError("La tarifa debe ser mayor que 0.");
      input.current?.focus();
      return;
    }
    setSaving(true);
    try {
      onUpdated(await suppliersApi.updateRate(supplier.id, rate));
    } catch (requestError) {
      if (requestError instanceof SessionExpiredError) return;
      setError(errorText(requestError));
      setSaving(false);
    }
  }

  return (
    <td className="py-4 pr-4 align-top">
      <p className="font-bold text-slate-900">{formatMoney(supplier.rate_per_shipment, supplier.currency)}</p>
      <form className="mt-2 flex items-center gap-2" noValidate onSubmit={onSubmit}>
        <input
          ref={input}
          type="number"
          min="0.01"
          step="0.01"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          aria-label={`Nueva tarifa para ${supplier.name}`}
          className="w-24 rounded-lg border border-cyan-200 px-2 py-1 text-sm focus:border-cyan-500 focus:outline-none focus:ring-2 focus:ring-cyan-200"
        />
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg border border-cyan-300 bg-white px-2 py-1 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 disabled:cursor-not-allowed disabled:text-slate-400"
        >
          {saving ? "Guardando..." : "Guardar"}
        </button>
      </form>
      <p role="alert" className={`mt-1 text-xs font-semibold text-red-700 ${error ? "" : "hidden"}`}>
        {error ?? ""}
      </p>
    </td>
  );
}

function ActionsCell({ supplier, onUpdated }: { supplier: Supplier; onUpdated: (supplier: Supplier) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isActive = supplier.status === "active";
  const nextStatus: SupplierStatus = isActive ? "suspended" : "active";

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      onUpdated(await suppliersApi.updateStatus(supplier.id, nextStatus));
    } catch (requestError) {
      if (requestError instanceof SessionExpiredError) return;
      setError(errorText(requestError));
      setBusy(false);
    }
  }

  return (
    <td className="py-4 align-top text-right">
      <button
        type="button"
        disabled={busy}
        onClick={onClick}
        className={`whitespace-nowrap rounded-lg border px-3 py-2 text-xs font-bold transition disabled:cursor-not-allowed disabled:opacity-60 ${
          isActive ? "border-amber-300 bg-white text-amber-800 hover:bg-amber-50" : "border-green-300 bg-white text-green-800 hover:bg-green-50"
        }`}
      >
        {isActive ? "Suspender" : "Reactivar"}
      </button>
      <p role="alert" className={`mt-1 text-xs font-semibold text-red-700 ${error ? "" : "hidden"}`}>
        {error ?? ""}
      </p>
    </td>
  );
}

type CreateForm = {
  name: string;
  country: string;
  categories: string[];
  rate: string;
  status: SupplierStatus;
  service_zone: string;
  contact_email: string;
  notes: string;
};

const EMPTY_FORM: CreateForm = {
  name: "",
  country: "",
  categories: [],
  rate: "",
  status: "active",
  service_zone: "",
  contact_email: "",
  notes: "",
};

const optional = (value: string) => (value.trim() === "" ? null : value.trim());

// Validación en cliente; devuelve la lista de errores
function validateCreateForm(data: SupplierDraft): string[] {
  const errors: string[] = [];
  if (!data.name) errors.push("El nombre es obligatorio.");
  if (!CURRENCY_BY_COUNTRY[data.country]) errors.push("Selecciona un país.");
  if (data.categories.length === 0) errors.push("Selecciona al menos una categoría.");
  if (!Number.isFinite(data.rate_per_shipment) || data.rate_per_shipment <= 0) errors.push("La tarifa debe ser mayor que 0.");
  return errors;
}

export function SuppliersClient() {
  const [countryFilter, setCountryFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [creating, setCreating] = useState(false);
  const [createMessage, setCreateMessage] = useState<Message | null>(null);
  // Cada reintento o alta vuelve a pedir el listado con los filtros actuales.
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    suppliersApi
      .list(countryFilter, categoryFilter)
      .then((list) => {
        if (!cancelled) setSuppliers(list);
      })
      .catch((error) => {
        if (cancelled || error instanceof SessionExpiredError) return;
        setSuppliers(null);
        setListError(errorText(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [countryFilter, categoryFilter, refreshTick]);

  function loadSuppliers() {
    setListError(null);
    setLoading(true);
    setRefreshTick((tick) => tick + 1);
  }

  function changeFilter(set: (value: string) => void, value: string) {
    set(value);
    setListError(null);
    setLoading(true);
  }

  // Sustituye un proveedor en la lista local (sin recargar la página)
  function replaceSupplier(updated: Supplier) {
    setSuppliers((current) => (current ? current.map((supplier) => (supplier.id === updated.id ? updated : supplier)) : current));
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateMessage(null);

    const rateText = form.rate.trim();
    const data: SupplierDraft = {
      name: form.name.trim(),
      country: form.country,
      categories: form.categories,
      rate_per_shipment: rateText === "" ? NaN : Number(rateText),
      currency: CURRENCY_BY_COUNTRY[form.country],
      status: form.status,
      service_zone: optional(form.service_zone),
      contact_email: optional(form.contact_email),
      notes: optional(form.notes),
    };

    const errors = validateCreateForm(data);
    if (errors.length > 0) {
      setCreateMessage({ type: "error", text: errors.join(" ") });
      return;
    }

    setCreating(true);
    try {
      const created = await suppliersApi.create(data);
      setForm(EMPTY_FORM);
      setCreateMessage({ type: "success", text: `Proveedor "${created.name}" registrado con id ${created.id}.` });
      loadSuppliers();
    } catch (error) {
      if (error instanceof SessionExpiredError) return;
      setCreateMessage({ type: "error", text: errorText(error) });
    } finally {
      setCreating(false);
    }
  }

  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) => setForm((current) => ({ ...current, [key]: value }));

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-12">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Carrier &amp; Warehouse Operations</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">
          Directorio de proveedores
        </h1>
        <p className="mt-3 max-w-2xl text-slate-600">
          Proveedores de Los Ángeles y Zaragoza en un único registro: tarifas, categorías y estado.
        </p>
      </section>

      {/* LISTADO */}
      <section className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="list-title">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 id="list-title" className="text-xl font-bold text-slate-900">Proveedores</h2>
            <p id="resultsCount" className="mt-1 text-sm text-slate-600" aria-live="polite">
              {suppliers ? `${suppliers.length} ${suppliers.length === 1 ? "proveedor" : "proveedores"}` : ""}
            </p>
          </div>

          <form id="filtersForm" className="flex flex-col gap-3 sm:flex-row sm:items-end" onSubmit={(event) => event.preventDefault()}>
            <label className="text-sm font-semibold text-slate-700">
              País
              <select
                id="countryFilter"
                name="country"
                value={countryFilter}
                onChange={(event) => changeFilter(setCountryFilter, event.target.value)}
                className="mt-1 block w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200 sm:w-40"
              >
                <option value="">Todos</option>
                <option value="USA">USA</option>
                <option value="Spain">Spain</option>
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">
              Categoría
              <select
                id="categoryFilter"
                name="category"
                value={categoryFilter}
                onChange={(event) => changeFilter(setCategoryFilter, event.target.value)}
                className="mt-1 block w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200 sm:w-56"
              >
                <option value="">Todas</option>
                {VALID_CATEGORIES.map((category) => (
                  <option key={category} value={category}>
                    {CATEGORY_LABELS[category]}
                  </option>
                ))}
              </select>
            </label>
          </form>
        </div>

        <div id="listMessage" role="status" aria-live="polite" className={messageClass("mt-5", listError ? { type: "error", text: listError } : null)}>
          {listError && (
            <>
              {`${listError} `}
              <button
                type="button"
                onClick={loadSuppliers}
                className="ml-2 rounded-lg border border-red-300 bg-white px-3 py-1 font-bold text-red-800 transition hover:bg-red-100 focus:outline-none focus:ring-4 focus:ring-red-200"
              >
                Reintentar
              </button>
            </>
          )}
        </div>

        <div
          id="listLoading"
          role="status"
          className={`mt-5 items-center gap-3 rounded-xl border border-cyan-100 bg-cyan-50 p-4 text-sm text-cyan-900 ${loading ? "flex" : "hidden"}`}
        >
          <Spinner />
          Cargando proveedores...
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-cyan-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="py-3 pr-4">Proveedor</th>
                <th scope="col" className="py-3 pr-4">Categorías</th>
                <th scope="col" className="py-3 pr-4">Tarifa por envío</th>
                <th scope="col" className="py-3 pr-4">Estado</th>
                <th scope="col" className="py-3 pr-4">Última tarifa</th>
                <th scope="col" className="py-3">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody id="suppliersTableBody" className="divide-y divide-cyan-100">
              {suppliers && suppliers.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-slate-600">No hay proveedores con estos filtros.</td>
                </tr>
              )}
              {suppliers?.map((supplier) => (
                // La clave incluye los datos editables: tras cualquier cambio (tarifa o estado) la fila
                // se vuelve a crear con sus controles en el estado inicial, como al repintar la tabla.
                <tr
                  key={`${supplier.id}-${supplier.updated_at}-${supplier.status}-${supplier.rate_per_shipment}`}
                  data-id={supplier.id}
                >
                  <td className="py-4 pr-4 align-top">
                    <p className="font-bold text-slate-900">{supplier.name}</p>
                    <p className="text-xs text-slate-500">{[supplier.country, supplier.service_zone].filter(Boolean).join(" · ")}</p>
                    {supplier.contact_email && <p className="text-xs text-slate-500">{supplier.contact_email}</p>}
                    {supplier.notes && <p className="mt-1 max-w-xs text-xs italic text-slate-500">{supplier.notes}</p>}
                  </td>
                  <td className="py-4 pr-4 align-top">
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {supplier.categories.map((category) => (
                        <span key={category} title={category} className="rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-semibold text-cyan-800">
                          {CATEGORY_LABELS[category] || category}
                        </span>
                      ))}
                    </div>
                  </td>
                  <RateCell supplier={supplier} onUpdated={replaceSupplier} />
                  <td className="py-4 pr-4 align-top">
                    <StatusBadge status={supplier.status} />
                  </td>
                  <td className="whitespace-nowrap py-4 pr-4 align-top text-xs text-slate-500">{formatDateTime(supplier.updated_at)}</td>
                  <ActionsCell supplier={supplier} onUpdated={replaceSupplier} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ALTA */}
      <section className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="create-title">
        <div className="mb-5">
          <h2 id="create-title" className="text-xl font-bold text-slate-900">Registrar proveedor</h2>
          <p className="mt-1 text-sm text-slate-600">La moneda se asigna según el país del contrato.</p>
        </div>

        <form id="createForm" noValidate className="grid gap-4 md:grid-cols-2" onSubmit={onCreate}>
          <label className="text-sm font-semibold text-slate-700">
            Nombre *
            <input id="nameInput" name="name" type="text" required value={form.name} onChange={(event) => set("name", event.target.value)} className={FIELD_CLASS} />
          </label>

          <div className="grid grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-slate-700">
              País *
              <select
                id="countryInput"
                name="country"
                required
                value={form.country}
                onChange={(event) => set("country", event.target.value)}
                className="mt-1 block w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200"
              >
                <option value="">Selecciona...</option>
                <option value="USA">USA</option>
                <option value="Spain">Spain</option>
              </select>
            </label>
            <label className="text-sm font-semibold text-slate-700">
              Moneda
              <input
                id="currencyInput"
                name="currency"
                type="text"
                readOnly
                tabIndex={-1}
                placeholder="—"
                value={CURRENCY_BY_COUNTRY[form.country] || ""}
                className="mt-1 block w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-normal text-slate-600"
              />
            </label>
          </div>

          <fieldset className="md:col-span-2">
            <legend className="text-sm font-semibold text-slate-700">
              Categorías * <span className="font-normal text-slate-500">(al menos una)</span>
            </legend>
            <div id="categoriesInput" className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {VALID_CATEGORIES.map((category) => (
                <label key={category} className="flex items-center gap-2 rounded-lg border border-cyan-100 px-3 py-2 text-sm text-slate-700 hover:bg-cyan-50">
                  <input
                    className="h-4 w-4 accent-cyan-700"
                    type="checkbox"
                    name="categories"
                    value={category}
                    checked={form.categories.includes(category)}
                    onChange={(event) =>
                      set(
                        "categories",
                        event.target.checked ? [...form.categories, category] : form.categories.filter((item) => item !== category),
                      )
                    }
                  />
                  {CATEGORY_LABELS[category]}
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-slate-700">
              Tarifa por envío *
              <input
                id="rateInput"
                name="rate_per_shipment"
                type="number"
                min="0.01"
                step="0.01"
                required
                value={form.rate}
                onChange={(event) => set("rate", event.target.value)}
                className={FIELD_CLASS}
              />
            </label>
            <label className="text-sm font-semibold text-slate-700">
              Estado *
              <select
                id="statusInput"
                name="status"
                required
                value={form.status}
                onChange={(event) => set("status", event.target.value as SupplierStatus)}
                className="mt-1 block w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200"
              >
                <option value="active">Activo</option>
                <option value="suspended">Suspendido</option>
              </select>
            </label>
          </div>

          <label className="text-sm font-semibold text-slate-700">
            Zona de servicio
            <input
              id="serviceZoneInput"
              name="service_zone"
              type="text"
              placeholder="West Coast, Aragón..."
              value={form.service_zone}
              onChange={(event) => set("service_zone", event.target.value)}
              className={FIELD_CLASS}
            />
          </label>

          <label className="text-sm font-semibold text-slate-700">
            Email de contacto
            <input
              id="contactEmailInput"
              name="contact_email"
              type="email"
              value={form.contact_email}
              onChange={(event) => set("contact_email", event.target.value)}
              className={FIELD_CLASS}
            />
          </label>

          <label className="text-sm font-semibold text-slate-700">
            Notas
            <textarea id="notesInput" name="notes" rows={2} value={form.notes} onChange={(event) => set("notes", event.target.value)} className={FIELD_CLASS} />
          </label>

          <div className="md:col-span-2">
            <div id="createMessage" role="status" aria-live="polite" className={messageClass("mb-4", createMessage)}>
              {createMessage?.text ?? ""}
            </div>
            <button
              id="createButton"
              type="submit"
              disabled={creating}
              className="inline-flex items-center justify-center rounded-lg bg-cyan-700 px-5 py-3 font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {creating ? "Registrando..." : "Registrar proveedor"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
