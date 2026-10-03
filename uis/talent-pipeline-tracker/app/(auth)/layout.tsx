"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getNextPath, isTokenExpired, useToken } from "../lib/auth";
import { TrackflowHeader } from "../ui/trackflow-header";

// Con sesión válida, login y registro devuelven a la app. Recuperar la contraseña
// sigue disponible aunque haya una sesión abierta (el enlace llega por correo).
const REDIRECT_WHEN_LOGGED_IN = ["/login", "/register"];

// Vistas públicas de autenticación.
export default function AuthLayout({ children }: LayoutProps<"/">) {
  const router = useRouter();
  const pathname = usePathname();
  const token = useToken();
  const loggedIn = typeof token === "string" && !isTokenExpired(token);

  useEffect(() => {
    if (loggedIn && REDIRECT_WHEN_LOGGED_IN.includes(pathname)) router.replace(getNextPath());
  }, [loggedIn, pathname, router]);

  return (
    <div className="min-h-screen bg-cyan-50 text-slate-800">
      <TrackflowHeader />
      <main className="mx-auto flex max-w-md flex-col px-4 pb-10 pt-28">
        <div className="rounded-2xl border border-cyan-100 bg-white p-6 shadow-sm md:p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
