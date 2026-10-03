"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ApiError, FieldErrors, forgotPassword } from "../../lib/auth";
import { FormField } from "../../ui/form-field";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Tras el envío el formulario queda desactivado: evita peticiones duplicadas.
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || sent) return;

    setError(null);
    setFieldErrors({});
    if (!email.trim()) {
      setFieldErrors({ email: "Este campo es obligatorio." });
      return;
    }

    setIsSubmitting(true);
    try {
      await forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length > 0) {
        setFieldErrors(err.fieldErrors);
      } else {
        setError(err instanceof Error ? err.message : "No se pudo enviar la solicitud.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-slate-800">Recuperar contraseña</h1>
      <p className="mb-6 text-sm text-slate-600">
        Escribe tu email y te enviaremos un enlace para elegir una contraseña nueva.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
          disabled={sent}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={fieldErrors.email}
          className="disabled:bg-slate-100 disabled:text-slate-500"
        />

        {error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        {sent && (
          // Mismo mensaje exista o no la dirección: no revela qué emails están registrados.
          <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            Si esa dirección está registrada, recibirás un enlace en breve. Revisa también la
            carpeta de spam.
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting || sent}
          className="w-full rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {sent ? "Enlace solicitado" : isSubmitting ? "Enviando..." : "Enviar enlace"}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-600">
        <Link href="/login" className="font-semibold text-cyan-700 hover:underline">
          Volver a iniciar sesión
        </Link>
      </p>
    </>
  );
}
