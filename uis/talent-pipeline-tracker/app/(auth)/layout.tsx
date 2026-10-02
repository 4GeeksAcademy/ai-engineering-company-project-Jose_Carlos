"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getNextPath, isTokenExpired, useToken } from "../lib/auth";
import { TrackflowHeader } from "../ui/trackflow-header";

// Vistas públicas de autenticación. Si ya hay una sesión válida, se vuelve a la app.
export default function AuthLayout({ children }: LayoutProps<"/">) {
  const router = useRouter();
  const token = useToken();
  const loggedIn = typeof token === "string" && !isTokenExpired(token);

  useEffect(() => {
    if (loggedIn) router.replace(getNextPath());
  }, [loggedIn, router]);

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
