"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, FieldErrors, register } from "../../lib/auth";
import { FormField } from "../../ui/form-field";

type RegisterForm = {
  email: string;
  password: string;
  confirmPassword: string;
  name: string;
  phone: string;
  address: string;
};

const EMPTY_FORM: RegisterForm = {
  email: "",
  password: "",
  confirmPassword: "",
  name: "",
  phone: "",
  address: "",
};

const MIN_PASSWORD_LENGTH = 8;

function validate(form: RegisterForm): FieldErrors {
  const errors: FieldErrors = {};
  if (!form.email.trim()) errors.email = "Este campo es obligatorio.";
  if (form.password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`;
  }
  if (form.confirmPassword !== form.password) {
    errors.confirmPassword = "Las contraseñas no coinciden.";
  }
  return errors;
}

// Campo opcional vacío → no se envía (el perfil se crea con null).
function optional(value: string): string | undefined {
  return value.trim() || undefined;
}

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState<RegisterForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  function update(field: keyof RegisterForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const clientErrors = validate(form);
    setFieldErrors(clientErrors);
    if (Object.keys(clientErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      // POST /users (con el perfil inicial) + POST /auth/login → token en localStorage.
      await register({
        email: form.email.trim(),
        password: form.password,
        name: optional(form.name),
        phone: optional(form.phone),
        address: optional(form.address),
      });
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la cuenta.");
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-slate-800">Crear cuenta</h1>
      <p className="mb-6 text-sm text-slate-600">Los datos de contacto son opcionales.</p>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField
          label="Email *"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={(event) => update("email", event.target.value)}
          error={fieldErrors.email}
        />
        <FormField
          label="Contraseña *"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={form.password}
          onChange={(event) => update("password", event.target.value)}
          error={fieldErrors.password}
        />
        <FormField
          label="Repite la contraseña *"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
          required
          value={form.confirmPassword}
          onChange={(event) => update("confirmPassword", event.target.value)}
          error={fieldErrors.confirmPassword}
        />
        <FormField
          label="Nombre"
          name="name"
          autoComplete="name"
          value={form.name}
          onChange={(event) => update("name", event.target.value)}
          error={fieldErrors.name}
        />
        <FormField
          label="Teléfono"
          name="phone"
          type="tel"
          autoComplete="tel"
          value={form.phone}
          onChange={(event) => update("phone", event.target.value)}
          error={fieldErrors.phone}
        />
        <FormField
          label="Dirección"
          name="address"
          autoComplete="street-address"
          value={form.address}
          onChange={(event) => update("address", event.target.value)}
          error={fieldErrors.address}
        />

        {error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {isSubmitting ? "Creando cuenta..." : "Crear cuenta"}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-slate-600">
        ¿Ya tienes cuenta?{" "}
        <Link href="/login" className="font-semibold text-cyan-700 hover:underline">
          Inicia sesión
        </Link>
      </p>
    </>
  );
}
