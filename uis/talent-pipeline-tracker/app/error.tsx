"use client"; // Los límites de error deben ser componentes de cliente.

import { useEffect } from "react";
import Link from "next/link";

// Pantalla de respaldo cuando una vista falla al renderizar: evita la página de error por
// defecto y ofrece dos salidas (reintentar o volver al listado).
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    // El detalle queda en la consola; al usuario no se le muestra el mensaje técnico.
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-cyan-50 p-6">
      <div role="alert" className="max-w-md rounded-xl border border-red-200 bg-white p-6 text-center shadow-sm">
        <h1 className="mb-2 text-xl font-bold text-slate-900">Algo ha fallado</h1>
        <p className="mb-4 text-sm text-slate-600">
          No se pudo mostrar esta pantalla. Puedes intentarlo de nuevo o volver al listado.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => retry()}
            className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white"
          >
            Reintentar
          </button>
          <Link
            href="/"
            className="rounded-lg border border-cyan-200 bg-white px-4 py-2 text-sm font-semibold text-cyan-700"
          >
            Volver al listado
          </Link>
        </div>
      </div>
    </div>
  );
}
