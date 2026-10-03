"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, clearToken, FieldErrors, resetPassword } from "../../lib/auth";
import { FormField } from "../../ui/form-field";

const MIN_PASSWORD_LENGTH = 8;

// useSearchParams necesita un límite de Suspense para no forzar el render en cliente de toda la página.
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ForgotPasswordLink({ children }: { children: string }) {
  return (
    <Link href="/forgot-password" className="font-semibold text-cyan-700 hover:underline">
      {children}
    </Link>
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  // El token llega en el enlace del correo: /reset-password?token=...
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tokenRejected, setTokenRejected] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!token) {
    return (
      <>
        <h1 className="mb-4 text-2xl font-bold text-slate-800">Nueva contraseña</h1>
        <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          Falta el token de restablecimiento. Abre el enlace del correo o pide uno nuevo.
        </p>
        <p className="text-sm">
          <ForgotPasswordLink>Solicitar un nuevo enlace</ForgotPasswordLink>
        </p>
      </>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setTokenRejected(false);

    const clientErrors: FieldErrors = {};
    if (password.length < MIN_PASSWORD_LENGTH) {
      clientErrors.new_password = `Debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`;
    }
    if (confirmPassword !== password) {
      clientErrors.confirmPassword = "Las contraseñas no coinciden.";
    }
    setFieldErrors(clientErrors);
    if (Object.keys(clientErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      await resetPassword(token, password);
      // Cualquier sesión abierta en este navegador se cierra: se entra con la nueva contraseña.
      clearToken();
      router.replace("/login?reset=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo restablecer la contraseña.");
      if (err instanceof ApiError) {
        setFieldErrors(err.fieldErrors);
        setTokenRejected(err.status === 400);
      }
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-slate-800">Nueva contraseña</h1>
      <p className="mb-6 text-sm text-slate-600">Elige la contraseña con la que entrarás a partir de ahora.</p>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField
          label="Nueva contraseña"
          name="new_password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={fieldErrors.new_password}
        />
        <FormField
          label="Repite la nueva contraseña"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
          required
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          error={fieldErrors.confirmPassword}
        />

        {error && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <p>{error}</p>
            {tokenRejected && (
              <p className="mt-1">
                <ForgotPasswordLink>Solicitar un nuevo enlace</ForgotPasswordLink>
              </p>
            )}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {isSubmitting ? "Guardando..." : "Guardar nueva contraseña"}
        </button>
      </form>
    </>
  );
}
