"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { Lang, Translate, translate } from "../lib/incidents";

// Idioma de las pantallas de incidencias (español o inglés). Se guarda en localStorage
// (`trackflow.lang`); sin preferencia guardada se usa el idioma del navegador. El resto del
// backoffice está solo en español.

const LANG_KEY = "trackflow.lang";
const listeners = new Set<() => void>();

function readLang(): Lang {
  try {
    const saved = window.localStorage.getItem(LANG_KEY);
    if (saved === "es" || saved === "en") return saved;
  } catch {
    // Sin localStorage: se usa el idioma del navegador.
  }
  return (navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es";
}

let current: Lang | null = null;

function getSnapshot(): Lang {
  current ??= readLang();
  return current;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function setLang(next: Lang) {
  current = next;
  try {
    window.localStorage.setItem(LANG_KEY, next);
  } catch {
    // El cambio vale solo para esta visita.
  }
  listeners.forEach((listener) => listener());
}

/** Idioma actual, función de traducción y cambio de idioma. */
export function useIncidentsLang(): { lang: Lang; t: Translate; toggleLang: () => void } {
  const lang = useSyncExternalStore(subscribe, getSnapshot, () => "es" as Lang);
  const t = useCallback<Translate>((key, params) => translate(lang, key, params), [lang]);
  const toggleLang = useCallback(() => setLang(lang === "es" ? "en" : "es"), [lang]);
  return { lang, t, toggleLang };
}

/** Pone el atributo lang del documento mientras la pantalla bilingüe está abierta. */
export function useDocumentLang(lang: Lang) {
  useEffect(() => {
    document.documentElement.lang = lang;
    return () => {
      document.documentElement.lang = "es";
    };
  }, [lang]);
}
