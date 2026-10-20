import {
  createNote,
  createRecord,
  deleteNote,
  deleteRecord,
  getPhotoUrl,
  getRecord,
  isNotFoundError,
  listNotes,
  listRecords,
  patchRecord,
  putRecord,
  RecordsApiError,
  toUserMessage,
  uploadPhoto,
} from "../app/lib/api";
import { API_BASE_URL } from "../app/lib/constants";
import { CandidateRecord, Note, RecordReplacePayload } from "../app/lib/types";

// =========================================================
// UTILIDADES DE PRUEBA
// =========================================================

const SERVER_MESSAGE = "Ha ocurrido un problema en el servidor. Inténtalo de nuevo en unos minutos.";

const RECORD: CandidateRecord = {
  id: "rec-1",
  full_name: "Ana García",
  email: "ana@example.com",
  phone: "+34 600 000 001",
  position: "Operaria de almacén",
  linkedin_url: null,
  cv_url: null,
  status: "received",
  stage: "pending",
  experience_years: 3,
  notes_count: 0,
  applied_at: "2026-10-01T08:00:00Z",
  updated_at: "2026-10-01T08:00:00Z",
};

const NOTE: Note = {
  id: "note-1",
  record_id: "rec-1",
  content: "Buena entrevista",
  created_at: "2026-10-02T09:00:00Z",
};

/** Respuesta mínima de fetch: el código solo usa `ok`, `status` y `json()`. */
function apiResponse(status: number, body?: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === undefined) throw new SyntaxError("Unexpected end of JSON input");
      return body;
    },
  } as Response;
}

const fetchMock = jest.fn<Promise<Response>, [string, RequestInit]>();

function lastCall() {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return {
    url: new URL(url, "http://app.test"),
    init,
    body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
  };
}

async function rejection(promise: Promise<unknown>): Promise<RecordsApiError> {
  const error = await promise.then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(RecordsApiError);
  return error as RecordsApiError;
}

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock as unknown as typeof fetch;
});

// =========================================================
// ERRORES: RecordsApiError, isNotFoundError, toUserMessage
// =========================================================

describe("RecordsApiError", () => {
  it.each([
    ["network", "No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo."],
    ["not_found", "No se ha encontrado. Puede que se haya eliminado."],
    ["validation", "Los datos enviados no son válidos. Revísalos e inténtalo de nuevo."],
    ["server", SERVER_MESSAGE],
  ] as const)("carries a user-facing message for %s", (kind, message) => {
    const error = new RecordsApiError(kind, 418);

    expect(error.message).toBe(message);
    expect(error.kind).toBe(kind);
    // El código de estado va en el objeto, nunca en el texto que ve el usuario.
    expect(error.status).toBe(418);
    expect(error.message).not.toContain("418");
  });

  it("defaults the status to 0 when there was no response", () => {
    expect(new RecordsApiError("network").status).toBe(0);
  });
});

describe("isNotFoundError", () => {
  it("is true for a not-found API error", () => {
    expect(isNotFoundError(new RecordsApiError("not_found", 404))).toBe(true);
  });

  it.each([
    ["another kind of API error", new RecordsApiError("server", 500)],
    ["a plain Error that mentions 404", new Error("404 not found")],
    ["an object shaped like the error", { kind: "not_found", status: 404 }],
    ["null", null],
    ["undefined", undefined],
  ])("is false for %s", (_case, value) => {
    expect(isNotFoundError(value)).toBe(false);
  });
});

describe("toUserMessage", () => {
  it("returns the message of an API error", () => {
    expect(toUserMessage(new RecordsApiError("validation", 422))).toBe(
      "Los datos enviados no son válidos. Revísalos e inténtalo de nuevo.",
    );
  });

  it.each([
    ["a browser error", new TypeError("Failed to fetch")],
    ["a thrown string", "boom"],
    ["null", null],
    ["undefined", undefined],
  ])("hides the technical detail of %s behind the generic message", (_case, value) => {
    expect(toUserMessage(value)).toBe(SERVER_MESSAGE);
  });
});

// =========================================================
// getPhotoUrl
// =========================================================

describe("getPhotoUrl", () => {
  it("builds the local photo route for a record", () => {
    expect(getPhotoUrl("rec-1")).toBe("/api/profile-photo/rec-1");
  });

  it("adds the version so the browser reloads a replaced photo", () => {
    expect(getPhotoUrl("rec-1", 1730000000000)).toBe("/api/profile-photo/rec-1?v=1730000000000");
  });

  it.each([
    ["version 0", 0],
    ["no version", undefined],
  ])("omits the parameter with %s", (_case, version) => {
    expect(getPhotoUrl("rec-1", version)).toBe("/api/profile-photo/rec-1");
  });

  it("returns a relative path, never an absolute URL", () => {
    expect(getPhotoUrl("rec-1", 5)).not.toContain("localhost");
  });
});

// =========================================================
// listRecords (construcción de la URL)
// =========================================================

