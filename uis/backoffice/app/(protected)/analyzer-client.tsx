"use client";

import { DragEvent, FormEvent, useEffect, useRef, useState } from "react";
import { SessionExpiredError, backofficeFetch } from "../lib/auth";

// Analizador de incidentes CSV: POST /analyze y GET /api/incidents/results/export.

type AnalysisResults = {
  valid?: unknown;
  invalid?: unknown;
  media_satisfaccion?: unknown;
  categories?: Record<string, number> | null;
  statuses?: Record<string, number> | null;
  errores?: Array<{ incident_id?: unknown; errors?: unknown }> | null;
};

type Message = { type: "success" | "error"; text: string };

// Los mensajes de error se eligen aquí según el tipo de fallo: nunca se muestra el texto
// que devuelve el servidor, el código de estado ni el mensaje del navegador.
const NETWORK_ERROR = "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.";
const SERVER_ERROR = "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.";
const NO_FILE_ERROR = "Selecciona un archivo CSV antes de iniciar el análisis.";

const ANALYZE_ERRORS: Record<number, string> = {
  400: "El archivo no es un CSV válido en UTF-8. Revisa el archivo y vuelve a subirlo.",
  413: "El archivo es demasiado grande.",
  422: NO_FILE_ERROR,
};

const EXPORT_ERRORS: Record<number, string> = {
  404: "Todavía no hay ningún análisis que exportar. Analiza un archivo primero.",
};

// Error cuyo `message` ya es un texto para el usuario.
class RequestError extends Error {}

async function request(
  path: string,
  options: RequestInit & { timeoutMs?: number },
  messagesByStatus: Record<number, string>,
): Promise<Response> {
  let response: Response;
  try {
    response = await backofficeFetch(path, options);
  } catch (error) {
    // Sesión caducada: el guard ya está llevando al login.
    if (error instanceof SessionExpiredError) throw error;
    throw new RequestError(NETWORK_ERROR);
  }
  if (!response.ok) throw new RequestError(messagesByStatus[response.status] || SERVER_ERROR);
  return response;
}

function userMessage(error: unknown): string {
  return error instanceof RequestError ? error.message : SERVER_ERROR;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kilobytes = bytes / 1024;
  return kilobytes < 1024 ? `${kilobytes.toFixed(1)} KB` : `${(kilobytes / 1024).toFixed(1)} MB`;
}

const BUTTON_PRIMARY =
  "inline-flex items-center justify-center rounded-lg bg-cyan-700 px-5 py-3 font-bold text-white transition hover:bg-cyan-800 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-300";

function Breakdown({ id, entries, emptyMessage }: { id: string; entries: [string, number][]; emptyMessage: string }) {
  return (
    <dl id={id} className="mt-4 divide-y divide-cyan-100">
      {entries.length === 0 ? (
        <p className="py-4 text-sm text-slate-600">{emptyMessage}</p>
      ) : (
        entries.map(([label, count]) => (
          <div key={label} className="flex items-center justify-between gap-4 py-3">
            <dt className="break-words text-sm font-medium text-slate-700">{label}</dt>
            <dd className="rounded-full bg-cyan-100 px-3 py-1 text-sm font-bold text-cyan-800">{String(count)}</dd>
          </div>
        ))
      )}
    </dl>
  );
}

