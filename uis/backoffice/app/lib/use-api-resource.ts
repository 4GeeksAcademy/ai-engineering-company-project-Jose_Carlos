"use client";

import { Dispatch, SetStateAction, useEffect, useRef, useState } from "react";
import { SessionExpiredError } from "./auth";

type Options<T> = {
  /** Cuando cambia, se vuelve a pedir el recurso (p. ej. un parámetro de la URL). */
  key?: unknown;
  /** Se llama con cada respuesta correcta (preselecciones, avisos de lista vacía…). */
  onLoaded?: (data: T) => void;
  /** Se llama si la petición falla. Una sesión caducada no llega aquí: el guard ya lleva al login. */
  onError?: (error: unknown) => void;
};

export type ApiResource<T> = {
  data: T;
  setData: Dispatch<SetStateAction<T>>;
  /** true tras una respuesta correcta; vuelve a false si la última petición falla. */
  loaded: boolean;
  loading: boolean;
  /** Vuelve a pedir el recurso (botones "Actualizar" y "Reintentar"). */
  reload: () => void;
};

/**
 * Pide un recurso de la API al montar la pantalla y cada vez que cambia `key` o se llama a `reload`.
 * Descarta las respuestas que llegan después de desmontar o de una petición más reciente, que es lo
 * que antes repetía cada pantalla con su propia bandera `cancelled`.
 */
export function useApiResource<T>(fetcher: () => Promise<T>, initial: T, { key, onLoaded, onError }: Options<T> = {}): ApiResource<T> {
  const [data, setData] = useState<T>(initial);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloadTick, setReloadTick] = useState(0);
  // Las funciones cambian en cada render: se guardan las últimas para no repetir la petición por ello.
  const callbacks = useRef({ fetcher, onLoaded, onError });
  useEffect(() => {
    callbacks.current = { fetcher, onLoaded, onError };
  });

  useEffect(() => {
    let cancelled = false;
    callbacks.current
      .fetcher()
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoaded(true);
        callbacks.current.onLoaded?.(result);
      })
      .catch((error: unknown) => {
        if (cancelled || error instanceof SessionExpiredError) return;
        setLoaded(false);
        callbacks.current.onError?.(error);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [key, reloadTick]);

  function reload() {
    setLoading(true);
    setReloadTick((tick) => tick + 1);
  }

  return { data, setData, loaded, loading, reload };
}