describe("listRecords", () => {
  const page = { total: 1, page: 1, limit: 10, data: [RECORD] };

  it("requests the records and returns the parsed page", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, page));

    await expect(listRecords({})).resolves.toEqual(page);

    expect(lastCall().url.href).toBe(`${API_BASE_URL}/records`);
  });

  it("sends every filter that has a value", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, page));

    await listRecords({ status: "received", stage: "review", search: "ana", page: 2, limit: 25 });

    expect(Object.fromEntries(lastCall().url.searchParams)).toEqual({
      status: "received",
      stage: "review",
      search: "ana",
      page: "2",
      limit: "25",
    });
  });

  it("leaves out empty and undefined filters", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, page));

    await listRecords({ status: undefined, search: "", page: 1 });

    expect(Object.fromEntries(lastCall().url.searchParams)).toEqual({ page: "1" });
  });

  it("encodes a search with spaces, accents and reserved characters", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, page));

    await listRecords({ search: "José & María #1" });

    const { url } = lastCall();
    expect(url.searchParams.get("search")).toBe("José & María #1");
    expect([...url.searchParams.keys()]).toEqual(["search"]);
    expect(url.hash).toBe("");
  });

  it("sets a timeout on the request", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, page));

    await listRecords({});

    expect(lastCall().init.signal).toBeInstanceOf(AbortSignal);
  });
});

// =========================================================
// Manejo de respuestas (común a todas las llamadas)
// =========================================================

describe("response handling", () => {
  it.each([
    [404, "not_found"],
    [400, "validation"],
    [422, "validation"],
    [401, "server"],
    [409, "server"],
    [500, "server"],
    [503, "server"],
  ] as const)("turns a %i response into a %s error", async (status, kind) => {
    fetchMock.mockResolvedValue(apiResponse(status, { detail: "technical detail" }));

    const error = await rejection(getRecord("rec-1"));

    expect(error.kind).toBe(kind);
    expect(error.status).toBe(status);
    expect(error.message).not.toContain("technical detail");
  });

  it("reports a network error when fetch itself fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await rejection(getRecord("rec-1"));

    expect(error.kind).toBe("network");
    expect(error.status).toBe(0);
    expect(error.message).not.toContain("Failed to fetch");
  });

  it("reports a network error when the request times out", async () => {
    fetchMock.mockRejectedValue(new DOMException("The operation timed out.", "TimeoutError"));

    expect((await rejection(listRecords({}))).kind).toBe("network");
  });

  it("reports a server error when a successful response is not JSON", async () => {
    fetchMock.mockResolvedValue(apiResponse(200));

    const error = await rejection(getRecord("rec-1"));

    expect(error.kind).toBe("server");
    expect(error.status).toBe(200);
  });

  it("checks the status before trying to read the body", async () => {
    // Un 404 con cuerpo ilegible sigue siendo un "no encontrado".
    fetchMock.mockResolvedValue(apiResponse(404));

    expect(isNotFoundError(await rejection(getRecord("missing")))).toBe(true);
  });
});

// =========================================================
// Candidaturas
// =========================================================

describe("getRecord", () => {
  it("requests the record by id and returns it", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, RECORD));

    await expect(getRecord("rec-1")).resolves.toEqual(RECORD);

    expect(lastCall().url.href).toBe(`${API_BASE_URL}/records/rec-1`);
  });

  it("rejects with a not-found error for an unknown id", async () => {
    fetchMock.mockResolvedValue(apiResponse(404, { detail: "Not found" }));

    expect(isNotFoundError(await rejection(getRecord("missing")))).toBe(true);
  });
});

describe("createRecord", () => {
  const payload = {
    full_name: "Ana García",
    email: "ana@example.com",
    phone: "+34 600 000 001",
    position: "Operaria de almacén",
    experience_years: 3,
  };

  it("posts the payload as JSON and returns the created record", async () => {
    fetchMock.mockResolvedValue(apiResponse(201, RECORD));

    await expect(createRecord(payload)).resolves.toEqual(RECORD);

    const { url, init, body } = lastCall();
    expect(url.href).toBe(`${API_BASE_URL}/records`);
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(body).toEqual(payload);
  });

  it("unwraps a record that arrives inside { data }", async () => {
    fetchMock.mockResolvedValue(apiResponse(201, { data: RECORD }));

    await expect(createRecord(payload)).resolves.toEqual(RECORD);
  });

  it("rejects with a validation error when the API refuses the data", async () => {
    fetchMock.mockResolvedValue(apiResponse(422, { detail: [{ loc: ["body", "email"] }] }));

    const error = await rejection(createRecord(payload));

    expect(error.kind).toBe("validation");
    expect(toUserMessage(error)).toBe("Los datos enviados no son válidos. Revísalos e inténtalo de nuevo.");
  });
});

describe("patchRecord", () => {
  it("patches only the given fields", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { ...RECORD, status: "selected" }));

    const updated = await patchRecord("rec-1", { status: "selected" });

    const { url, init, body } = lastCall();
    expect(updated.status).toBe("selected");
    expect(url.href).toBe(`${API_BASE_URL}/records/rec-1`);
    expect(init.method).toBe("PATCH");
    expect(body).toEqual({ status: "selected" });
  });

  it("rejects with a not-found error when the record is gone", async () => {
    fetchMock.mockResolvedValue(apiResponse(404));

    expect((await rejection(patchRecord("rec-1", { stage: "review" }))).kind).toBe("not_found");
  });
});

