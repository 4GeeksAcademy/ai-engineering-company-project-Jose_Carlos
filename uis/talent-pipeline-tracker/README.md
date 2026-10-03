This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Autenticación (AUTH-02)

La app requiere sesión. El login, el registro y la cuenta usan la API FastAPI de TrackFlow (`services/api`), que tiene que estar arrancada (por defecto en `http://localhost:8000`; se cambia con `NEXT_PUBLIC_AUTH_API_URL` en `.env.local`). Abre la app en `http://localhost:3000`, que es uno de los orígenes que permite el CORS de la API.

- Públicas, en el grupo `app/(auth)`: `/login` y `/register` (si ya hay una sesión válida, devuelven a la app), más `/forgot-password` y `/reset-password?token=…` para recuperar la contraseña.
- Protegidas, en el grupo `app/(protected)`, cuyo `layout.tsx` es el guard: `/`, `/records/[id]`, `/account/profile` y `/account/change-password`.
- El token se guarda en `localStorage` (`trackflow.access_token`). `app/lib/auth.ts` lo adjunta como `Authorization: Bearer` en las llamadas protegidas a la API de TrackFlow. Si falta, ha caducado o la API responde 401, se borra y se redirige a `/login?next=…`.
- No se usa middleware: corre en el servidor y no puede leer `localStorage`.
- Las llamadas de candidaturas van a la API externa de 4Geeks, que no usa este token, y no se le envía.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
