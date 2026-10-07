import {
  formatDate,
  getStageLabel,
  getStatusLabel,
  STAGE_OPTIONS,
  STATUS_OPTIONS,
} from "../app/lib/constants";
import { RecordStage, RecordStatus, STAGE_VALUES, STATUS_VALUES } from "../app/lib/types";

// =========================================================
// formatDate
// =========================================================

describe("formatDate", () => {
  it("formats an ISO date in Spanish with day, month, year and time", () => {
    // Mediodía UTC: el día es el mismo en cualquier zona horaria habitual.
    const formatted = formatDate("2026-10-07T12:00:00Z");

    expect(formatted).toMatch(/\b7 oct\.? 2026\b/);
    expect(formatted).toMatch(/\d{1,2}:\d{2}/);
  });

  it("accepts a date without time", () => {
    expect(formatDate("2026-03-15")).toMatch(/1[45] mar\.? 2026/);
  });

  it("uses the local time of the viewer, not UTC text", () => {
    const iso = "2026-10-07T12:00:00Z";
    const localHour = String(new Date(iso).getHours());

    expect(formatDate(iso)).toContain(`${localHour}:00`);
  });

  it.each([
    ["an unreadable date", "not-a-date"],
    ["an empty string", ""],
    ["an impossible date", "2026-13-45T00:00:00Z"],
    ["a missing value", undefined as unknown as string],
  ])("shows a dash instead of 'Invalid Date' for %s", (_case, value) => {
    const formatted = formatDate(value);

    expect(formatted).toBe("—");
    expect(formatted).not.toMatch(/invalid/i);
  });
});

// =========================================================
// getStatusLabel / getStageLabel
// =========================================================

describe("getStatusLabel", () => {
  it.each([
    ["received", "Recibido"],
    ["in_progress", "En proceso"],
    ["selected", "Seleccionado"],
    ["discarded", "Descartado"],
  ] as Array<[RecordStatus, string]>)("translates %s to %s", (value, label) => {
    expect(getStatusLabel(value)).toBe(label);
  });

  it("falls back to the raw value for a status the UI does not know yet", () => {
    expect(getStatusLabel("archived" as RecordStatus)).toBe("archived");
  });

  it("does not confuse values that differ only in case", () => {
    expect(getStatusLabel("Received" as RecordStatus)).toBe("Received");
  });
});

describe("getStageLabel", () => {
  it.each([
    ["pending", "Pendiente"],
    ["review", "Revisión"],
    ["personal_interview", "Entrevista personal"],
    ["technical_interview", "Entrevista técnica"],
    ["offer_presented", "Oferta presentada"],
  ] as Array<[RecordStage, string]>)("translates %s to %s", (value, label) => {
    expect(getStageLabel(value)).toBe(label);
  });

  it("falls back to the raw value for a stage the UI does not know yet", () => {
    expect(getStageLabel("onboarding" as RecordStage)).toBe("onboarding");
  });

  it("does not resolve a status value as a stage", () => {
    expect(getStageLabel("received" as RecordStage)).toBe("received");
  });
});

// =========================================================
// STATUS_OPTIONS / STAGE_OPTIONS
// =========================================================

describe("select options", () => {
  it("offer one option per allowed value, in the same order", () => {
    expect(STATUS_OPTIONS.map((option) => option.value)).toEqual([...STATUS_VALUES]);
    expect(STAGE_OPTIONS.map((option) => option.value)).toEqual([...STAGE_VALUES]);
  });

  it("never show a raw value as a label", () => {
    for (const option of [...STATUS_OPTIONS, ...STAGE_OPTIONS]) {
      expect(option.label).not.toBe(option.value);
      expect(option.label).not.toContain("_");
    }
  });
});

// =========================================================
// AUTH_API_URL
// =========================================================

describe("AUTH_API_URL", () => {
  const original = process.env.NEXT_PUBLIC_AUTH_API_URL;

  function loadWith(value: string | undefined): string {
    if (value === undefined) delete process.env.NEXT_PUBLIC_AUTH_API_URL;
    else process.env.NEXT_PUBLIC_AUTH_API_URL = value;

    let url = "";
    jest.isolateModules(() => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      url = require("../app/lib/constants").AUTH_API_URL;
    });
    return url;
  }

  afterEach(() => {
    if (original === undefined) delete process.env.NEXT_PUBLIC_AUTH_API_URL;
    else process.env.NEXT_PUBLIC_AUTH_API_URL = original;
  });

  it("uses the configured API address", () => {
    expect(loadWith("https://api.trackflow.test")).toBe("https://api.trackflow.test");
  });

  it("drops a trailing slash so paths can be appended safely", () => {
    expect(loadWith("https://api.trackflow.test/")).toBe("https://api.trackflow.test");
  });

  it("falls back to the local API when nothing is configured", () => {
    expect(loadWith(undefined)).toBe("http://localhost:8000");
  });
});
