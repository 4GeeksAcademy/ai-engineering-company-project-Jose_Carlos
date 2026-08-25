"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import Image from "next/image";
import { createRecord, getPhotoUrl, listRecords } from "../lib/api";
import {
  getStageLabel,
  getStatusLabel,
  STAGE_OPTIONS,
  STATUS_OPTIONS,
} from "../lib/constants";
import { CandidateRecord, RecordStage, RecordStatus } from "../lib/types";
import { TrackflowHeader } from "./trackflow-header";

const DEFAULT_LIMIT = 12;

type ListState = {
  loading: boolean;
  error: string | null;
  items: CandidateRecord[];
  total: number;
  page: number;
  limit: number;
  resolvedQueryKey: string;
};

type CreateFormState = {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  experience_years: string;
  linkedin_url: string;
  cv_url: string;
  status: RecordStatus;
  stage: RecordStage;
};

const DEFAULT_CREATE_FORM: CreateFormState = {
  full_name: "",
  email: "",
  phone: "",
  position: "",
  experience_years: "",
  linkedin_url: "",
  cv_url: "",
  status: "received",
  stage: "pending",
};

export function HomeClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [refreshTick, setRefreshTick] = useState(0);
  const [listState, setListState] = useState<ListState>({
    loading: true,
    error: null,
    items: [],
    total: 0,
    page: 1,
    limit: DEFAULT_LIMIT,
    resolvedQueryKey: "",
  });
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateFormState>(DEFAULT_CREATE_FORM);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const status = useMemo(
    () => (searchParams.get("status") as RecordStatus | null) ?? "",
    [searchParams],
  );
  const stage = useMemo(
    () => (searchParams.get("stage") as RecordStage | null) ?? "",
    [searchParams],
  );
  const search = useMemo(() => searchParams.get("search") ?? "", [searchParams]);
  const page = useMemo(() => {
    const value = Number(searchParams.get("page") ?? "1");
    return Number.isNaN(value) || value < 1 ? 1 : value;
  }, [searchParams]);
  const queryKey = useMemo(
    () => `${status}|${stage}|${search}|${page}`,
    [page, search, stage, status],
  );
  const isLoading = listState.loading || listState.resolvedQueryKey !== queryKey;
  const visibleError =
    listState.resolvedQueryKey === queryKey ? listState.error : null;

  useEffect(() => {
    let isMounted = true;

    void listRecords({
      status: status || undefined,
      stage: stage || undefined,
      search: search || undefined,
      page,
      limit: DEFAULT_LIMIT,
    })
      .then((response) => {
        if (!isMounted) return;
        setListState({
          loading: false,
          error: null,
          items: response.data,
          total: response.total,
          page: response.page,
          limit: response.limit,
          resolvedQueryKey: queryKey,
        });
      })
      .catch((error: unknown) => {
        if (!isMounted) return;
        setListState((current) => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : "Error desconocido",
          resolvedQueryKey: queryKey,
        }));
      });

    return () => {
      isMounted = false;
    };
  }, [page, queryKey, refreshTick, search, stage, status]);

  const totalPages = Math.max(1, Math.ceil(listState.total / listState.limit));

  function updateQuery(updates: Record<string, string | null>) {
    const params = new URLSearchParams(searchParams.toString());

    for (const [key, value] of Object.entries(updates)) {
      if (!value) {
        params.delete(key);
      } else {
        params.set(key, value);
      }
    }

    if ("status" in updates || "stage" in updates || "search" in updates) {
      params.delete("page");
    }

    const queryString = params.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname);
  }

  function handleCreateFormChange(
    field: keyof CreateFormState,
    value: string,
  ): void {
    setCreateForm((current) => ({ ...current, [field]: value }));
  }

  async function handleCreateCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);

    const experienceYears = Number(createForm.experience_years);
    if (Number.isNaN(experienceYears) || experienceYears < 0) {
      setCreateError("Los años de experiencia deben ser un número válido.");
      return;
    }

    setIsCreating(true);
    try {
      await createRecord({
        full_name: createForm.full_name.trim(),
        email: createForm.email.trim(),
        phone: createForm.phone.trim(),
        position: createForm.position.trim(),
        experience_years: experienceYears,
        linkedin_url: createForm.linkedin_url.trim() || null,
        cv_url: createForm.cv_url.trim() || null,
        status: createForm.status,
        stage: createForm.stage,
      });

      setCreateForm(DEFAULT_CREATE_FORM);
      setIsCreateOpen(false);
      setRefreshTick((current) => current + 1);
      updateQuery({ page: "1" });
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "Error desconocido");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-cyan-50 text-slate-800">
      <TrackflowHeader />

      <div className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 pb-8 pt-24 md:grid-cols-[300px_1fr] md:px-6">
        <nav className="rounded-2xl border border-cyan-100 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-lg font-bold text-slate-900">Filtros</h2>

          <label className="mb-2 block text-sm font-semibold text-slate-700">
            Estado
          </label>
          <select
            value={status}
            onChange={(event) =>
              updateQuery({ status: event.target.value || null })
            }
            className="mb-4 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
          >
            <option value="">Todos</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="mb-2 block text-sm font-semibold text-slate-700">
            Etapa
          </label>
          <select
            value={stage}
            onChange={(event) => updateQuery({ stage: event.target.value || null })}
            className="mb-4 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
          >
            <option value="">Todas</option>
            {STAGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="mb-2 block text-sm font-semibold text-slate-700">
            Buscar por nombre o email
          </label>
          <input
            value={search}
            onChange={(event) => updateQuery({ search: event.target.value || null })}
            className="mb-4 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
            placeholder="Ej: Michael Smith"
          />

          <button
            type="button"
            onClick={() => setIsCreateOpen((current) => !current)}
            className="w-full rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white"
          >
            {isCreateOpen ? "Cerrar formulario" : "Nueva candidatura"}
          </button>

          {isCreateOpen && (
            <form onSubmit={handleCreateCandidate} className="mt-4 space-y-3">
              <input
                required
                value={createForm.full_name}
                onChange={(event) =>
                  handleCreateFormChange("full_name", event.target.value)
                }
                placeholder="Nombre completo"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                required
                type="email"
                value={createForm.email}
                onChange={(event) => handleCreateFormChange("email", event.target.value)}
                placeholder="Email"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                required
                value={createForm.phone}
                onChange={(event) => handleCreateFormChange("phone", event.target.value)}
                placeholder="Teléfono"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                required
                value={createForm.position}
                onChange={(event) =>
                  handleCreateFormChange("position", event.target.value)
                }
                placeholder="Posición"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                required
                type="number"
                min="0"
                value={createForm.experience_years}
                onChange={(event) =>
                  handleCreateFormChange("experience_years", event.target.value)
                }
                placeholder="Años de experiencia"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                value={createForm.linkedin_url}
                onChange={(event) =>
                  handleCreateFormChange("linkedin_url", event.target.value)
                }
                placeholder="LinkedIn (opcional)"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <input
                value={createForm.cv_url}
                onChange={(event) => handleCreateFormChange("cv_url", event.target.value)}
                placeholder="CV URL (opcional)"
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              />
              <select
                value={createForm.status}
                onChange={(event) =>
                  handleCreateFormChange("status", event.target.value)
                }
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                value={createForm.stage}
                onChange={(event) =>
                  handleCreateFormChange("stage", event.target.value)
                }
                className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
              >
                {STAGE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              {createError && (
                <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                  No se pudo crear la candidatura: {createError}
                </p>
              )}

              <button
                type="submit"
                disabled={isCreating}
                className="w-full rounded-lg bg-cyan-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {isCreating ? "Creando..." : "Crear candidatura"}
              </button>
            </form>
          )}
        </nav>

        <main className="space-y-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-black text-slate-900">Candidaturas</h1>
            <p className="text-sm text-slate-600">
              Total: <strong>{listState.total}</strong>
            </p>
          </div>

          {isLoading && (
            <div className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm">
              Cargando candidaturas...
            </div>
          )}

          {visibleError && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-700">
              No se pudo cargar el listado: {visibleError}
            </div>
          )}

          {!isLoading && !visibleError && (
            <div className="space-y-3">
              {listState.items.map((record) => (
                <button
                  key={record.id}
                  onClick={() => router.push(`/records/${record.id}`)}
                  className="w-full rounded-2xl border border-cyan-100 bg-white p-4 text-left shadow-sm transition hover:border-cyan-300"
                >
                  <article className="flex flex-col gap-3 sm:flex-row sm:items-center">
                    <Image
                      src={getPhotoUrl(record.id)}
                      alt={`Foto de ${record.full_name}`}
                      className="h-16 w-16 rounded-xl border border-cyan-100 object-cover"
                      width={64}
                      height={64}
                      unoptimized
                    />
                    <div className="flex-1">
                      <h2 className="text-lg font-bold text-slate-900">
                        {record.full_name}
                      </h2>
                      <p className="text-sm text-slate-600">{record.position}</p>
                    </div>
                    <div className="grid gap-1 text-sm sm:text-right">
                      <span className="inline-flex rounded-full bg-cyan-100 px-2 py-1 font-semibold text-cyan-800 sm:justify-end">
                        {getStatusLabel(record.status)}
                      </span>
                      <span className="inline-flex rounded-full bg-slate-100 px-2 py-1 font-semibold text-slate-700 sm:justify-end">
                        {getStageLabel(record.stage)}
                      </span>
                      <span className="text-xs text-slate-500">
                        {record.experience_years} años de experiencia
                      </span>
                    </div>
                  </article>
                </button>
              ))}

              {listState.items.length === 0 && (
                <div className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm">
                  No hay candidaturas para los filtros actuales.
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-end gap-3">
            <button
              onClick={() => updateQuery({ page: String(Math.max(page - 1, 1)) })}
              disabled={page <= 1}
              className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            >
              Anterior
            </button>
            <span className="text-sm text-slate-600">
              Página {listState.page} de {totalPages}
            </span>
            <button
              onClick={() =>
                updateQuery({ page: String(Math.min(page + 1, totalPages)) })
              }
              disabled={page >= totalPages}
              className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            >
              Siguiente
            </button>
          </div>
        </main>
      </div>
    </div>
  );
}