export function AnalyzerClient() {
  const fileInput = useRef<HTMLInputElement>(null);
  const resultsSection = useRef<HTMLElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [resultsFileName, setResultsFileName] = useState("");
  const [canExport, setCanExport] = useState(false);
  // Cada análisis correcto vuelve a llevar la vista a los resultados.
  const [resultsTick, setResultsTick] = useState(0);

  useEffect(() => {
    if (resultsTick > 0) resultsSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [resultsTick]);

  function selectFile(next: File | null) {
    setFile(next);
    if (!next && fileInput.current) fileInput.current.value = "";
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragOver(false);
    if (isAnalyzing) return;
    const [dropped] = event.dataTransfer.files;
    if (dropped && fileInput.current) {
      const transfer = new DataTransfer();
      transfer.items.add(dropped);
      fileInput.current.files = transfer.files;
      selectFile(dropped);
      setMessage(null);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || isAnalyzing) {
      setMessage({ type: "error", text: NO_FILE_ERROR });
      return;
    }

    setMessage(null);
    setIsAnalyzing(true);
    const formData = new FormData();
    formData.append("file", file);

    try {
      // Un CSV grande puede tardar en subir y analizarse: más margen que el tiempo por defecto.
      const response = await request("/analyze", { method: "POST", body: formData, timeoutMs: 120000 }, ANALYZE_ERRORS);
      const body = (await response.json()) as AnalysisResults;
      setResults(body);
      setResultsFileName(`Archivo: ${file.name}`);
      setCanExport(true);
      setResultsTick((tick) => tick + 1);
      setMessage({
        type: "success",
        text:
          Number(body.invalid) > 0
            ? "Análisis completado. Se encontraron registros que requieren revisión."
            : "Análisis completado correctamente, sin registros inválidos.",
      });
    } catch (error) {
      if (!(error instanceof SessionExpiredError)) {
        setMessage({ type: "error", text: `No se pudo completar el análisis. ${userMessage(error)}` });
      }
    } finally {
      setIsAnalyzing(false);
    }
  }

  // El export es una ruta protegida: un enlace normal no puede enviar la cabecera
  // Authorization, así que descargamos con fetch y lo guardamos desde un blob.
  async function onExport() {
    if (!canExport) return;
    try {
      const response = await request("/api/incidents/results/export", {}, EXPORT_ERRORS);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "results.csv";
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      if (!(error instanceof SessionExpiredError)) {
        setMessage({ type: "error", text: `No se pudo descargar el CSV. ${userMessage(error)}` });
      }
    }
  }

  const valid = Number(results?.valid) || 0;
  const invalid = Number(results?.invalid) || 0;
  const satisfaction = Number(results?.media_satisfaccion);
  const categories = results?.categories && typeof results.categories === "object" ? Object.entries(results.categories) : [];
  const statuses = results?.statuses && typeof results.statuses === "object" ? Object.entries(results.statuses) : [];
  const invalidRecords = Array.isArray(results?.errores) ? results.errores : [];

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-12">
      <section aria-labelledby="page-title">
        <p className="mb-2 text-sm font-bold uppercase tracking-widest text-cyan-700">Control de calidad</p>
        <h1 id="page-title" className="text-3xl font-black tracking-tight text-slate-900 md:text-4xl">
          Analizador de incidentes CSV
        </h1>
        <p className="mt-3 max-w-2xl text-slate-600">
          Carga un archivo para revisar sus métricas y detectar registros que necesitan corrección.
        </p>
      </section>

      <section className="mt-8 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-7" aria-labelledby="upload-title">
        <div className="mb-5">
          <h2 id="upload-title" className="text-xl font-bold text-slate-900">Cargar archivo</h2>
          <p className="mt-1 text-sm text-slate-600">Selecciona o arrastra un archivo CSV para comenzar.</p>
        </div>

        <form id="analysisForm" noValidate onSubmit={onSubmit}>
          <label
            id="dropZone"
            htmlFor="csvFile"
            onDragEnter={(event) => {
              event.preventDefault();
              if (!isAnalyzing) setIsDragOver(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              if (!isAnalyzing) setIsDragOver(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDragOver(false);
            }}
            onDrop={onDrop}
            className={`group flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-5 py-8 text-center transition hover:border-cyan-500 hover:bg-cyan-100 focus-within:border-cyan-600 focus-within:ring-4 focus-within:ring-cyan-200 ${
              isDragOver ? "border-cyan-600 bg-cyan-100" : "border-cyan-300 bg-cyan-50"
            }`}
          >
            <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-white text-2xl text-cyan-700 shadow-sm" aria-hidden="true">
              ↑
            </span>
            <span className="font-bold text-slate-900">Arrastra el CSV hasta aquí</span>
            <span className="mt-1 text-sm text-slate-600">o pulsa para seleccionarlo desde tu dispositivo</span>
            <input
              ref={fileInput}
              id="csvFile"
              name="file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              disabled={isAnalyzing}
              onChange={(event) => {
                selectFile(event.target.files?.[0] ?? null);
                setMessage(null);
              }}
            />
          </label>

          <div
            id="selectedFile"
            className={`mt-4 items-center justify-between gap-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 ${file ? "flex" : "hidden"}`}
          >
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-wide text-cyan-800">Archivo seleccionado</p>
              <p id="fileName" className="mt-1 truncate font-semibold text-slate-900">{file?.name ?? ""}</p>
              <p id="fileSize" className="text-sm text-slate-600">{file ? formatFileSize(file.size) : ""}</p>
            </div>
            <button
              id="removeFileButton"
              type="button"
              disabled={isAnalyzing}
              onClick={() => {
                selectFile(null);
                setMessage(null);
                fileInput.current?.focus();
              }}
              className="shrink-0 rounded-lg border border-cyan-300 bg-white px-3 py-2 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-100 focus:outline-none focus:ring-4 focus:ring-cyan-200"
            >
              Quitar
            </button>
          </div>

          <div
            id="requestMessage"
            role="status"
            aria-live="polite"
            className={
              message === null
                ? "mt-4 hidden rounded-xl border p-4 text-sm"
                : `mt-4 rounded-xl border p-4 text-sm ${
                    message.type === "error"
                      ? "border-red-200 bg-red-50 font-semibold text-red-800"
                      : "border-cyan-200 bg-cyan-50 text-cyan-900"
                  }`
            }
          >
            {message?.text ?? ""}
          </div>

          <div className="mt-5 flex flex-col gap-3 sm:flex-row">
            <button id="analyzeButton" type="submit" disabled={isAnalyzing || !file} className={BUTTON_PRIMARY}>
              <svg
                id="loadingSpinner"
                className={`mr-2 h-5 w-5 animate-spin ${isAnalyzing ? "" : "hidden"}`}
                viewBox="0 0 24 24"
                fill="none"
                aria-hidden="true"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4Z" />
              </svg>
              <span id="analyzeButtonText">{isAnalyzing ? "Analizando..." : "Analizar archivo"}</span>
            </button>
            <button
              id="exportButton"
              type="button"
              disabled={!canExport}
              onClick={onExport}
              className="inline-flex items-center justify-center rounded-lg border border-cyan-300 bg-white px-5 py-3 font-bold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
            >
              Descargar resultados CSV
            </button>
          </div>
        </form>
      </section>

      <section
        id="resultsSection"
        ref={resultsSection}
        className={`mt-8 space-y-6 ${results ? "" : "hidden"}`}
        aria-labelledby="results-title"
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-bold uppercase tracking-widest text-cyan-700">Último análisis</p>
            <h2 id="results-title" className="mt-1 text-2xl font-black text-slate-900">Resultados</h2>
          </div>
          <p id="resultsFileName" className="text-sm text-slate-600">{resultsFileName}</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3" aria-label="Resumen general">
          <article className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-semibold text-slate-600">Registros válidos</p>
            <p id="validCount" className="mt-2 text-3xl font-black text-cyan-700">{String(valid)}</p>
          </article>
          <article className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-semibold text-slate-600">Registros inválidos</p>
            <p id="invalidCount" className="mt-2 text-3xl font-black text-slate-900">{String(invalid)}</p>
          </article>
          <article className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-semibold text-slate-600">Satisfacción media</p>
            <p id="satisfactionAverage" className="mt-2 text-3xl font-black text-cyan-700">
              {Number.isFinite(satisfaction) ? satisfaction.toFixed(2) : "0.00"}
            </p>
          </article>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6" aria-labelledby="categories-title">
            <h3 id="categories-title" className="text-lg font-bold text-slate-900">Desglose por categoría</h3>
            <Breakdown id="categoriesList" entries={categories} emptyMessage="No hay categorías contabilizadas." />
          </section>

          <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6" aria-labelledby="statuses-title">
            <h3 id="statuses-title" className="text-lg font-bold text-slate-900">Desglose por estado</h3>
            <Breakdown id="statusesList" entries={statuses} emptyMessage="No hay estados contabilizados." />
          </section>
        </div>

        <section className="rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm md:p-6" aria-labelledby="invalid-records-title">
          <h3 id="invalid-records-title" className="text-lg font-bold text-slate-900">Registros inválidos</h3>
          {invalidRecords.length === 0 ? (
            <div id="invalidRecordsStatus" role="status" className="mt-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-900">
              No se encontraron registros inválidos en el archivo.
            </div>
          ) : (
            <div id="invalidRecordsStatus" role="status" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm font-semibold text-amber-900">
              {`Se encontraron ${invalidRecords.length} registros con errores. Revisa el detalle antes de continuar.`}
            </div>
          )}
          <div id="invalidRecordsList" className="mt-4 space-y-3">
            {invalidRecords.map((record, index) => (
              <article key={index} className="rounded-xl border border-amber-200 bg-white p-4">
                <h4 className="font-bold text-slate-900">{`Incidente: ${String(record.incident_id ?? "UNKNOWN")}`}</h4>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                  {(Array.isArray(record.errors) ? record.errors : []).map((error, errorIndex) => (
                    <li key={errorIndex}>{String(error)}</li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
