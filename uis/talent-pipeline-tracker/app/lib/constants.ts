import { RecordStage, RecordStatus, STAGE_VALUES, STATUS_VALUES } from "./types";

export const API_BASE_URL = "https://playground.4geeks.com/tracker/api/v1";

export const STATUS_OPTIONS: Array<{ value: RecordStatus; label: string }> =
  STATUS_VALUES.map((value) => ({
    value,
    label:
      {
        received: "Recibido",
        in_progress: "En proceso",
        selected: "Seleccionado",
        discarded: "Descartado",
      }[value] ?? value,
  }));

export const STAGE_OPTIONS: Array<{ value: RecordStage; label: string }> =
  STAGE_VALUES.map((value) => ({
    value,
    label:
      {
        pending: "Pendiente",
        review: "Revisión",
        personal_interview: "Entrevista personal",
        technical_interview: "Entrevista técnica",
        offer_presented: "Oferta presentada",
      }[value] ?? value,
  }));

export function getStatusLabel(value: RecordStatus): string {
  return STATUS_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function getStageLabel(value: RecordStage): string {
  return STAGE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function formatDate(value: string): string {
  return new Date(value).toLocaleString("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
