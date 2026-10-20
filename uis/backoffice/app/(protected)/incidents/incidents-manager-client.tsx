"use client";

import Link from "next/link";
import { FormEvent, Fragment, useCallback, useEffect, useRef, useState } from "react";
import { SessionExpiredError } from "../../lib/auth";
import {
  BRANCHES,
  CATEGORIES,
  DuplicateGroup,
  Filters,
  Incident,
  IncidentStatus,
  IncidentsApiError,
  ORIGINS,
  SLA_CATEGORIES,
  STATUSES,
  STATUS_COLORS,
  STATUS_TRANSITIONS,
  SimilarIncident,
  Summary,
  Translate,
  errorMessage,
  formatDate,
  incidentsApi,
} from "../../lib/incidents";
import { FieldOptions, InlineRetry, Spinner, StatusBadge } from "../../ui/incidents-common";
import { useDocumentLang, useIncidentsLang } from "../../ui/incidents-lang";

// Panel de resumen, posibles duplicados y listado del gestor de incidencias.
// Cada bloque carga por separado: si uno falla, los demás siguen funcionando.

type LoadState = "loading" | "error" | "ready";
type FilterField = keyof Filters;
// Aviso del último cambio de estado: con `key` se vuelve a traducir al cambiar de idioma;
// el aviso de fallo guarda el texto ya compuesto (como antes, no se retraduce).
type Notice = { type: "success" | "error"; key?: string; params?: Record<string, string | number>; text?: string };

const EMPTY_FILTERS: Filters = { status: "", origin: "", branch: "", category: "" };

const SELECT_CLASS =
  "mt-1 block min-h-12 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-base font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200";
const RETRY_CLASS =
  "shrink-0 rounded-lg border border-red-300 bg-white px-4 py-2 font-bold text-red-800 transition hover:bg-red-100 focus:outline-none focus:ring-4 focus:ring-red-200";