describe("putRecord", () => {
  const payload: RecordReplacePayload = {
    full_name: "Ana García López",
    email: "ana@example.com",
    phone: "+34 600 000 001",
    position: "Jefa de turno",
    experience_years: 4,
    status: "in_progress",
    stage: "review",
  };

  it("replaces the record with the full payload", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { ...RECORD, ...payload }));

    const updated = await putRecord("rec-1", payload);

    const { init, body } = lastCall();
    expect(updated.position).toBe("Jefa de turno");
    expect(init.method).toBe("PUT");
    expect(body).toEqual(payload);
  });

  it("rejects with a validation error on a 400", async () => {
    fetchMock.mockResolvedValue(apiResponse(400));

    expect((await rejection(putRecord("rec-1", payload))).kind).toBe("validation");
  });
});

describe("deleteRecord", () => {
  it("resolves without reading a body", async () => {
    fetchMock.mockResolvedValue(apiResponse(204));

    await expect(deleteRecord("rec-1")).resolves.toBeUndefined();

    const { url, init } = lastCall();
    expect(url.href).toBe(`${API_BASE_URL}/records/rec-1`);
    expect(init.method).toBe("DELETE");
  });

  it("rejects when the server fails", async () => {
    fetchMock.mockResolvedValue(apiResponse(500));

    expect((await rejection(deleteRecord("rec-1"))).kind).toBe("server");
  });
});

// =========================================================
// Notas
// =========================================================

describe("listNotes", () => {
  it("returns the notes inside the response envelope", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { data: [NOTE], meta: { total: 1 } }));

    await expect(listNotes("rec-1")).resolves.toEqual([NOTE]);

    expect(lastCall().url.href).toBe(`${API_BASE_URL}/records/rec-1/notes`);
  });

  it("returns an empty list for a record without notes", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { data: [], meta: { total: 0 } }));

    await expect(listNotes("rec-1")).resolves.toEqual([]);
  });

  it("rejects with a not-found error for an unknown record", async () => {
    fetchMock.mockResolvedValue(apiResponse(404));

    expect((await rejection(listNotes("missing"))).kind).toBe("not_found");
  });
});

describe("createNote", () => {
  it("posts the content and returns the created note", async () => {
    fetchMock.mockResolvedValue(apiResponse(201, NOTE));

    await expect(createNote("rec-1", "Buena entrevista")).resolves.toEqual(NOTE);

    const { url, init, body } = lastCall();
    expect(url.href).toBe(`${API_BASE_URL}/records/rec-1/notes`);
    expect(init.method).toBe("POST");
    expect(body).toEqual({ content: "Buena entrevista" });
  });

  it("unwraps a note that arrives inside { data }", async () => {
    fetchMock.mockResolvedValue(apiResponse(201, { data: NOTE }));

    await expect(createNote("rec-1", "Buena entrevista")).resolves.toEqual(NOTE);
  });

  it("rejects with a validation error for an empty note", async () => {
    fetchMock.mockResolvedValue(apiResponse(422));

    expect((await rejection(createNote("rec-1", ""))).kind).toBe("validation");
  });
});

describe("deleteNote", () => {
  it("deletes the note of the record", async () => {
    fetchMock.mockResolvedValue(apiResponse(204));

    await expect(deleteNote("rec-1", "note-1")).resolves.toBeUndefined();

    const { url, init } = lastCall();
    expect(url.href).toBe(`${API_BASE_URL}/records/rec-1/notes/note-1`);
    expect(init.method).toBe("DELETE");
  });

  it("rejects with a not-found error when the note is already gone", async () => {
    fetchMock.mockResolvedValue(apiResponse(404));

    expect((await rejection(deleteNote("rec-1", "note-1"))).kind).toBe("not_found");
  });
});

// =========================================================
// Foto de perfil
// =========================================================

describe("uploadPhoto", () => {
  const photo = new File(["fake-image"], "ana.png", { type: "image/png" });

  it("sends the record id and the file to the local upload route", async () => {
    fetchMock.mockResolvedValue(apiResponse(200, { ok: true }));

    await expect(uploadPhoto("rec-1", photo)).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0];
    const form = init.body as FormData;
    expect(url).toBe("/api/upload-photo");
    expect(init.method).toBe("POST");
    expect(form.get("recordId")).toBe("rec-1");
    expect((form.get("photo") as File).name).toBe("ana.png");
    // Sin Content-Type manual: el navegador añade el boundary del multipart.
    expect(init.headers).toBeUndefined();
  });

  it("rejects with a validation error when the file is refused", async () => {
    fetchMock.mockResolvedValue(apiResponse(400, { error: "Formato no permitido" }));

    const error = await rejection(uploadPhoto("rec-1", photo));

    expect(error.kind).toBe("validation");
    expect(error.message).not.toContain("Formato no permitido");
  });

  it("rejects with a network error when the upload cannot be sent", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    expect((await rejection(uploadPhoto("rec-1", photo))).kind).toBe("network");
  });
});
