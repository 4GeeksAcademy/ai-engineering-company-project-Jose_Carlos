"use client";

import Link from "next/link";
import { useSession } from "./auth-guard";

export function TrackflowHeader() {
  const session = useSession();

  return (
    <header className="fixed top-0 z-50 w-full border-b border-cyan-100 bg-white/95 backdrop-blur">
      <nav
        className={`relative mx-auto flex max-w-7xl items-center gap-2 px-4 py-3 md:px-6 ${
          session ? "justify-between" : "justify-center"
        }`}
        aria-label="Navegacion principal"
      >
        <Link
          href="/"
          className="text-2xl font-extrabold tracking-tight text-cyan-700"
        >
          TrackFlow
        </Link>

        {session && (
          <div className="flex items-center gap-2">
            <Link
              href="/account/profile"
              className="hidden max-w-[16rem] truncate rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-cyan-50 sm:block"
              title="Mi perfil"
            >
              {session.user.profile?.name || session.user.email}
            </Link>
            <Link
              href="/account/profile"
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-cyan-700 hover:bg-cyan-50 sm:hidden"
            >
              Perfil
            </Link>
            <button
              type="button"
              onClick={session.logout}
              className="rounded-lg border border-cyan-200 px-3 py-1.5 text-sm font-semibold text-cyan-700"
            >
              Cerrar sesión
            </button>
          </div>
        )}
      </nav>
    </header>
  );
}
