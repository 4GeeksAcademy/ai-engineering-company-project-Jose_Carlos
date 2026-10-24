"use client";

import { FormEvent } from "react";
import { STAGE_OPTIONS, STATUS_OPTIONS } from "../lib/constants";
import { RecordStage, RecordStatus } from "../lib/types";

// Formulario "Nueva candidatura" del Talent Pipeline. Solo se ve al pulsar el botón, así que
// home-client.tsx lo carga con next/dynamic: su código no viaja en la carga inicial de /talent.
// El estado sigue en HomeClient; aquí solo se pinta.

export type CreateFormState = {
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

type Props = {
  form: CreateFormState;
  error: string | null;
  isSubmitting: boolean;
  onChange: (field: keyof CreateFormState, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function CandidateCreateForm({ form, error, isSubmitting, onChange, onSubmit }: Props) {
  return (
    <form onSubmit={onSubmit} className="mt-4 space-y-3">
      <input
        required
        value={form.full_name}
        onChange={(event) =>
          onChange("full_name", event.target.value)
        }
        placeholder="Nombre completo"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        required
        type="email"
        value={form.email}
        onChange={(event) => onChange("email", event.target.value)}
        placeholder="Email"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        required
        value={form.phone}
        onChange={(event) => onChange("phone", event.target.value)}
        placeholder="Teléfono"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        required
        value={form.position}
        onChange={(event) =>
          onChange("position", event.target.value)
        }
        placeholder="Posición"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        required
        type="number"
        min="0"
        value={form.experience_years}
        onChange={(event) =>
          onChange("experience_years", event.target.value)
        }
        placeholder="Años de experiencia"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        value={form.linkedin_url}
        onChange={(event) =>
          onChange("linkedin_url", event.target.value)
        }
        placeholder="LinkedIn (opcional)"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <input
        value={form.cv_url}
        onChange={(event) => onChange("cv_url", event.target.value)}
        placeholder="CV URL (opcional)"
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      />
      <select
        value={form.status}
        onChange={(event) =>
          onChange("status", event.target.value)
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
        value={form.stage}
        onChange={(event) =>
          onChange("stage", event.target.value)
        }
        className="w-full rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
      >
        {STAGE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          No se pudo crear la candidatura. {error}
        </p>
      )}

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full rounded-lg bg-cyan-800 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
      >
        {isSubmitting ? "Creando..." : "Crear candidatura"}
      </button>
    </form>
  );
}
