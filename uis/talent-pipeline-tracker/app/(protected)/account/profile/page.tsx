"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, FieldErrors, getMe, updateMyProfile } from "../../../lib/auth";
import { Me } from "../../../lib/types";
import { useSession } from "../../../ui/auth-guard";
import { FormField } from "../../../ui/form-field";
import { TrackflowHeader } from "../../../ui/trackflow-header";

type ProfileForm = { name: string; phone: string; address: string };

const ROLE_LABELS: Record<Me["role"], string> = {
  admin: "Administrador",
  manager: "Manager",
  user: "Usuario",
};

function toForm(me: Me): ProfileForm {
  return {
    name: me.profile?.name ?? "",
    phone: me.profile?.phone ?? "",
    address: me.profile?.address ?? "",
  };
}

export default function ProfilePage() {
  const session = useSession();
  const [me, setMe] = useState<Me | null>(null);
  const [form, setForm] = useState<ProfileForm>({ name: "", phone: "", address: "" });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Datos frescos de GET /auth/me: email del User + Profile vinculado.
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((data) => {
        if (cancelled) return;
        setMe(data);
        setForm(toForm(data));
      })
      .catch((err: unknown) => {
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          setLoadError(err instanceof Error ? err.message : "No se pudo cargar tu perfil.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function update(field: keyof ProfileForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    setSaved(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!me) return;
    setIsSaving(true);
    setSaveError(null);
    setFieldErrors({});
    setSaved(false);
    try {
      const profile = await updateMyProfile({
        name: form.name.trim() || null,
        phone: form.phone.trim() || null,
        address: form.address.trim() || null,
      });
      const updated = { ...me, profile };
      setMe(updated);
      setForm(toForm(updated));
      session?.setUser(updated);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "No se pudo guardar el perfil.");
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-cyan-50 text-slate-800">
      <TrackflowHeader />

      <main className="mx-auto max-w-2xl px-4 pb-10 pt-24 md:px-6">
        <Link href="/" className="mb-4 inline-block text-sm font-semibold text-cyan-700 hover:underline">
          ← Volver a candidaturas
        </Link>

        <section className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm md:p-8">
          <h1 className="mb-6 text-2xl font-bold text-slate-800">Mi perfil</h1>

          {loadError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {loadError}
            </p>
          )}

          {!me && !loadError && <p className="text-sm text-slate-600">Cargando perfil...</p>}

          {me && (
            <>
              <dl className="mb-6 grid grid-cols-1 gap-4 rounded-xl bg-cyan-50 p-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Email</dt>
                  <dd className="break-all text-sm font-medium text-slate-800">{me.email}</dd>
                </div>
                <div>
                  <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Rol</dt>
                  <dd className="text-sm font-medium text-slate-800">{ROLE_LABELS[me.role]}</dd>
                </div>
              </dl>

              <form onSubmit={handleSubmit} className="space-y-4" noValidate>
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

                {saveError && (
                  <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    {saveError}
                  </p>
                )}
                {saved && (
                  <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                    Perfil actualizado.
                  </p>
                )}

                <button
                  type="submit"
                  disabled={isSaving}
                  className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                >
                  {isSaving ? "Guardando..." : "Guardar cambios"}
                </button>
              </form>

              <div className="mt-8 border-t border-cyan-100 pt-6">
                <h2 className="mb-1 text-lg font-bold text-slate-800">Seguridad</h2>
                <Link
                  href="/account/change-password"
                  className="text-sm font-semibold text-cyan-700 hover:underline"
                >
                  Cambiar contraseña
                </Link>
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}
