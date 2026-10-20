"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { SessionExpiredError } from "../../../lib/auth";
import {
  BRANCHES,
  CATEGORIES,
  DESCRIPTION_MAX_LENGTH,
  FieldError,
  IncidentDraft,
  IncidentsApiError,
  ORIGINS,
  STATUSES,
  Suggestion,
  TITLE_MAX_LENGTH,
  errorMessage,
  fieldErrorMessage,
  incidentsApi,
} from "../../../lib/incidents";
import { FieldOptions, Spinner, StatusBadge } from "../../../ui/incidents-common";
import { useDocumentLang, useIncidentsLang } from "../../../ui/incidents-lang";

// Formulario de registro de incidencias, con ayuda semántica mientras se escribe:
// incidencias parecidas, posibles duplicados y categoría sugerida.

type Field = keyof IncidentDraft;
const FIELDS: Field[] = ["origin", "branch", "category", "status", "title", "description"];
const ASSIST_MIN_LENGTH = 12;
const ASSIST_DELAY_MS = 600;

type FieldErrors = Partial<Record<Field, FieldError>>;
type AssistStatus = "idle" | "loading" | "ready" | "unavailable";
// El mensaje se guarda por clave para volver a traducirlo al cambiar de idioma.
type Message = { type: "success" | "error"; key: string; params?: Record<string, string | number>; text?: string };

const EMPTY_FORM: IncidentDraft = { origin: "", branch: "", category: "", status: STATUSES[0], title: "", description: "" };

const CONTROL_CLASS =
  "mt-2 block min-h-14 w-full rounded-lg border bg-white px-4 py-3 text-lg focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200";

// Validación en cliente, antes de enviar.
function validate(data: IncidentDraft): FieldErrors {
  const errors: FieldErrors = {};
  FIELDS.forEach((field) => {
    if (!data[field]) errors[field] = { field, code: "required" };
  });
  if (data.title.length > TITLE_MAX_LENGTH) errors.title = { field: "title", code: "too_long" };
  if (data.description.length > DESCRIPTION_MAX_LENGTH) errors.description = { field: "description", code: "too_long" };
  return errors;
}

