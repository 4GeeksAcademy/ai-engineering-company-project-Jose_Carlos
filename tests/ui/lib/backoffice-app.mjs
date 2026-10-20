// Arranque compartido por las suites que usan el backoffice (Next.js, uis/backoffice):
//
//  * startApi: uvicorn con TinyDB y SQLite desechables (nunca el Supabase del .env), con CORS
//    abierto solo al origen del backoffice de la prueba.
//  * startBackoffice: `next dev` del backoffice en 127.0.0.1, apuntando a esa API.
//  * createUser / signIn: cuenta sintética y sesión en el navegador (token en localStorage).
//
// Los dos procesos escuchan en 127.0.0.1 con puertos libres y se paran con killTree().

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { freePort, groupSpawn, killTree, track, waitFor } from "./harness.mjs";

export const TOKEN_KEY = "trackflow.access_token";

export async function startApi(repoRoot, apiTemp, { port, corsOrigins = [] } = {}) {
  const python = process.env.PYTHON || [path.join(repoRoot, ".venv", "Scripts", "python.exe"), path.join(repoRoot, ".venv", "bin", "python")].find((p) => fs.existsSync(p));
  if (!python) throw new Error("Project virtualenv not found: run `uv sync --frozen` first (or set PYTHON).");
  port ??= await freePort();
  const output = [];
  const proc = track(spawn(python, ["-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: repoRoot,
    env: {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: "1",
      TEMP: apiTemp,
      TMP: apiTemp,
      TMPDIR: apiTemp,
      TINYDB_PATH: path.join(apiTemp, "db.json"),
      DATABASE_URL: "sqlite:///" + path.join(apiTemp, "inventory.db").split(path.sep).join("/"),
      // Sin descargar el modelo de embeddings: parecido léxico (lo mismo que usan los tests).
      EMBEDDINGS_PROVIDER: "hashing",
      BACKOFFICE_CORS_ORIGINS: corsOrigins.join(","),
    },
    stdio: ["ignore", "pipe", "pipe"],
    ...groupSpawn,
  }));
  for (const s of [proc.stdout, proc.stderr]) s.on("data", (b) => { output.push(String(b)); if (output.length > 200) output.shift(); });
  const origin = `http://127.0.0.1:${port}`;
  const ready = await waitFor(async () => (await fetch(origin + "/")).status === 200, 30000, 250);
  if (!ready) {
    killTree(proc);
    throw new Error("uvicorn did not become ready: " + output.join("").slice(-800));
  }
  return { proc, origin };
}

export async function startBackoffice(repoRoot, { port, apiOrigin, websiteUrl = "http://localhost:3000/" }) {
  const dir = path.join(repoRoot, "uis", "backoffice");
  const nextBin = path.join(dir, "node_modules", "next", "dist", "bin", "next");
  if (!fs.existsSync(nextBin)) throw new Error("Backoffice dependencies missing: run `npm ci` in uis/backoffice first.");
  port ??= await freePort();
  const output = [];
  const proc = track(spawn(process.execPath, [nextBin, "dev", "--port", String(port), "--hostname", "127.0.0.1"], {
    cwd: dir,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1", NEXT_PUBLIC_AUTH_API_URL: apiOrigin, NEXT_PUBLIC_WEBSITE_URL: websiteUrl },
    stdio: ["ignore", "pipe", "pipe"],
    ...groupSpawn,
  }));
  for (const s of [proc.stdout, proc.stderr]) s.on("data", (b) => { output.push(String(b)); if (output.length > 200) output.shift(); });
  const origin = `http://127.0.0.1:${port}`;
  // La primera petición compila la ruta: margen amplio.
  const ready = await waitFor(async () => (await fetch(origin + "/login")).status === 200, 180000, 500);
  if (!ready) {
    killTree(proc);
    throw new Error("next dev did not become ready: " + output.join("").slice(-800));
  }
  return { proc, origin, output };
}

/** API + backoffice que se conocen entre sí (CORS y NEXT_PUBLIC_AUTH_API_URL). */
export async function startStack(repoRoot, apiTemp, options = {}) {
  const apiPort = await freePort();
  const appPort = await freePort();
  const appOrigin = `http://127.0.0.1:${appPort}`;
  const api = await startApi(repoRoot, apiTemp, { port: apiPort, corsOrigins: [appOrigin] });
  try {
    const app = await startBackoffice(repoRoot, { port: appPort, apiOrigin: api.origin, ...options });
    return { api, app };
  } catch (e) {
    killTree(api.proc);
    throw e;
  }
}

export async function apiCall(origin, method, pathName, { token, body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(origin + pathName, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const json = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`${method} ${pathName} -> ${response.status} ${JSON.stringify(json)}`);
  return json;
}

/** Registra una cuenta sintética y devuelve su token y su id. */
export async function createUser(apiOrigin, email, password) {
  await apiCall(apiOrigin, "POST", "/users", { body: { email, password } });
  const { access_token: token } = await apiCall(apiOrigin, "POST", "/auth/login", { body: { email, password } });
  const me = await apiCall(apiOrigin, "GET", "/auth/me", { token });
  return { token, userId: me.id };
}

/** Deja la sesión abierta en el navegador (mismo localStorage que usa el login real). */
export async function signIn(page, appOrigin, token) {
  await page.goto(appOrigin + "/login", 120000);
  await page.eval(`localStorage.setItem(${JSON.stringify(TOKEN_KEY)}, ${JSON.stringify(token)});true`);
}

// Cambia el valor de un control controlado por React (setter nativo + evento), como el usuario.
export const setValue = (selector, value, event = "change") =>
  `(()=>{const el=document.querySelector(${JSON.stringify(selector)});const proto=el instanceof HTMLSelectElement?HTMLSelectElement.prototype:el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;` +
  `Object.getOwnPropertyDescriptor(proto,'value').set.call(el,${JSON.stringify(String(value))});el.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));return true})()`;
export const click = (selector) => `(()=>{document.querySelector(${JSON.stringify(selector)}).click();return true})()`;
export const submit = (selector) => `(()=>{document.querySelector(${JSON.stringify(selector)}).requestSubmit();return true})()`;
