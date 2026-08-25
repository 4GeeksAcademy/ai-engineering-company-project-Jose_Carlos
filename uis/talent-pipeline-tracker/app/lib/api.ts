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

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Error ${response.status}: ${response.statusText}`);
  }

  return (await response.json()) as T;
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
  const response = await fetch(
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
  const response = await fetch(buildUrl(`/records/${id}`));
  return parseResponse<CandidateRecord>(response);
}

export async function createRecord(
  payload: RecordCreatePayload,
): Promise<CandidateRecord> {
  const response = await fetch(buildUrl("/records"), {
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
  const response = await fetch(buildUrl(`/records/${id}`), {
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
  const response = await fetch(buildUrl(`/records/${id}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse<CandidateRecord>(response);
}

export async function deleteRecord(id: string): Promise<void> {
  const response = await fetch(buildUrl(`/records/${id}`), {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`Error ${response.status}: ${response.statusText}`);
  }
}

export async function listNotes(recordId: string): Promise<Note[]> {
  const response = await fetch(buildUrl(`/records/${recordId}/notes`));
  const parsed = await parseResponse<NotesResponse>(response);
  return parsed.data;
}

export async function createNote(recordId: string, content: string): Promise<Note> {
  const response = await fetch(buildUrl(`/records/${recordId}/notes`), {
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
  const response = await fetch(buildUrl(`/records/${recordId}/notes/${noteId}`), {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`Error ${response.status}: ${response.statusText}`);
  }
}
