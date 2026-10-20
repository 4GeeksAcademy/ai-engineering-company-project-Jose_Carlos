# Backoffice de TrackFlow (Next.js)

Panel interno de TrackFlow en una sola app Next.js (App Router + React + TypeScript + Tailwind 4).
Reúne lo que antes eran dos interfaces separadas: el backoffice en HTML/JS estático y el Talent
Pipeline Tracker.

| Sección | Ruta | Qué hace |
| --- | --- | --- |
| Incidentes (analizador CSV) | `/` | Sube un CSV, muestra métricas, desgloses y registros inválidos; exporta los resultados |
| Gestor de incidencias | `/incidents` | Resumen, posibles duplicados, listado con filtros, búsqueda semántica, casos similares y cambio de estado (español / inglés) |
| Registrar incidencia | `/incidents/new` | Formulario con ayuda semántica: incidencias parecidas, posibles duplicados y categoría sugerida (español / inglés) |
| Proveedores | `/suppliers` | Directorio con filtros, alta, tarifa en línea y suspender / reactivar |
| Inventario | `/inventory/products`, `/inventory/orders`, `/inventory/orders/inbound`, `/inventory/orders/outbound` | Stock por SKU, historial de movimientos, recepción de mercancía y salida de stock |
| Talent Pipeline | `/talent`, `/talent/records/[id]` | Candidaturas con filtros, paginación, detalle, notas y fotos |
| Cuenta | `/account/profile`, `/account/change-password` | Perfil y contraseña |

La cabecera común (`app/ui/backoffice-header.tsx`) enlaza todas las secciones, incluida la pestaña
**Talent Pipeline**, el perfil y «Cerrar sesión». Las direcciones antiguas (`/incidents.html`,
`/suppliers.html`, `/records/[id]`…) redirigen a las nuevas (`next.config.ts`).

## Autenticación

La app requiere sesión. El login, el registro y la cuenta usan la API FastAPI de TrackFlow (`services/api`), que tiene que estar arrancada (por defecto en `http://localhost:8000`; se cambia con `NEXT_PUBLIC_AUTH_API_URL` en `.env.local`). Abre la app en `http://localhost:3001`, que es el origen que permite el CORS de la API por defecto.

- Públicas, en el grupo `app/(auth)`: `/login` y `/register` (si ya hay una sesión válida, devuelven a la app), más `/forgot-password` y `/reset-password?token=…` para recuperar la contraseña.
- Protegidas, en el grupo `app/(protected)`, cuyo `layout.tsx` es el guard y pinta la cabecera común: todas las secciones de la tabla.
- El token se guarda en `localStorage` (`trackflow.access_token`). `app/lib/auth.ts` lo adjunta como `Authorization: Bearer` en las llamadas protegidas a la API de TrackFlow (`backofficeFetch` para las secciones del backoffice). Si falta, ha caducado o la API responde 401, se borra y se redirige a `/login?next=…`.
- No se usa middleware: corre en el servidor y no puede leer `localStorage`.
- Las llamadas de candidaturas van a la API externa de 4Geeks, que no usa este token, y no se le envía.

## Variables de entorno

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `NEXT_PUBLIC_AUTH_API_URL` | `http://localhost:8000` | URL de la API de TrackFlow (la usa el navegador) |
| `NEXT_PUBLIC_WEBSITE_URL` | `http://localhost:3000/` | Enlace del logo a la web pública |

## Arrancar en local

```bash
npm ci
npm run dev        # http://localhost:3001
npm test           # utilidades de app/lib (Jest)
```

Con Docker no hace falta: `docker compose up` desde la raíz del repositorio arranca el backoffice en el 3001.
Las pruebas en navegador de cada sección están en `tests/ui/` (ver su README).
