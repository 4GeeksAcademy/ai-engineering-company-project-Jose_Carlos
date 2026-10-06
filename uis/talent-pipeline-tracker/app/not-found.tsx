import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-cyan-50 p-6">
      <div className="max-w-md rounded-xl border border-cyan-100 bg-white p-6 text-center shadow-sm">
        <h1 className="mb-2 text-xl font-bold text-slate-900">Página no encontrada</h1>
        <p className="mb-4 text-sm text-slate-600">La dirección no corresponde a ninguna pantalla.</p>
        <Link
          href="/"
          className="inline-flex rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white"
        >
          Volver al listado
        </Link>
      </div>
    </div>
  );
}
