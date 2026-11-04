"use client";

// Telemetría de navegación y rendimiento, montada una vez en el layout raíz:
//
// - `page_viewed` en cada cambio de pantalla (ruta como plantilla, sección y pantalla anterior).
//   Se ignora la misma ruta repetida en menos de 2 s (re-renders y redirecciones del guard).
// - `page_load_recorded` con las Web Vitals de la carga completa (`useReportWebVitals`). Las
//   métricas llegan por separado y algunas (CLS, INP) solo al final, así que se acumulan y se
//   emite un único evento cuando la pestaña se oculta por primera vez.
//
// No pinta nada: es un componente aparte para que el layout raíz siga siendo de servidor.

import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { useEffect, useRef } from "react";
import { pageRoute, pageSection } from "../lib/telemetry-events";
import { telemetryService, track } from "../lib/telemetry";

const PAGE_VIEW_DEDUP_MS = 2_000;

type Vitals = { TTFB?: number; FCP?: number; LCP?: number; INP?: number; CLS?: number; navigationType?: string; route?: string };

// Fuera del componente: useReportWebVitals pide una referencia estable al callback.
const vitals: Vitals = {};
let vitalsSent = false;

const reportWebVitals: Parameters<typeof useReportWebVitals>[0] = (metric) => {
  if (["TTFB", "FCP", "LCP", "INP", "CLS"].includes(metric.name)) vitals[metric.name as keyof Vitals] = metric.value as never;
  vitals.navigationType ??= metric.navigationType;
  vitals.route ??= pageRoute(window.location.pathname);
};

function navigationType(type: string | undefined) {
  if (type === "reload") return "reload";
  if (type === "back-forward" || type === "back-forward-cache") return "back_forward";
  return "navigate";
}

function deviceClass() {
  const width = window.innerWidth;
  return width >= 1024 ? "desktop" : width >= 640 ? "tablet" : "mobile";
}

const ms = (value: number | undefined) => (typeof value === "number" ? Math.max(0, Math.round(value)) : null);

/** Emite `page_load_recorded` una sola vez por carga, si ya hay TTFB y FCP. */
function sendPageLoad() {
  if (vitalsSent || vitals.TTFB === undefined || vitals.FCP === undefined) return;
  vitalsSent = true;
  track("page_load_recorded", {
    // La ruta donde empezó la carga: las Web Vitals miden esa navegación completa.
    page_route: vitals.route ?? pageRoute(window.location.pathname),
    device_class: deviceClass(),
    navigation_type: navigationType(vitals.navigationType),
    ttfb_ms: ms(vitals.TTFB),
    fcp_ms: ms(vitals.FCP),
    lcp_ms: ms(vitals.LCP),
    inp_ms: ms(vitals.INP),
    cls: Math.max(0, Number((vitals.CLS ?? 0).toFixed(4))),
  });
}

export function TelemetryListener() {
  const pathname = usePathname();
  const lastView = useRef<{ route: string; at: number } | null>(null);
  const previousRoute = useRef<string | null>(null);

  useReportWebVitals(reportWebVitals);

  useEffect(() => telemetryService.onHide(sendPageLoad), []);

  useEffect(() => {
    if (!pathname) return;
    const route = pageRoute(pathname);
    const section = pageSection(route);
    const now = Date.now();
    if (!section || (lastView.current?.route === route && now - lastView.current.at < PAGE_VIEW_DEDUP_MS)) return;
    lastView.current = { route, at: now };
    track("page_viewed", { page_route: route, section, previous_route: previousRoute.current });
    previousRoute.current = route;
  }, [pathname]);

  return null;
}
