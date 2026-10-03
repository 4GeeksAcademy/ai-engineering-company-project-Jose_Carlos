"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ApiError, changePassword, FieldErrors } from "../../../lib/auth";
import { FormField } from "../../../ui/form-field";
import { TrackflowHeader } from "../../../ui/trackflow-header";

type PasswordForm = { currentPassword: string; newPassword: string; confirmPassword: string };

const EMPTY_FORM: PasswordForm = { currentPassword: "", newPassword: "", confirmPassword: "" };
const MIN_PASSWORD_LENGTH = 8;

// Las claves coinciden con los campos de la API para poder mezclar sus errores de validación.
function validate(form: PasswordForm): FieldErrors {
  const errors: FieldErrors = {};
  if (!form.currentPassword) errors.current_password = "Este campo es obligatorio.";
  if (form.newPassword.length < MIN_PASSWORD_LENGTH) {
    errors.new_password = `Debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`;
  }
  if (form.confirmPassword !== form.newPassword) {
    errors.confirmPassword = "Las contraseñas no coinciden.";
  }
  return errors;
}

export default function ChangePasswordPage() {
  const [form, setForm] = useState<PasswordForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  function update(field: keyof PasswordForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setSaved(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaved(false);

    // La confirmación se comprueba antes de llamar a la API.
    const clientErrors = validate(form);
    setFieldErrors(clientErrors);
    if (Object.keys(clientErrors).length > 0) return;

    setIsSaving(true);
    try {
      await changePassword(form.currentPassword, form.newPassword);
      setForm(EMPTY_FORM);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cambiar la contraseña.");
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-cyan-50 text-slate-800">
      <TrackflowHeader />

      <main className="mx-auto max-w-2xl px-4 pb-10 pt-24 md:px-6">
        <Link href="/account/profile" className="mb-4 inline-block text-sm font-semibold text-cyan-700 hover:underline">
          ← Volver a mi perfil
        </Link>

        <section className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm md:p-8">
          <h1 className="mb-6 text-2xl font-bold text-slate-800">Cambiar contraseña</h1>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <FormField
              label="Contraseña actual"
              name="current_password"
              type="password"
              autoComplete="current-password"
              required
              value={form.currentPassword}
              onChange={(event) => update("currentPassword", event.target.value)}
              error={fieldErrors.current_password}
            />
            <FormField
              label="Nueva contraseña"
              name="new_password"
              type="password"
              autoComplete="new-password"
              required
              minLength={MIN_PASSWORD_LENGTH}
              value={form.newPassword}
              onChange={(event) => update("newPassword", event.target.value)}
              error={fieldErrors.new_password}
            />
            <FormField
              label="Repite la nueva contraseña"
              name="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              value={form.confirmPassword}
              onChange={(event) => update("confirmPassword", event.target.value)}
              error={fieldErrors.confirmPassword}
            />

            {error && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}
            {saved && (
              <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                Contraseña actualizada.
              </p>
            )}

            <button
              type="submit"
              disabled={isSaving}
              className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {isSaving ? "Guardando..." : "Cambiar contraseña"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
