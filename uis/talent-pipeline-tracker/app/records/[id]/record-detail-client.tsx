"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createNote,
  deleteNote,
  deleteRecord,
  getPhotoUrl,
  getRecord,
  listNotes,
  patchRecord,
  putRecord,
} from "../../lib/api";
import { formatDate, STAGE_OPTIONS, STATUS_OPTIONS } from "../../lib/constants";
import { CandidateRecord, Note, RecordStage, RecordStatus } from "../../lib/types";
import { TrackflowHeader } from "../../ui/trackflow-header";

type DetailState = {
  loading: boolean;
  error: string | null;
  record: CandidateRecord | null;
};

type NotesState = {
  loading: boolean;
  error: string | null;
  items: Note[];
};

type EditFormState = {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  experience_years: string;
  linkedin_url: string;
  cv_url: string;
};

function mapRecordToEditForm(record: CandidateRecord): EditFormState {
  return {
    full_name: record.full_name,
    email: record.email,
    phone: record.phone,
    position: record.position,
    experience_years: String(record.experience_years),
    linkedin_url: record.linkedin_url ?? "",
    cv_url: record.cv_url ?? "",
  };
}

export function RecordDetailClient({ recordId }: { recordId: string }) {
  const router = useRouter();
  const [detailState, setDetailState] = useState<DetailState>({
    loading: true,
    error: null,
    record: null,
  });
  const [notesState, setNotesState] = useState<NotesState>({
    loading: true,
    error: null,
    items: [],
  });
  const [isStatusSaving, setIsStatusSaving] = useState(false);
  const [isStageSaving, setIsStageSaving] = useState(false);
  const [newNote, setNewNote] = useState("");
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [isUploadingPhoto, setIsUploadingPhoto] = useState(false);
  const [isDeletingRecord, setIsDeletingRecord] = useState(false);
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileFormError, setProfileFormError] = useState<string | null>(null);
  const [profileSuccessMessage, setProfileSuccessMessage] = useState<string | null>(
    null,
  );
  const [editForm, setEditForm] = useState<EditFormState>({
    full_name: "",
    email: "",
    phone: "",
    position: "",
    experience_years: "",
    linkedin_url: "",
    cv_url: "",
  });
  const [photoVersion, setPhotoVersion] = useState<number>(Date.now());

  const photoSrc = useMemo(
    () => getPhotoUrl(recordId, photoVersion),
    [photoVersion, recordId],
  );

  useEffect(() => {
    let isMounted = true;

    setDetailState({ loading: true, error: null, record: null });
    setNotesState({ loading: true, error: null, items: [] });

    void getRecord(recordId)
      .then((record) => {
        if (!isMounted) return;
        setDetailState({ loading: false, error: null, record });
        setEditForm(mapRecordToEditForm(record));
      })
      .catch((error: unknown) => {
        if (!isMounted) return;
        setDetailState({
          loading: false,
          error: error instanceof Error ? error.message : "Error desconocido",
          record: null,
        });
      });

    void listNotes(recordId)
      .then((notes) => {
        if (!isMounted) return;
        setNotesState({ loading: false, error: null, items: notes });
      })
      .catch((error: unknown) => {
        if (!isMounted) return;
        setNotesState({
          loading: false,
          error: error instanceof Error ? error.message : "Error desconocido",
          items: [],
        });
      });

    return () => {
      isMounted = false;
    };
  }, [recordId]);

  async function updateRecord(
    payload: { status?: RecordStatus; stage?: RecordStage },
    saving: "status" | "stage",
  ) {
    if (!detailState.record) return;

    if (saving === "status") setIsStatusSaving(true);
    if (saving === "stage") setIsStageSaving(true);

    try {
      const updatedRecord = await patchRecord(recordId, payload);
      setDetailState({ loading: false, error: null, record: updatedRecord });
      setProfileSuccessMessage(null);
    } catch (error) {
      setDetailState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error desconocido",
      }));
    } finally {
      if (saving === "status") setIsStatusSaving(false);
      if (saving === "stage") setIsStageSaving(false);
    }
  }

  async function handleCreateNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newNote.trim()) return;

    setIsCreatingNote(true);

    try {
      const created = await createNote(recordId, newNote.trim());
      setNotesState((current) => ({
        ...current,
        items: [created, ...current.items],
      }));
      setNewNote("");
    } catch (error) {
      setNotesState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error desconocido",
      }));
    } finally {
      setIsCreatingNote(false);
    }
  }

  async function handleDeleteNote(noteId: string) {
    setDeletingNoteId(noteId);
    try {
      await deleteNote(recordId, noteId);
      setNotesState((current) => ({
        ...current,
        items: current.items.filter((note) => note.id !== noteId),
      }));
    } catch (error) {
      setNotesState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error desconocido",
      }));
    } finally {
      setDeletingNoteId(null);
    }
  }

  async function handlePhotoUpload(file: File | null) {
    if (!file) return;

    setIsUploadingPhoto(true);

    try {
      const formData = new FormData();
      formData.set("recordId", recordId);
      formData.set("photo", file);

      const response = await fetch("/api/upload-photo", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Error ${response.status}: ${response.statusText}`);
      }

      setPhotoVersion(Date.now());
    } catch (error) {
      setDetailState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error desconocido",
      }));
    } finally {
      setIsUploadingPhoto(false);
    }
  }

  function openProfileEditor() {
    if (!detailState.record) return;
    setEditForm(mapRecordToEditForm(detailState.record));
    setProfileFormError(null);
    setProfileSuccessMessage(null);
    setIsEditingProfile(true);
  }

  function closeProfileEditor() {
    setProfileFormError(null);
    setIsEditingProfile(false);
  }

  function handleEditFieldChange(field: keyof EditFormState, value: string) {
    setEditForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSaveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detailState.record) return;

    const parsedYears = Number(editForm.experience_years);
    if (Number.isNaN(parsedYears) || parsedYears < 0) {
      setProfileFormError("Los años de experiencia deben ser un número válido.");
      return;
    }

    setProfileFormError(null);
    setProfileSuccessMessage(null);
    setIsSavingProfile(true);

    try {
      const updatedRecord = await putRecord(recordId, {
        full_name: editForm.full_name.trim(),
        email: editForm.email.trim(),
        phone: editForm.phone.trim(),
        position: editForm.position.trim(),
        experience_years: parsedYears,
        linkedin_url: editForm.linkedin_url.trim() || null,
        cv_url: editForm.cv_url.trim() || null,
        status: detailState.record.status,
        stage: detailState.record.stage,
      });

      setDetailState({ loading: false, error: null, record: updatedRecord });
      setEditForm(mapRecordToEditForm(updatedRecord));
      setProfileSuccessMessage("Datos actualizados correctamente.");
      setIsEditingProfile(false);
    } catch (error) {
      setProfileFormError(error instanceof Error ? error.message : "Error desconocido");
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleDeleteRecord() {
    const confirmed = window.confirm(
      "¿Seguro que deseas eliminar esta candidatura? Esta acción no se puede deshacer.",
    );
    if (!confirmed) return;

    setIsDeletingRecord(true);
    try {
      await deleteRecord(recordId);
      router.push("/");
    } catch (error) {
      setDetailState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error desconocido",
      }));
      setIsDeletingRecord(false);
    }
  }

  return (
    <div className="min-h-screen bg-cyan-50 text-slate-800">
      <TrackflowHeader />

      <main className="mx-auto max-w-5xl px-4 pb-10 pt-24 md:px-6">
        <div className="mb-4">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/"
              className="inline-flex rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm font-semibold text-cyan-700"
            >
              ← Volver al listado
            </Link>
            {detailState.record && (
              <>
                <button
                  type="button"
                  onClick={openProfileEditor}
                  className="inline-flex rounded-lg border border-cyan-300 bg-cyan-50 px-3 py-2 text-sm font-semibold text-cyan-800"
                >
                  Editar datos
                </button>
                <button
                  type="button"
                  onClick={handleDeleteRecord}
                  disabled={isDeletingRecord}
                  className="inline-flex rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 disabled:opacity-60"
                >
                  {isDeletingRecord ? "Eliminando..." : "Eliminar candidatura"}
                </button>
              </>
            )}
          </div>
        </div>

        {detailState.loading && (
          <section className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm">
            Cargando detalle...
          </section>
        )}

        {detailState.error && (
          <section className="mb-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-red-700">
            Ocurrió un error: {detailState.error}
          </section>
        )}

        {detailState.record && (
          <>
            <section className="mb-6 rounded-2xl border border-cyan-100 bg-white p-5 shadow-sm md:p-6">
              <div className="flex flex-col gap-6 md:flex-row">
                <div className="group relative w-fit">
                  <Image
                    src={photoSrc}
                    alt={`Foto de ${detailState.record.full_name}`}
                    className="h-56 w-56 rounded-2xl border border-cyan-100 object-cover"
                    width={224}
                    height={224}
                    unoptimized
                  />
                  <label className="absolute right-2 top-2 hidden cursor-pointer rounded-lg bg-black/70 px-3 py-2 text-xs font-semibold text-white group-hover:block">
                    {isUploadingPhoto ? "Subiendo..." : "Añadir foto de perfil"}
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(event) =>
                        handlePhotoUpload(event.target.files?.[0] ?? null)
                      }
                      disabled={isUploadingPhoto}
                    />
                  </label>
                </div>

                <div className="grid flex-1 gap-2">
                  {isEditingProfile ? (
                    <form onSubmit={handleSaveProfile} className="grid gap-2">
                      <input
                        required
                        value={editForm.full_name}
                        onChange={(event) =>
                          handleEditFieldChange("full_name", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="Nombre completo"
                      />
                      <input
                        required
                        type="email"
                        value={editForm.email}
                        onChange={(event) =>
                          handleEditFieldChange("email", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="Email"
                      />
                      <input
                        required
                        value={editForm.phone}
                        onChange={(event) =>
                          handleEditFieldChange("phone", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="Teléfono"
                      />
                      <input
                        required
                        value={editForm.position}
                        onChange={(event) =>
                          handleEditFieldChange("position", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="Posición"
                      />
                      <input
                        required
                        type="number"
                        min="0"
                        value={editForm.experience_years}
                        onChange={(event) =>
                          handleEditFieldChange("experience_years", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="Años de experiencia"
                      />
                      <input
                        value={editForm.linkedin_url}
                        onChange={(event) =>
                          handleEditFieldChange("linkedin_url", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="LinkedIn (opcional)"
                      />
                      <input
                        value={editForm.cv_url}
                        onChange={(event) =>
                          handleEditFieldChange("cv_url", event.target.value)
                        }
                        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                        placeholder="CV URL (opcional)"
                      />

                      {profileFormError && (
                        <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700">
                          No se pudo actualizar el perfil: {profileFormError}
                        </p>
                      )}

                      <div className="flex flex-wrap gap-2">
                        <button
                          type="submit"
                          disabled={isSavingProfile}
                          className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        >
                          {isSavingProfile ? "Guardando..." : "Guardar cambios (PUT)"}
                        </button>
                        <button
                          type="button"
                          onClick={closeProfileEditor}
                          className="rounded-lg border border-cyan-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                        >
                          Cancelar
                        </button>
                      </div>
                    </form>
                  ) : (
                    <>
                      <p>
                        <strong>Nombre:</strong> {detailState.record.full_name}
                      </p>
                      <p>
                        <strong>Email:</strong> {detailState.record.email}
                      </p>
                      <p>
                        <strong>Teléfono:</strong> {detailState.record.phone}
                      </p>
                      <p>
                        <strong>Posición:</strong> {detailState.record.position}
                      </p>
                      {detailState.record.linkedin_url && (
                        <p>
                          <strong>LinkedIn:</strong>{" "}
                          <a
                            className="text-cyan-700 underline"
                            href={detailState.record.linkedin_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Ver perfil
                          </a>
                        </p>
                      )}
                      {detailState.record.cv_url && (
                        <p>
                          <strong>CV:</strong>{" "}
                          <a
                            className="text-cyan-700 underline"
                            href={detailState.record.cv_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Abrir CV
                          </a>
                        </p>
                      )}
                      <p>
                        <strong>Experiencia:</strong> {detailState.record.experience_years} años
                      </p>
                    </>
                  )}

                  <label className="text-sm font-semibold text-slate-700">
                    Estado
                    <select
                      value={detailState.record.status}
                      disabled={isStatusSaving}
                      onChange={(event) =>
                        updateRecord(
                          { status: event.target.value as RecordStatus },
                          "status",
                        )
                      }
                      className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring disabled:opacity-60"
                    >
                      {STATUS_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm font-semibold text-slate-700">
                    Etapa
                    <select
                      value={detailState.record.stage}
                      disabled={isStageSaving}
                      onChange={(event) =>
                        updateRecord(
                          { stage: event.target.value as RecordStage },
                          "stage",
                        )
                      }
                      className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring disabled:opacity-60"
                    >
                      {STAGE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    <strong>Postulación:</strong> {formatDate(detailState.record.applied_at)}
                  </p>
                  <p>
                    <strong>Última actualización:</strong>{" "}
                    {formatDate(detailState.record.updated_at)}
                  </p>
                  {profileSuccessMessage && (
                    <p className="rounded-lg border border-green-200 bg-green-50 p-2 text-sm text-green-700">
                      {profileSuccessMessage}
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-2xl border border-cyan-100 bg-white p-5 shadow-sm md:p-6">
              <h2 className="mb-4 text-xl font-bold text-slate-900">Notas internas</h2>

              <form onSubmit={handleCreateNote} className="mb-4 flex gap-2">
                <input
                  value={newNote}
                  onChange={(event) => setNewNote(event.target.value)}
                  placeholder="Escribe una nota de seguimiento"
                  className="flex-1 rounded-lg border border-cyan-200 px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
                />
                <button
                  type="submit"
                  disabled={isCreatingNote}
                  className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {isCreatingNote ? "Guardando..." : "Añadir nota"}
                </button>
              </form>

              {notesState.loading && (
                <p className="rounded-lg border border-cyan-100 bg-cyan-50 p-3 text-sm">
                  Cargando notas...
                </p>
              )}

              {notesState.error && (
                <p className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  No se pudieron cargar las notas: {notesState.error}
                </p>
              )}

              {!notesState.loading && (
                <div className="max-h-[360px] overflow-y-auto pr-1">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {notesState.items.map((note) => (
                      <article
                        key={note.id}
                        className="flex h-28 flex-col justify-between rounded-xl border border-cyan-100 bg-cyan-50 p-3"
                      >
                        <p className="note-clamp text-sm leading-5">{note.content}</p>
                        <div className="mt-2 flex items-center justify-between">
                          <span className="text-xs text-slate-500">
                            {formatDate(note.created_at)}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDeleteNote(note.id)}
                            disabled={deletingNoteId === note.id}
                            className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 disabled:opacity-60"
                          >
                            {deletingNoteId === note.id ? "Eliminando..." : "Eliminar"}
                          </button>
                        </div>
                      </article>
                    ))}

                    {notesState.items.length === 0 && (
                      <p className="rounded-xl border border-cyan-100 bg-cyan-50 p-3 text-sm text-slate-600">
                        Aún no hay notas para esta candidatura.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
