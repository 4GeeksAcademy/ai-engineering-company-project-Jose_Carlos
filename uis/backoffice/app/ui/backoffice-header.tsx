"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { WEBSITE_URL } from "../lib/constants";
import { useSession } from "./auth-guard";
import { useIncidentsLang } from "./incidents-lang";

type NavItem = {
  href: string;
  label: string;
  /** Clave de traducción en las pantallas bilingües de incidencias (sin ella, siempre en español). */
  i18nKey?: string;
  active: (pathname: string) => boolean;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Incidentes", i18nKey: "nav.analyzer", active: (p) => p === "/" },
  { href: "/incidents", label: "Gestor de incidencias", i18nKey: "nav.manager", active: (p) => p === "/incidents" },
  { href: "/incidents/new", label: "Registrar incidencia", i18nKey: "nav.new", active: (p) => p === "/incidents/new" },
  { href: "/suppliers", label: "Proveedores", i18nKey: "nav.suppliers", active: (p) => p.startsWith("/suppliers") },
  { href: "/inventory/products", label: "Inventario", active: (p) => p.startsWith("/inventory") },
  { href: "/talent", label: "Talent Pipeline", active: (p) => p.startsWith("/talent") },
];

// Pantallas con selector de idioma (español / inglés).
const BILINGUAL_PATHS = ["/incidents", "/incidents/new"];

const LINK_CLASS = "rounded-lg px-3 py-2 text-slate-600 transition hover:bg-cyan-50 hover:text-cyan-800";
const ACTIVE_LINK_CLASS = "rounded-lg bg-cyan-50 px-3 py-2 text-cyan-800";
const OUTLINE_BUTTON =
  "rounded-lg border border-cyan-300 bg-white px-3 py-1.5 text-sm font-semibold text-cyan-800 transition hover:bg-cyan-50 focus:outline-none focus:ring-4 focus:ring-cyan-200";

/** Cabecera común de todas las pantallas con sesión: secciones del backoffice, cuenta y salida. */
export function BackofficeHeader() {
  const pathname = usePathname();
  const session = useSession();
  const { t, toggleLang } = useIncidentsLang();
  const bilingual = BILINGUAL_PATHS.includes(pathname);
  const label = (item: NavItem) => (bilingual && item.i18nKey ? t(item.i18nKey) : item.label);

  return (
    <header className="border-b border-cyan-100 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-6">
        <a href={WEBSITE_URL} className="text-2xl font-extrabold tracking-tight text-cyan-700">
          TrackFlow
        </a>
        <nav aria-label="Secciones del backoffice" className="flex flex-wrap gap-1 text-sm font-semibold">
          {NAV_ITEMS.map((item) => {
            const active = item.active(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={active ? ACTIVE_LINK_CLASS : LINK_CLASS}
              >
                {label(item)}
              </Link>
            );
          })}
        </nav>
        <div className="flex flex-wrap items-center gap-2">
          {bilingual ? (
            <button type="button" data-lang-toggle onClick={toggleLang} className={OUTLINE_BUTTON}>
              {t("nav.switchLang")}
            </button>
          ) : (
            <span className="rounded-full bg-cyan-100 px-3 py-1 text-xs font-bold uppercase tracking-wide text-cyan-800">
              Backoffice
            </span>
          )}
          {session && (
            <Link
              href="/account/profile"
              title="Mi perfil"
              className="max-w-[12rem] truncate rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-cyan-50"
            >
              {session.user.profile?.name || session.user.email}
            </Link>
          )}
          <button type="button" data-logout onClick={session?.logout} className={OUTLINE_BUTTON}>
            {bilingual ? t("nav.logout") : "Cerrar sesión"}
          </button>
        </div>
      </div>
    </header>
  );
}
