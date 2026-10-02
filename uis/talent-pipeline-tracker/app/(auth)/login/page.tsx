"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, FieldErrors, getNextPath, login } from "../../lib/auth";
import { FormField } from "../../ui/form-field";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setFieldErrors({});
    try {
      await login(email.trim(), password);
      router.replace(getNextPath());
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión.");
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-slate-800">Iniciar sesión</h1>
      <p className="mb-6 text-sm text-slate-600">Accede para gestionar las candidaturas.</p>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={fieldErrors.email}
        />
        <FormField
          label="Contraseña"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={fieldErrors.password}
        />

        {error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !email || !password}
          className="w-full rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {isSubmitting ? "Entrando..." : "Entrar"}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-600">
        ¿No tienes cuenta?{" "}
        <Link href="/register" className="font-semibold text-cyan-700 hover:underline">
          Regístrate
        </Link>
      </p>
    </>
  );
}
