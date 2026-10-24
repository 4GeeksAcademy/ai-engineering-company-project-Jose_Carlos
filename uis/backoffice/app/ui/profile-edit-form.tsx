"use client";

import { FormEvent } from "react";

// Formulario de edición del perfil de una candidatura. Solo aparece al pulsar "Editar", así
// que record-detail-client.tsx lo carga con next/dynamic. El estado sigue en el detalle.

export type EditFormState = {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  experience_years: string;
  linkedin_url: string;
  cv_url: string;
};

type Props = {
  form: EditFormState;
  error: string | null;
  isSaving: boolean;
  onChange: (field: keyof EditFormState, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
};

export function ProfileEditForm({ form, error, isSaving, onChange, onSubmit, onCancel }: Props) {
  return (
    <form onSubmit={onSubmit} className="grid gap-2">
      <input
        required
        value={form.full_name}
        onChange={(event) =>
          onChange("full_name", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="Nombre completo"
      />
      <input
        required
        type="email"
        value={form.email}
        onChange={(event) =>
          onChange("email", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="Email"
      />
      <input
        required
        value={form.phone}
        onChange={(event) =>
          onChange("phone", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="Teléfono"
      />
      <input
        required
        value={form.position}
        onChange={(event) =>
          onChange("position", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="Posición"
      />
      <input
        required
        type="number"
        min="0"
        value={form.experience_years}
        onChange={(event) =>
          onChange("experience_years", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="Años de experiencia"
      />
      <input
        value={form.linkedin_url}
        onChange={(event) =>
          onChange("linkedin_url", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="LinkedIn (opcional)"
      />
      <input
        value={form.cv_url}
        onChange={(event) =>
          onChange("cv_url", event.target.value)
        }
        className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-sm outline-none ring-cyan-200 focus:ring"
        placeholder="CV URL (opcional)"
      />

      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          No se pudo actualizar el perfil. {error}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={isSaving}
          className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {isSaving ? "Guardando..." : "Guardar cambios (PUT)"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-cyan-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}