function scrollToList() {
  document.querySelector("#list-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// =========================================================
// RESUMEN
// =========================================================

function Breakdown({
  id,
  field,
  values,
  counts,
  t,
  onFilter,
}: {
  id: string;
  field: FilterField;
  values: readonly string[];
  counts: Record<string, number>;
  t: Translate;
  onFilter: (field: FilterField, value: string) => void;
}) {
  const max = Math.max(1, ...values.map((value) => counts[value] || 0));
  return (
    <div id={id} className="mt-2 divide-y divide-cyan-100">
      {values.map((value) => {
        const count = counts[value] || 0;
        const label = t(`${field}.${value}`);
        // Cada fila filtra el listado por ese valor.
        return (
          <button
            key={value}
            type="button"
            title={t("summary.filterBy", { label })}
            onClick={() => onFilter(field, value)}
            className="flex min-h-11 w-full items-center gap-3 py-2 text-left transition hover:bg-cyan-50 focus:outline-none focus:ring-2 focus:ring-cyan-300"
          >
            <span className="flex w-1/2 shrink-0 items-center gap-2 text-sm font-medium text-slate-700">
              {label}
              {field === "category" && SLA_CATEGORIES.includes(value) && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900">{t("common.sla")}</span>
              )}
            </span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-cyan-50">
              <span className="block h-full rounded-full bg-cyan-600" style={{ width: `${(count / max) * 100}%` }} />
            </span>
            <span className="w-10 shrink-0 text-right text-sm font-bold text-slate-900">{String(count)}</span>
          </button>
        );
      })}
    </div>
  );
}

// =========================================================
// LISTADO: estado y casos similares de cada incidencia
// =========================================================

function statusSelectClass(status: string) {
  return `min-h-11 w-full min-w-36 rounded-lg px-3 py-2 text-sm font-bold ring-1 focus:outline-none focus:ring-4 disabled:cursor-not-allowed disabled:opacity-70 ${STATUS_COLORS[status]}`;
}

function StatusCell({
  incident,
  t,
  onChange,
}: {
  incident: Incident;
  t: Translate;
  /** Devuelve true si el cambio se ha guardado. */
  onChange: (incident: Incident, next: IncidentStatus) => Promise<boolean>;
}) {
  const [value, setValue] = useState<IncidentStatus>(incident.status);
  const [saving, setSaving] = useState(false);
  const transitions = STATUS_TRANSITIONS[incident.status];

  // Estado final: no hay nada que cambiar.
  if (transitions.length === 0) {
    return (
      <td className="py-4 pr-4 align-top">
        <StatusBadge status={incident.status} t={t} title={t("list.finalStatus")} />
      </td>
    );
  }

  return (
    <td className="py-4 pr-4 align-top">
      <select
        aria-label={t("list.changeStatus", { id: incident.id })}
        value={value}
        disabled={saving}
        className={statusSelectClass(value)}
        onChange={async (event) => {
          const next = event.target.value as IncidentStatus;
          // Cambio optimista: el estado se ve aplicado mientras la petición está en curso.
          setValue(next);
          setSaving(true);
          const saved = await onChange(incident, next);
          if (!saved) {
            // Fallo: el estado visual vuelve al valor anterior.
            setValue(incident.status);
            setSaving(false);
          }
        }}
      >
        {[incident.status, ...transitions].map((status) => (
          <option key={status} value={status}>
            {t(`status.${status}`)}
          </option>
        ))}
      </select>
    </td>
  );
}

function SimilarRow({ incident, t, lang }: { incident: Incident; t: Translate; lang: "es" | "en" }) {
  const [state, setState] = useState<{ status: LoadState; items: SimilarIncident[] }>({ status: "loading", items: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    incidentsApi
      .similar(incident.id)
      .then((items) => {
        if (!cancelled) setState({ status: "ready", items });
      })
      .catch((error) => {
        if (!cancelled && !(error instanceof SessionExpiredError)) setState({ status: "error", items: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [incident.id, attempt]);

  return (
    <tr className="bg-cyan-50">
      <td className="px-4 py-4" colSpan={6}>
        <p className="text-xs font-bold uppercase tracking-wide text-cyan-800">{t("list.similarTitle")}</p>
        <div className="mt-2 text-sm text-slate-700">
          {state.status === "loading" && t("list.similarLoading")}
          {state.status === "error" && (
            <>
              {t("list.similarError")}{" "}
              <InlineRetry
                t={t}
                onRetry={() => {
                  setState({ status: "loading", items: [] });
                  setAttempt((n) => n + 1);
                }}
              />
            </>
          )}
          {state.status === "ready" && state.items.length === 0 && t("list.similarEmpty")}
          {state.status === "ready" && state.items.length > 0 && (
            <ul className="space-y-2">
              {state.items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-bold text-slate-900">{`#${item.id}`}</span>
                  <span className="text-slate-800">{item.title}</span>
                  <StatusBadge status={item.status} t={t} />
                  <span className="text-xs text-slate-500">{t("list.match", { n: Math.round(item.score * 100) })}</span>
                  <span className="text-xs text-slate-500">{`${t(`branch.${item.branch}`)} · ${formatDate(lang, item.created_at)}`}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </td>
    </tr>
  );
}

// =========================================================
// PANTALLA
// =========================================================

export function IncidentsManagerClient() {
  const { lang, t } = useIncidentsLang();
  useDocumentLang(lang);

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  // Cada búsqueda, filtro o reintento vuelve a pedir el listado (aunque el valor no cambie).
  const [listTick, setListTick] = useState(0);

  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryState, setSummaryState] = useState<LoadState>("loading");
  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [duplicatesState, setDuplicatesState] = useState<LoadState>("loading");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [listState, setListState] = useState<LoadState>("loading");
  const [listErrorKey, setListErrorKey] = useState("list.error");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  // true si el servidor busca en modo básico porque el modelo de embeddings no ha cargado
  const [semanticDegraded, setSemanticDegraded] = useState(false);
  const listRequestId = useRef(0);
  const summaryLoaded = useRef(false);

  // Las funciones fetch* piden los datos y solo cambian el estado al llegar la respuesta; las
  // load* además muestran antes el "cargando" (para los reintentos y las recargas).
  const fetchSummary = useCallback(
    () =>
      incidentsApi
        .summary()
        .then((data) => {
          summaryLoaded.current = true;
          setSummary(data);
          setSummaryState("ready");
        })
        .catch((error) => {
          if (error instanceof SessionExpiredError) return;
          summaryLoaded.current = false;
          setSummary(null);
          setSummaryState("error");
        }),
    [],
  );

  const loadSummary = useCallback(() => {
    // En las recargas tras un cambio de estado no se oculta el resumen ya pintado.
    if (!summaryLoaded.current) setSummaryState("loading");
    fetchSummary();
  }, [fetchSummary]);

  const fetchDuplicates = useCallback(
    () =>
      incidentsApi
        .duplicates()
        .then((groups) => {
          setDuplicates(groups);
          setDuplicatesState("ready");
        })
        .catch((error) => {
          if (error instanceof SessionExpiredError) return;
          setDuplicatesState("error");
        }),
    [],
  );

  const loadDuplicates = useCallback(() => {
    setDuplicatesState((current) => (current === "error" ? "loading" : current));
    fetchDuplicates();
  }, [fetchDuplicates]);

  useEffect(() => {
    // El estado inicial ya es "cargando": aquí solo se piden los datos.
    fetchSummary();
    fetchDuplicates();
    // Aviso informativo: si no se puede consultar, la página funciona igual sin él.
    incidentsApi
      .semanticStatus()
      .then((status) => setSemanticDegraded(status.degraded === true))
      .catch(() => setSemanticDegraded(false));
  }, [fetchSummary, fetchDuplicates]);

  // Pide el listado con los filtros y la búsqueda actuales. El "cargando" lo pone reloadList.
  useEffect(() => {
    const requestId = ++listRequestId.current;
    (activeSearch ? incidentsApi.search(activeSearch, filters) : incidentsApi.list(filters))
      .then((result) => {
        // Si el usuario ha cambiado los filtros mientras tanto, esta respuesta ya no vale.
        if (requestId !== listRequestId.current) return;
        setIncidents(result);
        setListState("ready");
      })
      .catch((error) => {
        if (error instanceof SessionExpiredError || requestId !== listRequestId.current) return;
        setIncidents([]);
        setListState("error");
        setListErrorKey(activeSearch && error instanceof IncidentsApiError && error.status === 503 ? "list.searchError" : "list.error");
      });
  }, [filters, activeSearch, listTick]);

  function reloadList() {
    setListState("loading");
    setNotice(null);
    setExpanded(new Set());
    setListTick((tick) => tick + 1);
  }

  function setFilter(field: FilterField, value: string) {
    setFilters((current) => ({ ...current, [field]: value }));
    reloadList();
  }

  function runSearch(query: string) {
    setActiveSearch(query.trim());
    reloadList();
  }

  async function changeStatus(incident: Incident, next: IncidentStatus): Promise<boolean> {
    setNotice(null);
    try {
      const updated = await incidentsApi.updateStatus(incident.id, next);
      setIncidents((current) => current.map((item) => (item.id === updated.id ? { ...item, ...updated } : item)));
      setExpanded(new Set());
      setNotice({ type: "success", key: "list.statusUpdated", params: { id: updated.id, status: `status.${updated.status}` } });
      loadSummary();
      loadDuplicates();
      return true;
    } catch (error) {
      if (error instanceof SessionExpiredError) return false;
      // Fallo: el estado visual vuelve al valor anterior y se avisa al usuario.
      setNotice({ type: "error", text: `${t("list.statusFailed", { id: incident.id })} ${errorMessage(lang, error)}` });
      return false;
    }
  }

  function toggleSimilar(id: number) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const noticeText = notice
    ? notice.text ??
      t(notice.key ?? "", {
        ...notice.params,
        // El estado del aviso de éxito se traduce en el idioma actual.
        ...(notice.params?.status ? { status: t(String(notice.params.status)) } : {}),
      })
    : "";

  const isReady = listState === "ready";
  const isEmpty = isReady && incidents.length === 0;
  const hasFilters = Object.values(filters).some(Boolean);
  const searchNotes: string[] = [];
  if (activeSearch !== "" && isReady) searchNotes.push(t("list.searchInfo", { q: activeSearch }));
  if (semanticDegraded) searchNotes.push(t("list.searchDegraded"));

  const filterSelects: Array<{ field: FilterField; id: string; values: readonly string[]; label: string; placeholder: string }> = [
    { field: "status", id: "statusFilter", values: STATUSES, label: "field.status", placeholder: "common.all" },
    { field: "origin", id: "originFilter", values: ORIGINS, label: "field.origin", placeholder: "common.all" },
    { field: "branch", id: "branchFilter", values: BRANCHES, label: "field.branch", placeholder: "common.allFem" },
    { field: "category", id: "categoryFilter", values: CATEGORIES, label: "field.category", placeholder: "common.allFem" },
  ];

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-12">
      <section aria-labelledby="page-title" className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">{t("manager.eyebrow")}</p>
          <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">
            {t("manager.title")}
          </h1>
          <p className="mt-3 max-w-2xl text-slate-600">{t("manager.intro")}</p>
        </div>
        <Link
          href="/incidents/new"
          className="inline-flex shrink-0 items-center justify-center rounded-lg bg-cyan-700 px-5 py-3 font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200"
        >
          {t("manager.newButton")}
        </Link>
      </section>

      {/* RESUMEN */}
      <section id="summarySection" className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="summary-title">
        <h2 id="summary-title" className="text-xl font-bold text-slate-900">{t("summary.title")}</h2>

        <div
          id="summaryLoading"
          role="status"
          className={`mt-5 items-center gap-3 rounded-xl border border-cyan-100 bg-cyan-50 p-4 text-sm text-cyan-900 ${summaryState === "loading" ? "flex" : "hidden"}`}
        >
          <Spinner />
          <span>{t("summary.loading")}</span>
        </div>

        <div
          id="summaryError"
          role="alert"
          className={`mt-5 flex-col gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800 sm:flex-row sm:items-center sm:justify-between ${summaryState === "error" ? "flex" : "hidden"}`}
        >
          <span id="summaryErrorText">{summaryState === "error" ? t("summary.error") : ""}</span>
          <button
            id="summaryRetry"
            type="button"
            className={RETRY_CLASS}
            onClick={() => {
              summaryLoaded.current = false;
              loadSummary();
            }}
          >
            {t("common.retry")}
          </button>
        </div>

        <div id="summaryContent" className={summaryState === "ready" ? "block" : "hidden"}>
          {summary && (
            <>
              <div className="mt-5 grid gap-4 sm:grid-cols-3">
                <article className="rounded-2xl border border-cyan-200 bg-cyan-50 p-5">
                  <p className="text-sm font-semibold text-slate-600">{t("summary.total")}</p>
                  <p id="summaryTotal" className="mt-2 text-3xl font-black text-cyan-700">{String(summary.total)}</p>
                </article>
                <article className="rounded-2xl border border-cyan-200 bg-white p-5">
                  <p className="text-sm font-semibold text-slate-600">{t("summary.active")}</p>
                  <p id="summaryActive" className="mt-2 text-3xl font-black text-slate-900">
                    {String(summary.by_status.open + summary.by_status.in_progress)}
                  </p>
                </article>
                <article className="rounded-2xl border border-cyan-200 bg-white p-5">
                  <p className="text-sm font-semibold text-slate-600">{t("summary.sla")}</p>
                  <p id="summarySla" className="mt-2 text-3xl font-black text-slate-900">
                    {String(SLA_CATEGORIES.reduce((total, category) => total + (summary.by_category[category] || 0), 0))}
                  </p>
                </article>
              </div>

              <div className="mt-6 grid gap-6 md:grid-cols-2">
                {(
                  [
                    ["by-status-title", "summary.byStatus", "summaryByStatus", "status", STATUSES, summary.by_status],
                    ["by-origin-title", "summary.byOrigin", "summaryByOrigin", "origin", ORIGINS, summary.by_origin],
                    ["by-category-title", "summary.byCategory", "summaryByCategory", "category", CATEGORIES, summary.by_category],
                    ["by-branch-title", "summary.byBranch", "summaryByBranch", "branch", BRANCHES, summary.by_branch],
                  ] as const
                ).map(([titleId, titleKey, listId, field, values, counts]) => (
                  <section key={listId} aria-labelledby={titleId}>
                    <h3 id={titleId} className="text-lg font-bold text-slate-900">{t(titleKey)}</h3>
                    <Breakdown
                      id={listId}
                      field={field}
                      values={values}
                      counts={counts}
                      t={t}
                      onFilter={(f, value) => {
                        setFilter(f, value);
                        scrollToList();
                      }}
                    />
                  </section>
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      {/* POSIBLES DUPLICADOS (embeddings) */}
      <section className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="duplicates-title">
        <h2 id="duplicates-title" className="text-xl font-bold text-slate-900">{t("duplicates.title")}</h2>
        <p className="mt-1 text-sm text-slate-600">{t("duplicates.intro")}</p>
        {duplicatesState === "ready" && duplicates.length > 0 ? (
          <ul id="duplicatesList" className="mt-4 block space-y-3">
            {duplicates.map((group) => (
              <li
                key={group.incident_ids.join("-")}
                className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="font-bold text-slate-900">{group.title}</p>
                  <p className="mt-1 text-sm text-slate-700">
                    {[
                      t("duplicates.count", { n: group.size }),
                      t(`category.${group.category}`),
                      group.branches.map((branch) => t(`branch.${branch}`)).join(", "),
                      group.incident_ids.map((id) => `#${id}`).join(" "),
                    ].join(" · ")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput(group.title);
                    runSearch(group.title);
                    scrollToList();
                  }}
                  className="min-h-11 shrink-0 rounded-lg border border-amber-400 bg-white px-4 py-2 text-sm font-bold text-amber-900 transition hover:bg-amber-100 focus:outline-none focus:ring-4 focus:ring-amber-200"
                >
                  {t("duplicates.view")}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div id="duplicatesState" role="status" className="mt-4 block rounded-xl border border-cyan-100 bg-cyan-50 p-4 text-sm text-cyan-900">
            {t({ loading: "duplicates.loading", error: "duplicates.error", ready: "duplicates.empty" }[duplicatesState])}
            {duplicatesState === "error" && (
              <>
                {" "}
                <InlineRetry t={t} onRetry={loadDuplicates} />
              </>
            )}
          </div>
        )}
      </section>

      {/* LISTADO */}
      <section className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="list-title">
        <div>
          <h2 id="list-title" className="text-xl font-bold text-slate-900">{t("list.title")}</h2>
          <p id="resultsCount" className="mt-1 text-sm text-slate-600" aria-live="polite">
            {isReady ? (incidents.length === 1 ? t("list.count.one") : t("list.count.many", { n: incidents.length })) : ""}
          </p>
        </div>

        <form id="filtersForm" className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(event) => event.preventDefault()}>
          {filterSelects.map(({ field, id, values, label, placeholder }) => (
            <label key={field} className="text-sm font-semibold text-slate-700">
              <span>{t(label)}</span>
              <select id={id} name={field} value={filters[field]} onChange={(event) => setFilter(field, event.target.value)} className={SELECT_CLASS}>
                <FieldOptions values={values} group={field} placeholderKey={placeholder} t={t} />
              </select>
            </label>
          ))}
        </form>

        <form
          id="searchForm"
          noValidate
          className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            runSearch(searchInput);
          }}
        >
          <label className="flex-1 text-sm font-semibold text-slate-700">
            <span>{t("list.searchLabel")}</span>
            <input
              id="searchInput"
              name="q"
              type="search"
              autoComplete="off"
              placeholder={t("list.searchPlaceholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              className="mt-1 block min-h-12 w-full rounded-lg border border-cyan-200 px-3 py-2 text-base font-normal focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200"
            />
          </label>
          <button
            type="submit"
            className="min-h-12 rounded-lg bg-cyan-700 px-5 py-2 font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200"
          >
            {t("list.searchButton")}
          </button>
          <button
            id="searchClear"
            type="button"
            onClick={() => {
              setSearchInput("");
              runSearch("");
            }}
            className={`min-h-12 rounded-lg border border-cyan-300 bg-white px-5 py-2 font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200 ${activeSearch !== "" ? "block" : "hidden"}`}
          >
            {t("list.searchClear")}
          </button>
        </form>
        <p id="searchInfo" className={`mt-2 text-sm text-slate-600 ${searchNotes.length > 0 ? "block" : "hidden"}`}>
          {searchNotes.join(" ")}
        </p>

        {/* Aviso del último cambio de estado (éxito o fallo) */}
        <div
          id="listNotice"
          role="alert"
          className={
            notice === null
              ? "mt-5 hidden rounded-xl border p-4 text-sm"
              : `mt-5 rounded-xl border p-4 text-sm ${
                  notice.type === "error"
                    ? "border-red-200 bg-red-50 font-semibold text-red-800"
                    : "border-green-200 bg-green-50 text-green-900"
                }`
          }
        >
          {noticeText}
        </div>

        <div
          id="listLoading"
          role="status"
          className={`mt-5 items-center gap-3 rounded-xl border border-cyan-100 bg-cyan-50 p-4 text-sm text-cyan-900 ${listState === "loading" ? "flex" : "hidden"}`}
        >
          <Spinner />
          <span>{t("list.loading")}</span>
        </div>

        <div
          id="listError"
          role="alert"
          className={`mt-5 flex-col gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-semibold text-red-800 sm:flex-row sm:items-center sm:justify-between ${listState === "error" ? "flex" : "hidden"}`}
        >
          <span id="listErrorText">{listState === "error" ? t(listErrorKey) : ""}</span>
          <button id="listRetry" type="button" onClick={reloadList} className={RETRY_CLASS}>
            {t("common.retry")}
          </button>
        </div>

        <div id="listEmpty" role="status" className={`mt-5 rounded-xl border border-cyan-100 bg-cyan-50 p-6 text-center text-slate-700 ${isEmpty ? "block" : "hidden"}`}>
          {isEmpty ? (activeSearch ? t("list.emptySearch") : t(hasFilters ? "list.emptyFiltered" : "list.empty")) : ""}
        </div>

        <div id="listTable" className={`mt-5 overflow-x-auto ${isReady && !isEmpty ? "block" : "hidden"}`}>
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-cyan-100 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="py-3 pr-4">{t("list.colIncident")}</th>
                <th scope="col" className="py-3 pr-4">{t("field.category")}</th>
                <th scope="col" className="py-3 pr-4">{t("field.origin")}</th>
                <th scope="col" className="py-3 pr-4">{t("field.branch")}</th>
                <th scope="col" className="py-3 pr-4">{t("field.status")}</th>
                <th scope="col" className="py-3">
                  <span className="sr-only">{t("list.colActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody id="incidentsTableBody" className="divide-y divide-cyan-100">
              {isReady &&
                incidents.map((incident) => {
                  const showSimilar = expanded.has(incident.id);
                  return (
                    <Fragment key={incident.id}>
                      <tr data-id={incident.id}>
                        <td className="max-w-md py-4 pr-4 align-top">
                          <p className="font-bold text-slate-900">{`#${incident.id} · ${incident.title}`}</p>
                          {incident.description !== incident.title && (
                            <p className="mt-1 line-clamp-2 text-sm text-slate-600">{incident.description}</p>
                          )}
                          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                            {formatDate(lang, incident.created_at)}
                            {incident.score !== undefined && (
                              <span className="rounded-full bg-cyan-100 px-2 py-0.5 font-semibold text-cyan-800">
                                {t("list.match", { n: Math.round(incident.score * 100) })}
                              </span>
                            )}
                          </p>
                        </td>
                        <td className="py-4 pr-4 align-top">
                          <span
                            title={t(`categoryHint.${incident.category}`)}
                            className="inline-flex whitespace-nowrap rounded-full bg-cyan-100 px-2 py-0.5 text-xs font-semibold text-cyan-800"
                          >
                            {t(`category.${incident.category}`)}
                          </span>
                        </td>
                        <td className="py-4 pr-4 align-top text-slate-700">{t(`origin.${incident.origin}`)}</td>
                        <td className="py-4 pr-4 align-top text-slate-700">{t(`branch.${incident.branch}`)}</td>
                        <StatusCell key={`${incident.id}-${incident.status}`} incident={incident} t={t} onChange={changeStatus} />
                        <td className="py-4 align-top text-right">
                          <button
                            type="button"
                            onClick={() => toggleSimilar(incident.id)}
                            className="min-h-11 whitespace-nowrap rounded-lg border border-cyan-300 bg-white px-3 py-2 text-xs font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200"
                          >
                            {t(showSimilar ? "list.similarHide" : "list.similar")}
                          </button>
                        </td>
                      </tr>
                      {showSimilar && <SimilarRow incident={incident} t={t} lang={lang} />}
                    </Fragment>
                  );
                })}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
