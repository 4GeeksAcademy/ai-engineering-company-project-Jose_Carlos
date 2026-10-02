"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, clearToken, getMe, isTokenExpired, useToken } from "../lib/auth";
import { Me } from "../lib/types";

type Session = {
  user: Me;
  setUser: (user: Me) => void;
  logout: () => void;
};

const SessionContext = createContext<Session | null>(null);

/** Sesión actual dentro de las vistas protegidas; null fuera de ellas (login, registro). */
export function useSession(): Session | null {
  return useContext(SessionContext);
}

/**
 * Guard de cliente para las vistas que requieren sesión. El middleware de Next no puede
 * leer localStorage, así que la comprobación se hace aquí: sin token, con token caducado
 * o si GET /auth/me responde 401, se limpia la sesión y se redirige a /login.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const token = useToken();
  const [user, setUser] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const loggingOut = useRef(false);

  const hasValidToken = typeof token === "string" && !isTokenExpired(token);

  // Sin token válido → /login (con ?next= para volver a la vista actual).
  useEffect(() => {
    if (token === undefined || hasValidToken) return;
    if (token) clearToken();
    if (loggingOut.current) {
      router.replace("/login");
      return;
    }
    const next = `${pathname}${window.location.search}`;
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [token, hasValidToken, pathname, router]);

  // Con token → validarlo contra la API y cargar el usuario.
  useEffect(() => {
    if (!hasValidToken) return;
    let cancelled = false;
    getMe()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        // Un 401 ya ha limpiado el token: el efecto anterior redirige.
        if (!cancelled && !(err instanceof ApiError && err.status === 401)) {
          setError(err instanceof Error ? err.message : "No se pudo comprobar la sesión.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hasValidToken, token, retryTick]);

  const logout = useCallback(() => {
    loggingOut.current = true;
    clearToken();
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cyan-50 p-6">
        <div className="max-w-md rounded-xl border border-red-200 bg-white p-6 text-center shadow-sm">
          <p className="mb-4 text-sm text-red-700">{error}</p>
          <button
            type="button"
            onClick={() => {
              setError(null);
              setRetryTick((tick) => tick + 1);
            }}
            className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white"
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  if (!hasValidToken || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-cyan-50 text-sm text-slate-600">
        Comprobando sesión...
      </div>
    );
  }

  return (
    <SessionContext.Provider value={{ user, setUser, logout }}>{children}</SessionContext.Provider>
  );
}
