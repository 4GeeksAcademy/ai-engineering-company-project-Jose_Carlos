import { API_BASE_URL } from "./constants";
import {
  CandidateRecord,
  Note,
  NotesResponse,
  RecordCreatePayload,
  RecordReplacePayload,
  RecordStage,
  RecordStatus,
  RecordsResponse,
} from "./types";

function buildUrl(path: string, query?: Record<string, string | number | undefined>) {
  const url = new URL(`${API_BASE_URL}${path}`);

  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  return url.toString();
}

// =========================================================
// ERRORES
// =========================================================

export type RecordsApiErrorKind = "network" | "not_found" | "validation" | "server";

// Texto para el usuario según el tipo de fallo: las pantallas muestran `error.message`,
// así que nunca debe contener el código de estado ni el mensaje del navegador o del servidor.
const ERROR_MESSAGES: Record<RecordsApiErrorKind, string> = {
  network: "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.",
  not_found: "No se ha encontrado. Puede que se haya eliminado.",
  validation: "Los datos enviados no son válidos. Revísalos e inténtalo de nuevo.",
  server: "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.",
};

export class RecordsApiError extends Error {
  constructor(
    public kind: RecordsApiErrorKind,
    public status = 0,
  ) {
    super(ERROR_MESSAGES[kind]);
  }
}

export function isNotFoundError(error: unknown): boolean {
  return error instanceof RecordsApiError && error.kind === "not_found";
}

/** Mensaje para mostrar al usuario a partir de cualquier error capturado. */
export function toUserMessage(error: unknown): string {
  return error instanceof RecordsApiError ? error.message : ERROR_MESSAGES.server;
}

function errorKind(status: number): RecordsApiErrorKind {
  if (status === 404) return "not_found";
  if (status === 400 || status === 422) return "validation";
  return "server";
}

const REQUEST_TIMEOUT_MS = 15000;

/** fetch con tiempo de espera; un fallo de red o una respuesta de error lanza RecordsApiError. */
async function request(url: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch {
    // Sin conexión, CORS o tiempo de espera agotado.
    throw new RecordsApiError("network");
  }

  if (!response.ok) {
    throw new RecordsApiError(errorKind(response.status), response.status);
  }
  return response;
}

async function parseResponse<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    // Respuesta correcta pero ilegible.
    throw new RecordsApiError("server", response.status);
  }
}

export function getPhotoUrl(recordId: string, version?: number): string {
  const photoUrl = new URL(`/api/profile-photo/${recordId}`, "http://localhost");
  if (version) {
    photoUrl.searchParams.set("v", String(version));
  }
  return `${photoUrl.pathname}${photoUrl.search}`;
}

export async function listRecords(query: {
  status?: RecordStatus;
  stage?: RecordStage;
  search?: string;
  page?: number;
  limit?: number;
}): Promise<RecordsResponse> {
  const response = await request(
    buildUrl("/records", {
      status: query.status,
      stage: query.stage,
      search: query.search,
      page: query.page,
      limit: query.limit,
    }),
  );

  return parseResponse<RecordsResponse>(response);
}

export async function getRecord(id: string): Promise<CandidateRecord> {
  const response = await request(buildUrl(`/records/${id}`));
  return parseResponse<CandidateRecord>(response);
}

export async function createRecord(
  payload: RecordCreatePayload,
): Promise<CandidateRecord> {
  const response = await request(buildUrl("/records"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await parseResponse<CandidateRecord | { data: CandidateRecord }>(
    response,
  );
  if ("data" in parsed) {
    return parsed.data;
  }
  return parsed;
}

export async function patchRecord(
  id: string,
  payload: { status?: RecordStatus; stage?: RecordStage },
): Promise<CandidateRecord> {
  const response = await request(buildUrl(`/records/${id}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse<CandidateRecord>(response);
}

export async function putRecord(
  id: string,
  payload: RecordReplacePayload,
): Promise<CandidateRecord> {
  const response = await request(buildUrl(`/records/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse<CandidateRecord>(response);
}

export async function deleteRecord(id: string): Promise<void> {
  await request(buildUrl(`/records/${id}`), {
    method: "DELETE",
  });
}

export async function listNotes(recordId: string): Promise<Note[]> {
  const response = await request(buildUrl(`/records/${recordId}/notes`));
  const parsed = await parseResponse<NotesResponse>(response);
  return parsed.data;
}

export async function createNote(recordId: string, content: string): Promise<Note> {
  const response = await request(buildUrl(`/records/${recordId}/notes`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  const parsed = await parseResponse<Note | { data: Note }>(response);
  if ("data" in parsed) {
    return parsed.data;
  }
  return parsed;
}

export async function deleteNote(recordId: string, noteId: string): Promise<void> {
  await request(buildUrl(`/records/${recordId}/notes/${noteId}`), {
    method: "DELETE",
  });
}

/** Sube la foto de perfil a la ruta local de la app. */
export async function uploadPhoto(recordId: string, file: File): Promise<void> {
  const formData = new FormData();
  formData.set("recordId", recordId);
  formData.set("photo", file);

  await request("/api/upload-photo", { method: "POST", body: formData });
}