export function IncidentFormClient() {
  const { lang, t } = useIncidentsLang();
  useDocumentLang(lang);

  const formRef = useRef<HTMLFormElement>(null);
  const [form, setForm] = useState<IncidentDraft>(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [message, setMessage] = useState<Message | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [assistStatus, setAssistStatus] = useState<AssistStatus>("idle");
  const [assistResult, setAssistResult] = useState<Suggestion | null>(null);
  const assistTimer = useRef<number | undefined>(undefined);
  const assistRequestId = useRef(0);
  // Lleva el foco a un campo cuando React ya ha pintado los errores.
  function setFocusField(field: Field | null) {
    if (!field) return;
    window.setTimeout(() => formRef.current?.querySelector<HTMLElement>(`[name="${field}"]`)?.focus(), 0);
  }

  useEffect(() => () => window.clearTimeout(assistTimer.current), []);

  function clearFieldError(field: Field) {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  function update(field: Field, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    clearFieldError(field);
  }

  const resetAssist = useCallback(() => {
    window.clearTimeout(assistTimer.current);
    assistRequestId.current += 1;
    setAssistResult(null);
    setAssistStatus("idle");
  }, []);

  const loadAssist = useCallback(
    async (draft: { title: string; description: string }) => {
      if (draft.title.length + draft.description.length < ASSIST_MIN_LENGTH) {
        resetAssist();
        return;
      }
      const requestId = ++assistRequestId.current;
      setAssistStatus("loading");
      try {
        const result = await incidentsApi.suggest(draft);
        if (requestId !== assistRequestId.current) return;
        setAssistResult(result);
        setAssistStatus("ready");
      } catch (error) {
        if (error instanceof SessionExpiredError || requestId !== assistRequestId.current) return;
        // Es solo una ayuda: si falla, el formulario sigue funcionando sin ella, pero se avisa
        // de que no se ha podido comprobar si la incidencia ya existe.
        setAssistResult(null);
        setAssistStatus("unavailable");
      }
    },
    [resetAssist],
  );

  function updateText(field: "title" | "description", value: string) {
    const next = { ...form, [field]: value };
    update(field, value);
    window.clearTimeout(assistTimer.current);
    assistTimer.current = window.setTimeout(
      () => loadAssist({ title: next.title.trim(), description: next.description.trim() }),
      ASSIST_DELAY_MS,
    );
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    setMessage(null);

    const data: IncidentDraft = { ...form, title: form.title.trim(), description: form.description.trim() };
    const errors = validate(data);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setMessage({ type: "error", key: "form.reviewErrors" });
      setFocusField(FIELDS.find((field) => errors[field]) ?? null);
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await incidentsApi.create(data);
      setForm(EMPTY_FORM);
      resetAssist();
      setMessage({ type: "success", key: "form.success", params: { id: created.id } });
    } catch (error) {
      if (error instanceof SessionExpiredError) return;

      // Los errores que identifican un campo del formulario se muestran junto a él.
      const known = error instanceof IncidentsApiError ? error.errors.filter((item) => FIELDS.includes(item.field as Field)) : [];
      if (known.length > 0) {
        const next: FieldErrors = { ...errors };
        known.forEach((item) => {
          next[item.field as Field] = item;
        });
        setFieldErrors(next);
        setMessage({ type: "error", key: "form.reviewErrors" });
        setFocusField(FIELDS.find((field) => next[field]) ?? null);
      } else {
        // Este mensaje se compone una vez (como antes): no se retraduce.
        setMessage({ type: "error", key: "", text: errorMessage(lang, error) });
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  function errorFor(field: Field) {
    const error = fieldErrors[field];
    return (
      <p data-error-for={field} role="alert" className={`mt-2 text-sm font-semibold text-red-700 ${error ? "" : "hidden"}`}>
        {error ? fieldErrorMessage(lang, error) : ""}
      </p>
    );
  }

  const controlBorder = (field: Field) => (fieldErrors[field] ? "border-red-500" : "border-cyan-200");
  const branchHighlighted = form.origin === "branch";

  // ---------------------------------------------------------------- ayuda semántica
  const similar = assistResult ? assistResult.similar : [];
  const hasAssistContent = assistStatus === "ready" && similar.length > 0;
  const suggestion = assistResult?.suggested_category ?? null;
  const assistStateText =
    assistStatus === "loading"
      ? t("assist.loading")
      : hasAssistContent
        ? ""
        : t({ ready: "assist.empty", unavailable: "assist.unavailable" }[assistStatus as "ready" | "unavailable"] || "assist.intro");

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-12">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">{t("form.eyebrow")}</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">
          {t("form.title")}
        </h1>
        <p className="mt-3 max-w-2xl text-slate-600">{t("form.intro")}</p>
      </section>

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        {/* FORMULARIO: campos grandes, pensados para uso táctil en almacén */}
        <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7 lg:col-span-2">
          <form id="incidentForm" ref={formRef} noValidate className="space-y-6" onSubmit={onSubmit}>
            <fieldset>
              <legend className="text-base font-semibold text-slate-800">
                <span>{t("field.origin")}</span> *
              </legend>
              <div id="originOptions" className="mt-2 grid gap-3 sm:grid-cols-3">
                {ORIGINS.map((origin) => (
                  <label
                    key={origin}
                    className="flex min-h-20 cursor-pointer flex-col justify-center rounded-xl border-2 border-cyan-200 bg-white px-4 py-3 transition hover:bg-cyan-50 has-[:checked]:border-cyan-700 has-[:checked]:bg-cyan-50 has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-cyan-200"
                  >
                    <input
                      className="sr-only"
                      type="radio"
                      name="origin"
                      value={origin}
                      checked={form.origin === origin}
                      onChange={() => update("origin", origin)}
                    />
                    <span className="text-lg font-bold text-slate-900">{t(`origin.${origin}`)}</span>
                    <span className="text-sm text-slate-600">{t(`originHint.${origin}`)}</span>
                  </label>
                ))}
              </div>
              {errorFor("origin")}
            </fieldset>

            {/* Cuando el origen es una sede, el campo de sede se destaca. */}
            <div
              id="branchField"
              data-highlighted={String(branchHighlighted)}
              className={
                branchHighlighted
                  ? "rounded-xl border-2 border-amber-400 bg-amber-50 p-4 ring-4 ring-amber-100 transition-all"
                  : "rounded-xl border border-transparent p-0 transition-all"
              }
            >
              <label htmlFor="branchInput" className="text-base font-semibold text-slate-800">
                <span>{t("field.branch")}</span> *
              </label>
              <select
                id="branchInput"
                name="branch"
                required
                value={form.branch}
                aria-invalid={Boolean(fieldErrors.branch)}
                onChange={(event) => update("branch", event.target.value)}
                className={`${CONTROL_CLASS} ${controlBorder("branch")}`}
              >
                <FieldOptions values={BRANCHES} group="branch" placeholderKey="common.select" t={t} />
              </select>
              <p id="branchHint" className={branchHighlighted ? "mt-2 text-sm font-bold text-amber-900" : "mt-2 text-sm text-slate-600"}>
                {t(branchHighlighted ? "form.branchHighlight" : "form.branchHint")}
              </p>
              {errorFor("branch")}
            </div>

            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <label htmlFor="categoryInput" className="text-base font-semibold text-slate-800">
                  <span>{t("field.category")}</span> *
                </label>
                <select
                  id="categoryInput"
                  name="category"
                  required
                  value={form.category}
                  aria-invalid={Boolean(fieldErrors.category)}
                  onChange={(event) => update("category", event.target.value)}
                  className={`${CONTROL_CLASS} ${controlBorder("category")}`}
                >
                  <FieldOptions values={CATEGORIES} group="category" placeholderKey="common.select" t={t} />
                </select>
                <p id="categoryHint" className="mt-2 text-sm text-slate-600">
                  {form.category ? t(`categoryHint.${form.category}`) : ""}
                </p>
                {errorFor("category")}
              </div>
              <div>
                <label htmlFor="statusInput" className="text-base font-semibold text-slate-800">
                  <span>{t("field.status")}</span> *
                </label>
                <select
                  id="statusInput"
                  name="status"
                  required
                  value={form.status}
                  aria-invalid={Boolean(fieldErrors.status)}
                  onChange={(event) => update("status", event.target.value)}
                  className={`${CONTROL_CLASS} ${controlBorder("status")}`}
                >
                  <FieldOptions values={STATUSES} group="status" t={t} />
                </select>
                {errorFor("status")}
              </div>
            </div>

            <div>
              <label htmlFor="titleInput" className="text-base font-semibold text-slate-800">
                <span>{t("field.title")}</span> *
              </label>
              <input
                id="titleInput"
                name="title"
                type="text"
                required
                autoComplete="off"
                placeholder={t("form.titlePlaceholder")}
                value={form.title}
                aria-invalid={Boolean(fieldErrors.title)}
                onChange={(event) => updateText("title", event.target.value)}
                className={`mt-2 block min-h-14 w-full rounded-lg border px-4 py-3 text-lg focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200 ${controlBorder("title")}`}
              />
              {errorFor("title")}
            </div>

            <div>
              <label htmlFor="descriptionInput" className="text-base font-semibold text-slate-800">
                <span>{t("field.description")}</span> *
              </label>
              <textarea
                id="descriptionInput"
                name="description"
                rows={4}
                required
                placeholder={t("form.descriptionPlaceholder")}
                value={form.description}
                aria-invalid={Boolean(fieldErrors.description)}
                onChange={(event) => updateText("description", event.target.value)}
                className={`mt-2 block w-full rounded-lg border px-4 py-3 text-lg focus:border-cyan-500 focus:outline-none focus:ring-4 focus:ring-cyan-200 ${controlBorder("description")}`}
              />
              {errorFor("description")}
            </div>

            <div>
              <div
                id="formMessage"
                role="status"
                aria-live="polite"
                className={
                  message === null
                    ? "mb-4 hidden rounded-xl border p-4 text-base"
                    : `mb-4 rounded-xl border p-4 text-base ${
                        message.type === "error"
                          ? "border-red-200 bg-red-50 font-semibold text-red-800"
                          : "border-green-200 bg-green-50 font-semibold text-green-900"
                      }`
                }
              >
                {message && (message.text ?? t(message.key, message.params))}
                {message?.type === "success" && (
                  <Link href="/incidents" className="ml-2 font-bold underline">
                    {t("form.successLink")}
                  </Link>
                )}
              </div>
              <button
                id="submitButton"
                type="submit"
                disabled={isSubmitting}
                className="inline-flex min-h-14 w-full items-center justify-center rounded-lg bg-cyan-700 px-6 py-3 text-lg font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-300 sm:w-auto"
              >
                <Spinner id="submitSpinner" className={`mr-2 h-5 w-5 animate-spin ${isSubmitting ? "" : "hidden"}`} />
                <span id="submitText">{t(isSubmitting ? "form.submitting" : "form.submit")}</span>
              </button>
            </div>
          </form>
        </section>

        {/* AYUDA SEMÁNTICA: similares, posibles duplicados y categoría sugerida */}
        <aside className="h-fit rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6" aria-labelledby="assist-title">
          <h2 id="assist-title" className="text-lg font-bold text-slate-900">{t("assist.title")}</h2>
          <p id="assistState" className="mt-2 text-sm text-slate-600">{assistStateText}</p>
          <div id="assistContent" className={`mt-4 space-y-4 ${hasAssistContent ? "" : "hidden"}`}>
            {hasAssistContent && (
              <>
                {similar.some((item) => item.possible_duplicate) && (
                  <p className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-900">
                    {t("assist.duplicateWarning")}
                  </p>
                )}

                {suggestion && suggestion.value !== form.category && (
                  <div className="rounded-xl border border-cyan-200 bg-cyan-50 p-3">
                    <p className="text-xs font-bold uppercase tracking-wide text-cyan-800">{t("assist.suggested")}</p>
                    <button
                      type="button"
                      onClick={() => update("category", suggestion.value)}
                      className="mt-2 min-h-12 w-full rounded-lg bg-cyan-700 px-4 py-2 text-base font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200"
                    >
                      {t("assist.useCategory", { category: t(`category.${suggestion.value}`) })}
                    </button>
                    <p className="mt-2 text-xs text-slate-600">
                      {t("assist.confidence", { n: Math.round(suggestion.confidence * 100) })}
                    </p>
                  </div>
                )}

                <div>
                  <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{t("assist.similar")}</p>
                  <ul className="mt-2 space-y-3">
                    {similar.map((item) => (
                      <li key={item.id} className="rounded-xl border border-cyan-100 p-3">
                        <p className="text-sm font-semibold text-slate-900">{`#${item.id} · ${item.title}`}</p>
                        <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                          <StatusBadge status={item.status} t={t} />
                          {t(`branch.${item.branch}`)}
                          {item.possible_duplicate && (
                            <span className="rounded-full bg-amber-100 px-2 py-0.5 font-bold text-amber-900">{t("assist.duplicate")}</span>
                          )}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
