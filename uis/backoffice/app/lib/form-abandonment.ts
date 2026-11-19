"use client";

// `order_form_abandoned`: un operario empieza una entrada o salida y la deja sin registrar.
//
// El formulario está "sucio" cuando algún campo difiere del formulario vacío. Si el componente
// se desmonta (cambia de pantalla, cierra sesión) o la pestaña se cierra estando sucio, se emite
// un evento. Un envío correcto vacía el formulario, así que deja de estar sucio y no emite nada.
// Ocultar la pestaña no cuenta: el operario puede volver y terminar.
//
// También lleva el registro de formularios sucios que usa `session_expired` (`had_unsaved_form`).

import { useEffect, useRef } from "react";
import { telemetryService, track } from "./telemetry";

const WAREHOUSES: Record<string, string> = { LA: "los_angeles", ZGZ: "zaragoza" };

export type FormErrorType = "none" | "client_validation" | "api_validation" | "insufficient_stock" | "network" | "server";

const dirtyForms = new Set<symbol>();

/** true si hay algún formulario de inventario con cambios sin enviar. */
export function hasUnsavedForm(): boolean {
  return dirtyForms.size > 0;
}

/**
 * Vigila un formulario de inventario. `values` es el estado actual y `empty` el formulario
 * vacío; devuelve `reportError` para anotar el último error que se le mostró al operario.
 */
export function useFormAbandonment<T extends Record<string, string>>(form: "inbound" | "outbound", values: T, empty: T) {
  const state = useRef({ id: Symbol(form), values, startedAt: null as number | null, lastError: "none" as FormErrorType });

  const filled = Object.keys(values).filter((field) => values[field] !== empty[field]);
  const dirty = filled.length > 0;

  useEffect(() => {
    const current = state.current;
    current.values = values;
    if (dirty) {
      current.startedAt ??= Date.now();
      dirtyForms.add(current.id);
    } else {
      // Vacío otra vez (envío correcto o el operario lo borró todo): se empieza de cero.
      current.startedAt = null;
      current.lastError = "none";
      dirtyForms.delete(current.id);
    }
  }, [values, dirty]);

  useEffect(() => {
    const current = state.current;
    let emitted = false;

    function emitIfAbandoned() {
      if (emitted || current.startedAt === null) return;
      emitted = true;
      const fields = Object.keys(current.values).filter((field) => current.values[field] !== empty[field]);
      track("order_form_abandoned", {
        form,
        fields_filled: fields,
        warehouse: WAREHOUSES[current.values.warehouse] ?? null,
        last_error_type: current.lastError,
        time_on_form_ms: Math.max(0, Date.now() - current.startedAt),
      });
    }

    const offHide = telemetryService.onHide((reason) => {
      if (reason === "pagehide") emitIfAbandoned();
    });
    return () => {
      offHide();
      emitIfAbandoned();
      dirtyForms.delete(current.id);
    };
    // `empty` es una constante del módulo de cada formulario.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form]);

  return {
    reportError(type: FormErrorType) {
      state.current.lastError = type;
    },
  };
}
