# Hito 10 — Dockerizar el proyecto TrackFlow (ticket #infra-40)

Este documento explica, paso a paso y sin dar nada por sabido, cómo se ha preparado el proyecto
para que **cualquier persona pueda arrancarlo en su ordenador con un solo comando**, sin tener que
instalar Python, Node.js ni ninguna librería a mano.

Está pensado para leerse de principio a fin. Si en algún momento quieres repetir el proceso tú
solo, la [sección 6](#6-el-proceso-paso-a-paso) tiene todos los pasos en orden, con los comandos
exactos.

> 🔄 **Actualización: backoffice unificado.** Después de dockerizar el proyecto, el backoffice
> (que era HTML estático) y el Talent Pipeline Tracker se unieron en **una sola app Next.js**, en
> `uis/backoffice`, publicada en el puerto **3001** (el Talent está en `/talent`). La
> [sección 12](#12-unificación-del-backoffice-y-el-talent-pipeline-nextjs) explica cómo se hizo.
> Las secciones 6 a 8 cuentan el proceso **tal como se hizo al principio**, con tres interfaces y
> el puerto 3002; donde algo ha cambiado se avisa. Las secciones 9, 10 y 11 (uso diario,
> problemas y VPS) ya están **al día**.

---

## Índice

1. [El problema que queríamos resolver](#1-el-problema-que-queríamos-resolver)
2. [Conceptos básicos (explicados sin tecnicismos)](#2-conceptos-básicos-explicados-sin-tecnicismos)
3. [Qué hay en el proyecto](#3-qué-hay-en-el-proyecto)
4. [Lo que pedía el checklist y lo que encontramos al revisar](#4-lo-que-pedía-el-checklist-y-lo-que-encontramos-al-revisar)
5. [Requisitos previos: qué necesitas instalado](#5-requisitos-previos-qué-necesitas-instalado)
6. [El proceso paso a paso](#6-el-proceso-paso-a-paso)
7. [Problemas que aparecieron y cómo se resolvieron](#7-problemas-que-aparecieron-y-cómo-se-resolvieron)
8. [Cómo se comprobó que todo funciona](#8-cómo-se-comprobó-que-todo-funciona)
9. [Uso diario: los comandos que vas a necesitar](#9-uso-diario-los-comandos-que-vas-a-necesitar)
10. [Si algo falla](#10-si-algo-falla)
11. [Producción: la imagen para el VPS](#11-producción-la-imagen-para-el-vps)
12. [Unificación del backoffice y el Talent Pipeline (Next.js)](#12-unificación-del-backoffice-y-el-talent-pipeline-nextjs)
13. [Resumen de archivos creados y modificados](#13-resumen-de-archivos-creados-y-modificados)
14. [Glosario](#14-glosario)

---

## 1. El problema que queríamos resolver

Hasta ahora, para poner en marcha el proyecto en un ordenador nuevo había que:

- instalar la versión correcta de Python,
- instalar `uv` y luego todas las librerías de Python,
- instalar Node.js y las librerías de la app Next.js,
- arrancar cada parte por separado, cada una en una terminal distinta,
- y rezar para que todo coincidiera con lo que tiene el resto del equipo.

Cada persona nueva perdía horas "depurando dependencias" (es decir, peleándose con versiones que no
encajan). El objetivo del ticket es que baste con:

```sh
docker compose up
```

y que **todo** el proyecto arranque igual en cualquier ordenador.

---

## 2. Conceptos básicos (explicados sin tecnicismos)

### ¿Qué es Docker?

Imagina que tu programa es una planta. Para que crezca necesita una tierra concreta, un tipo de
abono y una cantidad de agua. Si se la das a otra persona, esa persona tiene que conseguir
exactamente la misma tierra y el mismo abono, o la planta se muere.

**Docker** te permite meter la planta **en una maceta cerrada que ya trae su tierra, su abono y su
riego**. Da igual dónde pongas la maceta: la planta crece igual.

- La **"maceta"** se llama **contenedor**.
- La **"receta"** para fabricar la maceta (qué tierra, qué abono…) se llama **imagen**, y se escribe
  en un archivo llamado **`Dockerfile`**.

### ¿Qué es Docker Compose?

Nuestro proyecto no es una sola planta, son varias (la API y las páginas web). **Docker Compose** es
como el **plano del jardín**: un archivo (`docker-compose.yml`) que dice qué macetas hay, dónde se
colocan, cómo se conectan entre sí y qué necesita cada una. Con un único comando
(`docker compose up`) se monta el jardín completo.

### Imagen vs. contenedor

- **Imagen**: la receta ya "cocinada" y guardada. No se ejecuta, solo existe. Es como un molde.
- **Contenedor**: una copia de esa imagen **en marcha**. Puedes tener varios contenedores hechos con
  la misma imagen.

### Puertos

Un ordenador tiene miles de "puertas" numeradas (puertos) por las que entran y salen las
conexiones. Cuando escribes `http://localhost:3000` en el navegador, le dices: "conéctate a mi
propio ordenador (`localhost`), por la puerta 3000".

Cada contenedor tiene sus propias puertas internas. En `docker-compose.yml` decimos qué puerta de
tu ordenador lleva a qué puerta del contenedor. Eso se llama **publicar un puerto**.

### Bind mount (carpeta compartida)

Normalmente un contenedor tiene una copia congelada del código. Si cambias un archivo en tu editor,
el contenedor no se entera.

Un **bind mount** es como una **carpeta compartida** entre tu ordenador y el contenedor: lo que
cambias en tu editor, el contenedor lo ve al instante. Gracias a eso tenemos…

### Recarga en caliente (hot reload)

Que el programa **se actualice solo** cuando guardas un archivo, sin tener que pararlo y arrancarlo
otra vez. Guardas → recargas el navegador (o se recarga solo) → ves el cambio.

### Variables de entorno y el archivo `.env`

Son "ajustes" que se le pasan a un programa desde fuera, en vez de escribirlos dentro del código.
Por ejemplo: la contraseña de la base de datos o en qué dirección está la API.

El archivo **`.env`** es una lista de esos ajustes, uno por línea:

```
NOMBRE=valor
```

**Muy importante:** en `.env` van los **secretos** (contraseñas, claves). Por eso `.env` **nunca se
sube a GitHub** (está en `.gitignore`). En cambio, `.env.example` sí se sube: es la misma lista
pero **vacía**, para que cualquiera sepa qué tiene que rellenar.

### `.gitignore`, `.dockerignore` y `.gitattributes`

- **`.gitignore`**: lista de archivos que Git **no** debe subir (secretos, librerías descargadas…).
- **`.dockerignore`**: lista de archivos que Docker **no** debe meter en la imagen. Igual que
  `.gitignore`, pero para Docker.
- **`.gitattributes`**: reglas sobre cómo guarda Git ciertos archivos. Aquí lo usamos para una cosa
  concreta (los "finales de línea", explicado en el [paso 6.10](#610-gitattributes-y-gitignore)).

### Red de Docker y "nombre de servicio"

Los contenedores de Compose se conectan a una **red privada** entre ellos. Dentro de esa red,
cada contenedor se encuentra por su **nombre**. Es como una oficina con extensiones telefónicas:
para llamar a la API no marcas un número largo, marcas "backend".

Aquí hay un detalle importante que conviene entender bien:

| ¿Quién hace la llamada? | ¿Dónde está? | Dirección correcta para llegar a la API |
| --- | --- | --- |
| Un contenedor (por ejemplo, el de interfaces) | Dentro de la red de Docker | `http://backend:8000` |
| **Tu navegador** (Chrome, Edge…) | En tu ordenador, **fuera** de la red de Docker | `http://localhost:8000` |

Dentro de un contenedor, `localhost` significa **"yo mismo, este contenedor"**, no tu ordenador.
Por eso entre contenedores **nunca** se usa `localhost`. Pero tu navegador no está dentro de la red
de Docker y no conoce el nombre "backend": para él lo correcto es `localhost` y el puerto publicado.

---

## 3. Qué hay en el proyecto

Las partes que nos importan para este hito:

```
(raíz del repositorio)
├── services/                     ← el backend: la API hecha con FastAPI (Python)
│   ├── api/                      ← código principal de la API
│   ├── routers/                  ← rutas del inventario
│   └── database.py               ← conexión a las bases de datos
├── scripts/                      ← scripts de Python que la API también usa
├── packages/shared/              ← código Python compartido que la API también usa
├── uis/                          ← todas las interfaces (lo que se ve en el navegador)
│   ├── website/trackflow-web/    ← web pública (HTML estático)
│   ├── backoffice/               ← panel interno (HTML + JavaScript estático)
│   └── talent-pipeline-tracker/  ← app hecha con Next.js (React)
├── pyproject.toml + uv.lock      ← lista de librerías de Python y sus versiones exactas
├── .env                          ← ajustes y secretos (NO se sube a GitHub)
└── .env.example                  ← plantilla de .env (SÍ se sube)
```

> 🔄 Así estaba al empezar el hito. Hoy `uis/` tiene solo dos carpetas: `website/` (igual) y
> `backoffice/`, que es la app Next.js con todo el panel interno **y** el Talent Pipeline. La antigua
> `talent-pipeline-tracker/` ya no existe (ver sección 12).

---

## 4. Lo que pedía el checklist y lo que encontramos al revisar

Antes de escribir nada se revisó el proyecto. Esto es importante: **nunca hay que construir sobre
suposiciones**. Salieron tres diferencias con lo que daba por hecho el checklist:

| El checklist decía… | La realidad del proyecto | Decisión tomada |
| --- | --- | --- |
| Website y backoffice son apps **Next.js** que se arrancan con `next dev`. | Son **páginas HTML estáticas**. La única app Next.js es `talent-pipeline-tracker`. | (Elegido por ti) Adaptarnos a lo real: website en el **3000**, backoffice en el **3001** (los dos con un servidor de recarga en caliente llamado *browser-sync*) y la app Next.js en el **3002** con `next dev`. |
| Instalar dependencias desde `requirements.txt`. | No existía. Las librerías estaban en `pyproject.toml` y `uv.lock`. | Generar `services/requirements.txt` a partir de `uv.lock`, para que use **exactamente las mismas versiones**. |
| El backend se construye desde `/services/`. | La API también usa código de `scripts/` y `packages/`, que están fuera de `services/`. | Construir la imagen desde `/services/` y, además, compartir esas carpetas con el contenedor mediante *bind mounts*. |

---

## 5. Requisitos previos: qué necesitas instalado

Solo dos cosas:

1. **Docker Desktop** (incluye Docker y Docker Compose). Se descarga desde
   https://www.docker.com/products/docker-desktop/ . Tras instalarlo, **ábrelo** y espera a que diga
   que está en marcha ("Engine running"). Si Docker Desktop está cerrado, ningún comando `docker`
   funcionará.
2. **Git**, para descargar el repositorio.

Para comprobar que Docker está listo, abre una terminal y escribe:

```sh
docker --version
docker compose version
docker info
```

Los dos primeros dicen qué versión tienes. El tercero, si Docker Desktop **no** está abierto,
muestra un error del tipo `failed to connect to the docker API` (nos pasó durante este hito:
la solución fue simplemente abrir Docker Desktop).

> **¿Qué es la terminal?** Es la ventana donde se escriben comandos de texto. En Windows puedes
> usar *PowerShell* o la terminal integrada de VS Code (menú *Terminal → New Terminal*). Todos los
> comandos de este documento se ejecutan **desde la carpeta raíz del repositorio**.

Solo para **generar** algunos archivos (pasos 6.2 y 6.3) se usaron también `uv` y `npm`, que ya
tenías instalados. Una persona que solo quiera **usar** el proyecto no los necesita.

---

## 6. El proceso paso a paso

> 🔄 **Ojo:** esta sección cuenta la primera versión, con tres interfaces (3000, 3001 y 3002). Los
> archivos `uis/Dockerfile`, `uis/start.sh`, `docker-compose.yml` y `.env.example` se cambiaron
> después para el backoffice unificado. Si vas a copiar algo, copia **los archivos del repositorio**,
> no los fragmentos de esta sección. Los cambios exactos están en la sección 12.

### 6.1 Revisar el proyecto

Se miró qué carpetas había, qué contenían las apps y cómo se comunicaban. Algunos de los comandos
usados (no hace falta que los repitas, son para "investigar"):

```sh
ls uis uis/website uis/backoffice services      # ver qué hay en cada carpeta
cat uis/talent-pipeline-tracker/package.json    # ver qué librerías usa la app Next.js
cat .env.example                                # ver qué ajustes necesita la API
```

También se buscaron todas las direcciones del tipo `localhost` en el código, para saber quién
llama a quién. Conclusión:

- El **backoffice** y la **app Next.js** llaman a la API **desde el navegador** → deben usar
  `http://localhost:8000`.
- La **web pública** no llama a la API.
- La **API** construye un enlace (`FRONTEND_URL`) para el correo de "restablecer contraseña": ese
  enlace lo abre el navegador → debe ser `http://localhost:3002`.

### 6.2 Crear `services/requirements.txt`

Docker necesita una lista de las librerías de Python que tiene que instalar. Como ya existía
`uv.lock` (que guarda las versiones exactas), se generó la lista a partir de él:

```sh
uv export --frozen --no-dev --no-hashes --no-emit-project --no-header --format requirements.txt -o services/requirements.txt
```

Qué significa cada parte:

| Parte | Significado |
| --- | --- |
| `uv export` | "Exporta la lista de librerías". |
| `--frozen` | Usa `uv.lock` tal cual, sin actualizar nada. |
| `--no-dev` | No incluyas las librerías que solo se usan para los tests (pytest…). |
| `--no-hashes` | No añadas las "huellas" de seguridad de cada archivo (hace la lista más legible). |
| `--no-emit-project` | No incluyas el propio proyecto, solo sus librerías. |
| `--no-header` | Sin comentario de cabecera. |
| `--format requirements.txt -o services/requirements.txt` | Guárdalo en ese formato y en ese archivo. |

> **Cuándo repetirlo:** cada vez que se añada o cambie una librería de Python (con `uv add …`).

### 6.3 Crear `package.json` para el website y el backoffice

Las páginas estáticas no tenían ninguna dependencia, pero para tener **recarga en caliente**
necesitan un pequeño servidor: **browser-sync**. Se creó un `package.json` (la "lista de
librerías" del mundo Node.js) en cada una. Ejemplo, `uis/website/package.json`:

```json
{
  "name": "trackflow-website",
  "version": "0.1.0",
  "private": true,
  "description": "Servidor de desarrollo con recarga en caliente para el website estático (lo usa uis/start.sh dentro del contenedor de interfaces).",
  "devDependencies": {
    "browser-sync": "3.0.4"
  }
}
```

`uis/backoffice/package.json` es igual cambiando `website` por `backoffice`.

Después se generó el archivo de versiones exactas (`package-lock.json`) de cada uno, sin instalar
nada en tu ordenador:

```sh
cd uis/website    && npm install --package-lock-only --ignore-scripts && cd ../..
cd uis/backoffice && npm install --package-lock-only --ignore-scripts && cd ../..
```

`--package-lock-only` = "solo escribe el `package-lock.json`, no descargues nada".

### 6.4 El Dockerfile de las interfaces (`uis/Dockerfile`)

Esta es la **receta** del contenedor que ejecuta las tres páginas web. Contenido completo, con la
explicación de cada línea debajo:

```dockerfile
FROM node:22-alpine

WORKDIR /opt/uis/website
COPY website/package.json website/package-lock.json ./
RUN npm ci --no-audit --no-fund

WORKDIR /opt/uis/backoffice
COPY backoffice/package.json backoffice/package-lock.json ./
RUN npm ci --no-audit --no-fund

WORKDIR /app/talent-pipeline-tracker
COPY talent-pipeline-tracker/package.json talent-pipeline-tracker/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY start.sh /usr/local/bin/start.sh
RUN sed -i 's/\r$//' /usr/local/bin/start.sh && chmod +x /usr/local/bin/start.sh

WORKDIR /app
EXPOSE 3000 3001 3002

CMD ["start.sh"]
```

| Instrucción | Qué hace |
| --- | --- |
| `FROM node:22-alpine` | Parte de una imagen oficial que ya trae **Node.js 22** sobre **Alpine** (un Linux muy pequeño). Es "la tierra base de la maceta". |
| `WORKDIR /opt/uis/website` | "Sitúate en esta carpeta dentro del contenedor" (la crea si no existe). |
| `COPY …package.json …package-lock.json ./` | Copia **solo** la lista de librerías del website. |
| `RUN npm ci` | Instala las librerías exactamente como dice `package-lock.json`. `ci` = instalación limpia y reproducible. |
| (lo mismo para backoffice) | Se instalan **por separado**, como pedía el checklist. |
| (lo mismo para talent-pipeline-tracker) | Instala Next.js, React, etc. |
| `COPY start.sh …` y `RUN sed … chmod +x …` | Copia el script de arranque, le quita los finales de línea de Windows (ver [6.10](#610-gitattributes-y-gitignore)) y le da permiso para ejecutarse. |
| `EXPOSE 3000 3001 3002` | Documenta qué puertas usa el contenedor. |
| `CMD ["start.sh"]` | El comando que se ejecuta al arrancar el contenedor. |

**¿Por qué solo se copian los `package.json` y no el código?** Porque el código llega por *bind
mount* (carpeta compartida). Así, cuando cambias una página, no hay que reconstruir la imagen.

**¿Por qué las librerías del website y del backoffice van a `/opt/…` y no junto al código?**
Porque la carpeta compartida se "pone encima" de `/app` dentro del contenedor y taparía cualquier
cosa que hubiera ahí. En `/opt` no les afecta. (??)


### 6.5 El script de arranque (`uis/start.sh`)

Un contenedor ejecuta **un** comando al arrancar, pero nosotros necesitamos **tres** servidores
(website, backoffice y Next.js). La solución es un pequeño script que los lanza a la vez. Esto es
lo que hace, por partes:

**1) Comprobar que llega a la API por su nombre de servicio** (`http://backend:8000`). Lo intenta
hasta 30 veces, cada 2 segundos. Si no responde, avisa pero **sigue adelante** (la web pública no
necesita la API).

```sh
until wget -q -O /dev/null "$API_INTERNAL_URL/"; do
  ...
  sleep 2
done
```

**2) Arrancar el website en el puerto 3000** con browser-sync, vigilando los `.html`, `.css` y
`.js`:

```sh
/opt/uis/website/node_modules/.bin/browser-sync start \
  --server /app/website/trackflow-web \
  --files "/app/website/trackflow-web/**/*.html,/app/website/trackflow-web/**/*.css,/app/website/trackflow-web/**/*.js" \
  --port 3000 --no-open --no-ui --no-notify &
```

- `--server …` → qué carpeta se sirve.
- `--files …` → qué archivos vigilar para recargar (`**/*.html` = "cualquier `.html` en cualquier
  subcarpeta").
- `--no-open` → no intentes abrir un navegador (dentro del contenedor no hay).
- El `&` del final significa "lánzalo y sigue con lo siguiente sin esperar".

**3) Arrancar el backoffice en el puerto 3001**, igual que el website, con dos extras:
`--ss /app` para que funcione el enlace del logo que apunta a la web pública, y
`--ignore "**/node_modules/**"` para no vigilar carpetas de librerías (sería muy lento).

**4) Arrancar la app Next.js en el puerto 3002:**

```sh
cd /app/talent-pipeline-tracker
./node_modules/.bin/next dev --webpack --hostname 0.0.0.0 --port 3002 &
```

- `next dev` → modo desarrollo con recarga en caliente.
- `--hostname 0.0.0.0` → acepta conexiones que vienen de fuera del contenedor (si no, solo
  respondería a sí mismo y tu navegador no podría entrar).
- `--webpack` → usa el motor *webpack*, que sabe detectar cambios en carpetas compartidas desde
  Windows (ver [problema 7.3](#73-la-recarga-en-caliente-y-windows)).

**5) Vigilar a los tres.** Si uno se cae, el script para los otros y termina con error. Así lo ves
en `docker compose ps` en lugar de tener un contenedor "medio vivo".

### 6.6 El `.dockerignore` de las interfaces (`uis/.dockerignore`)

```
**/node_modules
**/.next
**/.env*
**/*.log
**/coverage
**/*.tsbuildinfo
```

Cada línea es algo que **no** debe entrar en la imagen: librerías ya descargadas en tu ordenador
(`node_modules`, que además son de Windows y no valen en Linux), archivos temporales de Next.js
(`.next`), secretos (`.env*`), registros (`*.log`) y restos de los tests.

El `**/` delante significa "en cualquier subcarpeta". **Sin él solo se ignoraría en la carpeta
principal**, y se colarían los `node_modules` de `talent-pipeline-tracker`.

### 6.7 El Dockerfile del backend (`services/Dockerfile`)

```dockerfile
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt

COPY . /app/services

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-dir", "services", "--reload-dir", "scripts", "--reload-dir", "packages"]
```

| Instrucción | Qué hace |
| --- | --- |
| `FROM python:3.13-slim` | Imagen oficial con **Python 3.13** (la versión de `.python-version`). `slim` = versión reducida. |
| `COPY --from=ghcr.io/astral-sh/uv:0.12.21 …` | Instala **uv** copiándolo de su imagen oficial (la misma versión que tienes en tu ordenador). |
| `COPY requirements.txt …` + `RUN uv pip install …` | Instala todas las librerías de Python. `--system` = en el Python del contenedor (no hace falta entorno virtual: el contenedor ya está aislado). |
| `COPY . /app/services` | Copia el código de `services/` a la imagen. |
| `ENV PYTHONUNBUFFERED=1` | Hace que los mensajes de Python salgan al momento en los registros. |
| `CMD ["uvicorn", …, "--reload", …]` | Arranca la API con **Uvicorn** en el puerto 8000 y con **recarga en caliente** (`--reload`), vigilando las carpetas `services`, `scripts` y `packages`. |

**¿Por qué `--host 0.0.0.0`?** Igual que con Next.js: para aceptar conexiones de fuera del
contenedor. En el README antiguo ponía `127.0.0.1`, que dentro de Docker significaría "solo yo".

### 6.8 El `.dockerignore` del backend (`services/.dockerignore`)

```
**/__pycache__
**/*.pyc
**/.env*
tests/
**/*.log
api/db*.json
```

Excluye archivos temporales de Python (`__pycache__`, `*.pyc`), secretos, tests, registros y
también los **datos locales** de TinyDB (`api/db.json`), que contienen usuarios y no deben quedar
guardados dentro de una imagen.

### 6.9 El plano del jardín: `docker-compose.yml` (en la raíz)

Este es el archivo que une todo. Contenido completo:

```yaml
name: trackflow

services:
  interfaces:
    build:
      context: ./uis
    init: true
    command: ["start.sh"]
    ports:
      - "${WEBSITE_PORT:-3000}:3000"
      - "${BACKOFFICE_PORT:-3001}:3001"
      - "${TALENT_TRACKER_PORT:-3002}:3002"
    environment:
      API_INTERNAL_URL: ${API_INTERNAL_URL:-http://backend:8000}
      NEXT_PUBLIC_AUTH_API_URL: ${NEXT_PUBLIC_AUTH_API_URL:-http://localhost:8000}
      CHOKIDAR_USEPOLLING: ${CHOKIDAR_USEPOLLING:-true}
      WATCHPACK_POLLING: ${WATCHPACK_POLLING:-true}
      NEXT_TELEMETRY_DISABLED: ${NEXT_TELEMETRY_DISABLED:-1}
    volumes:
      - ./uis:/app
      - /app/talent-pipeline-tracker/node_modules
      - /app/talent-pipeline-tracker/.next
    depends_on:
      - backend
    networks:
      - trackflow-net

  backend:
    build:
      context: ./services
    command:
      - uvicorn
      - services.api.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"
      - --reload
      - --reload-dir
      - services
      - --reload-dir
      - scripts
      - --reload-dir
      - packages
    ports:
      - "${API_PORT:-8000}:8000"
    environment:
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:?Define JWT_SECRET_KEY en .env (copia .env.example)}
      JWT_ALGORITHM: ${JWT_ALGORITHM:-HS256}
      ACCESS_TOKEN_EXPIRE_MINUTES: ${ACCESS_TOKEN_EXPIRE_MINUTES:-30}
      DATABASE_URL: ${DATABASE_URL:?Define DATABASE_URL en .env (copia .env.example)}
      RESEND_API_KEY: ${RESEND_API_KEY:-}
      PASSWORD_RESET_LOG_LINK: ${PASSWORD_RESET_LOG_LINK:-false}
      EMAIL_FROM: ${EMAIL_FROM:-TrackFlow <onboarding@resend.dev>}
      FRONTEND_URL: ${FRONTEND_URL:-http://localhost:3002}
      PASSWORD_RESET_EXPIRE_MINUTES: ${PASSWORD_RESET_EXPIRE_MINUTES:-30}
      PASSWORD_RESET_MAX_PER_HOUR: ${PASSWORD_RESET_MAX_PER_HOUR:-5}
      BACKOFFICE_CORS_ORIGINS: ${BACKOFFICE_CORS_ORIGINS:-http://localhost:3001,http://127.0.0.1:3001,http://localhost:3002,http://127.0.0.1:3002}
      EMBEDDINGS_PROVIDER: ${EMBEDDINGS_PROVIDER:-fastembed}
      EMBEDDINGS_MODEL: ${EMBEDDINGS_MODEL:-sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2}
    volumes:
      - ./services:/app/services
      - ./scripts:/app/scripts
      - ./packages:/app/packages
      - ./uis/backoffice:/app/uis/backoffice:ro
      - fastembed-cache:/root/.cache/fastembed
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - trackflow-net

networks:
  trackflow-net:
    name: trackflow-net

volumes:
  fastembed-cache:
```

(En el archivo real hay además comentarios explicando cada bloque.)

Cómo leerlo:

**`services:`** — la lista de contenedores. Hay dos: `interfaces` y `backend`. **Estos nombres son
también los "nombres de servicio"** con los que se encuentran dentro de la red.

**`build: context: ./uis`** — "fabrica la imagen usando la receta (`Dockerfile`) de la carpeta
`uis`".

**`ports:`** — qué puerta de tu ordenador lleva a qué puerta del contenedor. Formato
`"ordenador:contenedor"`. Por ejemplo `"3000:3000"`: lo que entre por tu puerto 3000 va al 3000 del
contenedor.

**`${WEBSITE_PORT:-3000}`** — esto es una **variable**. Compose lee automáticamente el `.env` de la
raíz y sustituye `${WEBSITE_PORT}` por su valor. El `:-3000` significa "si no está definido en
`.env`, usa 3000".

**`${JWT_SECRET_KEY:?mensaje}`** — el `:?` significa "**obligatorio**: si no está en `.env`, para
todo y muestra este mensaje". Se usa para los dos secretos imprescindibles.

> 🔐 **Fíjate en que en este archivo no hay ninguna contraseña ni clave real.** Solo hay *nombres*
> de variables. Los valores reales están en `.env`, que no se sube a GitHub. Los únicos valores
> escritos (los que van tras `:-`) son ajustes por defecto que no son secretos y que ya usaba el
> propio código.

**`environment:`** — las variables que recibe cada contenedor. Cada uno recibe **solo las que
necesita** (el contenedor de interfaces no recibe la contraseña de la base de datos).

**`volumes:`** — las carpetas compartidas:

- `./uis:/app` → tu carpeta `uis` aparece dentro del contenedor como `/app`. **Esto es lo que hace
  posible la recarga en caliente.**
- `/app/talent-pipeline-tracker/node_modules` (sin `:`) → es un **volumen anónimo**: una "caja"
  propia del contenedor que protege sus librerías para que la carpeta compartida no las tape con las
  de tu ordenador (que son de Windows y no funcionan en Linux).
- `fastembed-cache:/root/.cache/fastembed` → un **volumen con nombre** donde se guarda el modelo de
  inteligencia artificial de búsqueda (~220 MB). Se descarga **una sola vez** y se conserva aunque
  apagues los contenedores.
- `:ro` (en el backoffice del backend) = *read only*, solo lectura.

**`depends_on: - backend`** — "arranca primero el backend y luego las interfaces".

**`healthcheck:`** — cada 10 segundos Docker pregunta a la API "¿estás viva?". Así
`docker compose ps` muestra `healthy` (sana) o `unhealthy` (con problemas). Aquí sí se usa
`localhost`, porque es el contenedor preguntándose **a sí mismo**.

**`networks: trackflow-net`** — los dos contenedores se conectan a una red con un nombre fijo
(`trackflow-net`), como pedía el checklist.

**`init: true`** — añade un pequeño "portero" que ayuda a que el contenedor se apague limpiamente
cuando haces `docker compose down`.

### 6.10 `.gitattributes` y `.gitignore`

**El problema de los finales de línea:** Windows y Linux marcan el final de cada línea de texto de
forma distinta (Windows añade un carácter invisible extra, llamado `\r` o *CRLF*). Si `start.sh`
llega al contenedor (que es Linux) con finales de Windows, falla con errores rarísimos.

Por eso se creó `.gitattributes` en la raíz:

```
# start.sh se ejecuta en Linux (contenedor): siempre con finales de línea LF.
*.sh text eol=lf
```

"Todos los archivos `.sh` guárdalos siempre con finales de Linux". Y, por si acaso, el Dockerfile
también los limpia (el `sed -i 's/\r$//'` del paso 6.4).

En `.gitignore` se añadió `node_modules/`, para que nunca se suban carpetas de librerías.

Y se comprobó que `.env` ya estaba ignorado:

```sh
git check-ignore -v .env
```

Respuesta: `.gitignore:12:.env  .env` → "sí, la línea 12 de `.gitignore` lo ignora". ✅

### 6.11 Actualizar `.env.example`

Se añadió al final una sección con los nuevos ajustes de Docker (sin secretos), para que cualquiera
sepa que existen:

```
# --- Docker Compose (docker compose up) ---
WEBSITE_PORT=3000
BACKOFFICE_PORT=3001
TALENT_TRACKER_PORT=3002
API_PORT=8000
BACKOFFICE_CORS_ORIGINS=http://localhost:3001,http://127.0.0.1:3001,http://localhost:3002,http://127.0.0.1:3002
API_INTERNAL_URL=http://backend:8000
NEXT_PUBLIC_AUTH_API_URL=http://localhost:8000
CHOKIDAR_USEPOLLING=true
WATCHPACK_POLLING=true
NEXT_TELEMETRY_DISABLED=1
```

Qué es cada uno:

| Variable | Para qué sirve |
| --- | --- |
| `*_PORT` | En qué puerto de tu ordenador aparece cada app. Cámbialo si ese puerto ya lo usa otro programa. |
| `BACKOFFICE_CORS_ORIGINS` | Lista de páginas a las que la API **permite** llamarla. Los navegadores bloquean por seguridad las llamadas entre puertos distintos salvo que la API lo autorice (esto se llama **CORS**). |
| `API_INTERNAL_URL` | Dirección de la API **entre contenedores** → nombre de servicio `backend`. |
| `NEXT_PUBLIC_AUTH_API_URL` | Dirección de la API **para el navegador** → `localhost`. |
| `CHOKIDAR_USEPOLLING`, `WATCHPACK_POLLING` | Activan la detección de cambios por "sondeo" (ver [7.3](#73-la-recarga-en-caliente-y-windows)). |
| `NEXT_TELEMETRY_DISABLED` | Evita que Next.js envíe estadísticas de uso. |

Además, `FRONTEND_URL` pasó de `http://localhost:3000` a `http://localhost:3002`, porque con Docker
la app Next.js está en el 3002.

### 6.12 Comprobar que el archivo de Compose es correcto

Antes de arrancar nada:

```sh
docker compose config --quiet
```

Si no dice nada, el archivo está bien. Si hay un error, lo explica. (Aquí apareció el
[problema 7.1](#71-el-env-tenía-un-bloque-que-docker-no-entendía).)

Para ver cómo queda el archivo con las variables ya sustituidas:

```sh
docker compose config
```

> ⚠️ Este último comando **muestra los secretos** de tu `.env` en pantalla. No lo copies ni lo
> compartas.

### 6.13 Construir las imágenes y arrancar

```sh
docker compose build        # fabrica las dos imágenes (la primera vez tarda varios minutos)
docker compose up -d        # arranca los contenedores en segundo plano
docker compose ps           # muestra su estado
```

`-d` (*detached*) = "arráncalos y devuélveme la terminal". Sin `-d`, verás todos los mensajes en
directo y la terminal quedará ocupada (se para con `Ctrl + C`).

Atajo que hace todo a la vez: `docker compose up --build`.

---

## 7. Problemas que aparecieron y cómo se resolvieron

Esta sección es probablemente la más útil para aprender: **lo normal es que las cosas no funcionen a
la primera**, y lo importante es saber leer el error.

### 7.1 El `.env` tenía un bloque que Docker no entendía

**Error:**

```
failed to read .env: line 16: unexpected character "{" in variable name "{"
```

**Qué significaba:** "en la línea 16 del `.env` hay una `{` y eso no es una variable". El `.env`
tenía apuntado un usuario de prueba en formato JSON (`{ "name": …, "email": … }`). Python lo
ignoraba, pero Docker es más estricto: cada línea tiene que ser `NOMBRE=valor` o un comentario.

**Solución:** convertir esas líneas en **comentarios** poniendo `# ` delante (no se borró nada). Se
hizo antes una copia de seguridad del `.env`.

**Lección:** en un `.env`, las notas siempre como comentario (`# así`).

### 7.2 La API no arrancaba: problema de codificación de caracteres

**Error (en los registros del backend):**

```
RuntimeError: No se puede abrir la base de datos /app/services/api/db.json:
'utf-8' codec can't decode byte 0xc1 in position 380: invalid start byte.
```

**Qué significaba:** los ordenadores guardan las letras como números, y hay varias "tablas de
traducción" (codificaciones). La letra **Á** (de "Los **Á**ngeles") se había guardado con la tabla
de Windows (*cp1252*), pero el contenedor (Linux) la leía con la tabla universal (*UTF-8*), y no
coincidía.

La causa estaba en el código: TinyDB abría el archivo **sin decir qué tabla usar**, así que usaba
la de cada sistema. **En Windows funcionaba por casualidad.** Docker lo destapó, y eso es
justamente para lo que sirve: que funcione igual en cualquier sitio.

**Solución (dos partes):**

1. En `services/database.py` se indicó la codificación explícitamente:

   ```python
   tinydb = open_tinydb(TINYDB_PATH, encoding="utf-8", ensure_ascii=False, indent=2)
   ```

2. Se convirtió el `db.json` existente a UTF-8 (tras hacer copia de seguridad).

Al guardar `database.py`, la API **se reinició sola** gracias a la recarga en caliente, y en los
registros apareció:

```
WARNING:  StatReload detected changes in 'services/database.py'. Reloading...
INFO:     Application startup complete.
```

### 7.3 La recarga en caliente y Windows

Los programas que detectan cambios normalmente esperan a que el sistema les "avise" de que un
archivo ha cambiado. **Con carpetas compartidas desde Windows (y macOS) esos avisos no llegan al
contenedor.**

**Solución:** el *sondeo* (*polling*): en vez de esperar el aviso, el programa **mira cada poco si
el archivo ha cambiado**. Se activa con:

- `CHOKIDAR_USEPOLLING=true` → para browser-sync (website y backoffice).
- `WATCHPACK_POLLING=true` + la opción `--webpack` → para Next.js.
- Uvicorn (la API) ya usa sondeo por sí mismo en esta instalación.

### 7.4 browser-sync no recargaba

Aunque todo estaba configurado, browser-sync no recargaba. Se probó por partes hasta aislar la
causa: la herramienta que vigila archivos sí funcionaba sola, así que el fallo estaba en cómo se le
pasaba la lista de archivos.

**Causa:** en un primer intento se escribió `--files "…/*.{html,css,js}"` (las llaves significan
"html o css o js"). Pero browser-sync **separa esa opción por comas**, así que lo partía en trozos
sin sentido (`…/*.{html`, `css`, `js}`).

**Solución:** escribir la lista completa separada por comas:

```
--files "…/**/*.html,…/**/*.css,…/**/*.js"
```

Tras cambiar `start.sh` hubo que **reconstruir** (porque `start.sh` está dentro de la imagen):

```sh
docker compose up -d --build interfaces
```

**Lección:** cuando algo no funciona, pruébalo por partes hasta encontrar la pieza que falla.

---

## 8. Cómo se comprobó que todo funciona

| Comprobación | Comando | Resultado |
| --- | --- | --- |
| Estado de los contenedores | `docker compose ps` | Los dos `Up`; el backend `healthy`. |
| La API responde | `curl http://localhost:8000/` | `{"message":"Bienvenid@ a la API de análisis de incidentes"}` |
| Las tres webs responden | `curl -o /dev/null -w "%{http_code}" http://localhost:3000/` (y 3001, 3002) | `200` (= OK) en las tres. |
| **Comunicación por nombre de servicio** | `docker compose exec interfaces wget -qO- http://backend:8000/` | El contenedor de interfaces llega a la API usando el nombre `backend`. ✅ |
| CORS (permiso del navegador) | Petición de prueba con `Origin: http://localhost:3002` | La API responde `access-control-allow-origin: http://localhost:3002`. ✅ |
| Recarga en caliente del website/backoffice | Editar un `.html` desde Windows y mirar los registros | `[Browsersync] Reloading Browsers...` ✅ |
| Recarga en caliente de Next.js | Crear una página de prueba que dice `v1`, cambiarla a `v2` | El navegador pasó a mostrar `v2` sin reiniciar nada. ✅ (la página de prueba se borró) |
| Recarga en caliente de la API | Guardar `services/database.py` | `StatReload detected changes … Reloading...` ✅ |
| Que no se ha roto nada | `uv run --frozen pytest -q` | `775 passed` ✅ |

> `curl` es un programa que hace peticiones web desde la terminal, como un navegador sin
> ventana. `docker compose exec interfaces …` significa "ejecuta este comando **dentro** del
> contenedor `interfaces`".

---

## 9. Uso diario: los comandos que vas a necesitar

### La primera vez (después de clonar el repositorio)

```sh
git clone <url-del-repositorio>
cd <carpeta-del-repositorio>
cp .env.example .env
```

Abre `.env` con tu editor y rellena **como mínimo** `JWT_SECRET_KEY` y `DATABASE_URL` (las
instrucciones están en los comentarios del propio archivo). Luego:

```sh
docker compose up --build
```

Y abre en el navegador:

| Qué | Dirección |
| --- | --- |
| Web pública | http://localhost:3000 |
| Backoffice (incidencias, proveedores, inventario…) | http://localhost:3001 |
| Talent Pipeline (dentro del backoffice, pestaña *Talent Pipeline*) | http://localhost:3001/talent |
| API (documentación interactiva) | http://localhost:8000/docs |

La primera vez el backoffice te llevará a **Iniciar sesión**. Si aún no tienes cuenta, pulsa
*Regístrate*. Hay un único login para todas las secciones.

### Cada día

| Quiero… | Comando |
| --- | --- |
| Arrancar todo | `docker compose up -d` |
| Ver si está en marcha | `docker compose ps` |
| Ver los mensajes (registros) de todo | `docker compose logs -f` (salir con `Ctrl + C`) |
| Ver solo los de la API | `docker compose logs -f backend` |
| Ver solo los de las webs | `docker compose logs -f interfaces` |
| Reiniciar un contenedor | `docker compose restart backend` |
| Apagar todo | `docker compose down` |
| Entrar "dentro" de un contenedor | `docker compose exec backend sh` (salir con `exit`) |

Mientras está en marcha, **simplemente edita los archivos y guarda**: los cambios se aplican solos.

### ¿Qué pasa al hacer `docker compose down`?

**Para los contenedores y además los borra**, junto con la red `trackflow-net`. No es grave: los
contenedores son desechables y el siguiente `docker compose up` crea otros nuevos a partir de las
imágenes. **No se pierde nada importante:**

| Qué | ¿Se pierde? | Por qué |
| --- | --- | --- |
| Tu código | No | Está en tu ordenador; el contenedor solo lo veía por la carpeta compartida. |
| Los datos de TinyDB (`services/api/db.json`) | No | También están en tu ordenador. |
| La base de datos del inventario (Supabase) | No | Está en internet. |
| Las imágenes construidas | No | Por eso el siguiente arranque es rápido. |
| El modelo de IA (volumen `fastembed-cache`) | No | Los volúmenes con nombre sobreviven a `down`. |
| Los registros (`docker compose logs`) | **Sí** | Viven dentro del contenedor. |

Variantes:

| Comando | Qué hace |
| --- | --- |
| `docker compose stop` / `docker compose start` | Solo **pausa** y reanuda, sin borrar los contenedores. |
| `docker compose down -v` | Además **borra los volúmenes**: el modelo de IA (~220 MB) se volverá a descargar. |
| `docker compose down --rmi all` | Además **borra las imágenes**: el siguiente arranque reconstruye todo. |
| `docker volume prune` | Con los contenedores apagados, borra los volúmenes que ya nadie usa (por ejemplo, las cajas de `node_modules` antiguas). |

### Cuándo hay que reconstruir (`--build`)

Solo cuando cambia algo que está **dentro de la imagen**, no el código normal:

| Cambio | Qué hacer |
| --- | --- |
| Editar páginas, componentes o código de la API | Nada, se recarga solo. |
| Añadir/cambiar una librería de **Python** | `uv export --frozen --no-dev --no-hashes --no-emit-project --no-header -o services/requirements.txt` y luego `docker compose up -d --build backend` |
| Añadir/cambiar una librería del **backoffice** (Next.js) | `docker compose up -d --build -V interfaces` |
| Cambiar `start.sh` o un `Dockerfile` | `docker compose up -d --build` |
| Cambiar el `.env` | `docker compose up -d` (Compose recrea los contenedores afectados) |

`-V` renueva los volúmenes anónimos (la "caja" de `node_modules`); sin él, el contenedor seguiría
usando las librerías antiguas.

---

## 10. Si algo falla

| Síntoma | Causa probable | Solución |
| --- | --- | --- |
| `failed to connect to the docker API` | Docker Desktop está cerrado. | Ábrelo y espera a que diga *Engine running*. |
| `Define JWT_SECRET_KEY en .env` | Falta el `.env` o esa variable está vacía. | `cp .env.example .env` y rellénalo. |
| `unexpected character … in variable name` | Hay una línea en `.env` que no es `NOMBRE=valor`. | Conviértela en comentario con `#`. |
| `port is already allocated` | Otro programa usa ese puerto. | Cierra ese programa o cambia el puerto en `.env` (p. ej. `WEBSITE_PORT=4000`). |
| El backend sale `unhealthy` | La API no arranca. | `docker compose logs backend` y lee el último error. |
| Los cambios no se ven | Falta el sondeo o el cambio requiere reconstruir. | Revisa que `.env` tenga `CHOKIDAR_USEPOLLING=true` y `WATCHPACK_POLLING=true`; consulta la tabla "Cuándo hay que reconstruir". |
| El backoffice dice que no puede conectar con el servidor | La API está caída o CORS no incluye el origen. | Comprueba `docker compose ps` y `BACKOFFICE_CORS_ORIGINS`. |
| La primera búsqueda de incidencias tarda mucho | Se está descargando el modelo de IA (~220 MB). | Esperar; solo ocurre una vez. |

Regla general: **lee los registros** (`docker compose logs`). El error casi siempre está en las
últimas líneas.

---

## 11. Producción: la imagen para el VPS

El brief también pedía desplegar en el VPS. Se acordó que **el despliegue lo harás tú**, pero se
dejó preparada una **imagen de producción** y probada en local. Esta sección explica qué es, cómo
se hizo y cómo usarla paso a paso.

### 11.1 ¿Por qué otra imagen? Desarrollo vs. producción

Lo que se montó en la sección 6 es para **desarrollar**: el código entra por carpetas compartidas
y todo se recarga solo. Eso tiene un problema para un servidor: **las imágenes de desarrollo no
llevan el código dentro**. La de interfaces solo trae Node.js y librerías, sin ninguna página, y la
del backend no trae `scripts/` ni `packages/`. Si las subieras a un servidor sin el código, no
arrancarían.

Para producción se creó una imagen distinta, **autónoma**: lleva todo dentro y no depende de
ninguna carpeta del ordenador donde se ejecuta.

| | Desarrollo (`docker-compose.yml`) | Producción (`Dockerfile` de la raíz) |
| --- | --- | --- |
| Número de imágenes | 2 (`interfaces` y `backend`) | 1 (`trackflow`) |
| ¿El código va dentro? | No, llega por carpeta compartida | **Sí** |
| Recarga en caliente | Sí | No (no hace falta en un servidor) |
| Backoffice (Next.js, con el Talent) | `next dev` en el 3001 | `next build` + `next start` en el 3001 (más rápido y ligero) |
| Datos (TinyDB) | `services/api/db.json` de tu ordenador | Volumen de Docker en `/app/data` |
| Cómo se arranca | `docker compose up` | `docker run …` |

### 11.2 Los archivos que se crearon

| Archivo | Para qué |
| --- | --- |
| `Dockerfile` (raíz) | La receta de la imagen de producción. |
| `docker/start-app.sh` | Arranca los tres programas dentro del contenedor. |
| `.dockerignore` (raíz) | Lista de lo que **sí** puede entrar en la imagen (todo lo demás se excluye). |

#### El `Dockerfile` de la raíz, explicado

Está dividido en **dos etapas** (*multi-stage build*). Es como cocinar en una cocina y servir en
otra: en la primera se compila el backoffice (Next.js), con todas las herramientas necesarias, y a la
segunda solo pasa el resultado. Así la imagen final no arrastra herramientas que ya no hacen falta.

**Etapa 1: compilar el backoffice (Next.js)**

```dockerfile
FROM node:22-bookworm-slim AS backoffice-build
WORKDIR /build
COPY uis/backoffice/package.json uis/backoffice/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY uis/backoffice/ ./
ARG NEXT_PUBLIC_AUTH_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WEBSITE_URL=http://localhost:3000/
ENV NEXT_PUBLIC_AUTH_API_URL=$NEXT_PUBLIC_AUTH_API_URL \
    NEXT_PUBLIC_WEBSITE_URL=$NEXT_PUBLIC_WEBSITE_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev --no-audit --no-fund
```

| Instrucción | Qué hace |
| --- | --- |
| `FROM node:22-bookworm-slim AS backoffice-build` | Parte de Node.js 22 sobre Debian ("bookworm") y llama a esta etapa `backoffice-build`. |
| `COPY … package.json …` + `RUN npm ci` | Instala las librerías del backoffice. |
| `COPY uis/backoffice/ ./` | Copia el código de la app. |
| `ARG NEXT_PUBLIC_WEBSITE_URL=…` | Igual que el siguiente, pero con la dirección de la web pública (el logo del backoffice enlaza a ella). |
| `ARG NEXT_PUBLIC_AUTH_API_URL=…` | Un **argumento de construcción**: un valor que se le pasa a `docker build` con `--build-arg` (ver 11.4). |
| `RUN npm run build` | Compila la app para producción (`next build`). |
| `npm prune --omit=dev` | Borra las librerías que solo servían para compilar o para los tests (jest, typescript…). |

> **¿Por qué `NEXT_PUBLIC_AUTH_API_URL` va en la construcción y no en el `.env`?** Next.js
> **escribe** el valor de las variables que empiezan por `NEXT_PUBLIC_` dentro del código que se
> envía al navegador, y lo hace **al compilar**. Una vez compilado, cambiarlo en el `.env` no sirve
> de nada. Por eso se fija en `docker build`, y si cambia la dirección del VPS hay que **reconstruir
> la imagen**.

**Etapa 2: la imagen final**

```dockerfile
FROM node:22-bookworm-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH
COPY services/requirements.txt /tmp/requirements.txt
RUN uv venv --python 3.13 /opt/venv \
 && uv pip install --no-cache -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt
RUN npm install --prefix /opt/serve --no-audit --no-fund serve@14.2.6
```

Esta imagen necesita **a la vez** Node.js (para las webs) y Python (para la API). Se parte de
Node.js y **uv** instala Python 3.13 en un entorno propio (`/opt/venv`), con las librerías de
`requirements.txt`. También se instala **serve**, un pequeño servidor para la web pública
estática.

```dockerfile
WORKDIR /app
COPY services/ services/
COPY scripts/ scripts/
COPY packages/shared/ packages/shared/
COPY csv/ csv/
COPY uis/website/trackflow-web/ uis/website/trackflow-web/
COPY --from=backoffice-build /build uis/backoffice/
```

Aquí se mete **todo el código** en la imagen, con la misma estructura de carpetas que el
repositorio (la API lo necesita así). La última línea trae el backoffice **ya compilado** desde la
etapa 1. `csv/` se incluye para poder cargar las incidencias históricas dentro del contenedor.

```dockerfile
COPY docker/start-app.sh /usr/local/bin/start-app.sh
RUN sed -i 's/\r$//' /usr/local/bin/start-app.sh && chmod +x /usr/local/bin/start-app.sh

ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    TINYDB_PATH=/app/data/db.json \
    EMBEDDINGS_CACHE_DIR=/app/data/fastembed
RUN mkdir -p /app/data \
 && chown -R node:node /app/data /app/uis/backoffice/imagenesPerfil
USER node

EXPOSE 3000 3001 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["start-app.sh"]
```

| Instrucción | Qué hace |
| --- | --- |
| `TINYDB_PATH=/app/data/db.json` | Le dice a la API que guarde la base de datos TinyDB en `/app/data`, **fuera del código**. Ahí se conectará un volumen para que los datos no se pierdan. El archivo de embeddings se guarda junto a ella automáticamente. |
| `EMBEDDINGS_CACHE_DIR=/app/data/fastembed` | El modelo de IA (~220 MB) también se guarda en el volumen: se descarga una sola vez. |
| `chown … node:node` + `USER node` | El contenedor **no se ejecuta como administrador** (`root`), sino como un usuario normal llamado `node`. Si alguien atacara la app, tendría menos permisos. `chown` le da permiso para escribir solo donde lo necesita. |
| `HEALTHCHECK` | Igual que en desarrollo: Docker pregunta cada 30 s a la API "¿estás viva?". |
| `CMD ["start-app.sh"]` | Al arrancar, ejecuta el script que lanza los tres programas. |

#### El script `docker/start-app.sh`

Hace lo mismo que `uis/start.sh` (lanzar varios programas y vigilarlos), pero en modo producción:

```sh
uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers &
/opt/serve/node_modules/.bin/serve /app/uis/website/trackflow-web --listen tcp://0.0.0.0:3000 --no-port-switching &
./node_modules/.bin/next start --hostname 0.0.0.0 --port 3001 &
```

- **API** en el 8000, **sin** `--reload`. Va en **un solo proceso**: TinyDB es un archivo JSON y,
  si varios procesos escribieran a la vez, se podría estropear.
- **Web pública** en el 3000 con `serve`. `--no-port-switching` hace que, si el 3000 estuviera
  ocupado, falle en vez de irse en silencio a otro puerto.
- **Backoffice** (con el Talent Pipeline) en el 3001 con `next start` (la versión compilada).

Si uno de los tres se cae, el script para los demás y el contenedor termina. Así Docker lo
**reinicia solo** gracias a `--restart unless-stopped` (ver 11.6).

#### El `.dockerignore` de la raíz: una lista blanca

```
*

!services/
!scripts/
!packages/shared/
!csv/
!uis/backoffice/
!uis/website/trackflow-web/
!docker/start-app.sh

**/.env*
**/__pycache__
**/*.pyc
**/*.log
**/node_modules
**/.next
**/coverage
**/*.tsbuildinfo
services/api/db*.json
services/Dockerfile
services/.dockerignore
uis/backoffice/__tests__
```

- `*` = "excluye **todo**".
- Las líneas con `!` = "excepto esto". Solo pasan las carpetas que la imagen necesita.
- El último bloque vuelve a quitar, dentro de lo permitido, lo que no debe ir: secretos (`.env*`),
  librerías de tu ordenador, archivos temporales, **tus datos locales** (`db*.json`) y los tests.

¿Por qué una lista blanca y no una lista negra como en desarrollo? Porque en la raíz hay muchas
cosas (`.venv`, `.git`, `audit/`, `.env`, `.coverage`…). Con una lista negra, si mañana alguien
añade una carpeta con algo sensible y se olvida de excluirla, **acabaría dentro de la imagen**. Con
la lista blanca, por defecto no entra nada.

### 11.3 Dónde está el backoffice en producción

Al principio el backoffice era HTML estático, y en el VPS había que abrirlo en
`http://IP:8000/backoffice/`. Su código llamaba siempre a `http://localhost:8000`, que en el VPS
sería **el ordenador del visitante**, y solo funcionaba si lo servía la propia API.

Desde la unificación (sección 12), el backoffice es la app Next.js y lee la dirección de la API de
`NEXT_PUBLIC_AUTH_API_URL`, que se fija al construir la imagen (11.4). Por eso ahora se abre en su
propio puerto: **`http://IP:3001`** (y el Talent Pipeline en `http://IP:3001/talent`). La API ya
**no** sirve `/backoffice/`.

### 11.4 Cómo se construye la imagen

Desde la **raíz** del repositorio, con Docker Desktop abierto:

```sh
docker build -t TU_USUARIO/trackflow:1.0 --build-arg NEXT_PUBLIC_AUTH_API_URL=http://IP_DEL_VPS:8000 --build-arg NEXT_PUBLIC_WEBSITE_URL=http://IP_DEL_VPS:3000/ .
```

| Parte | Qué es | Qué poner |
| --- | --- | --- |
| `docker build` | "Construye una imagen". | — |
| `-t TU_USUARIO/trackflow:1.0` | El **nombre** de la imagen (`-t` = *tag*). | `TU_USUARIO` es tu usuario **exacto** de Docker Hub, `trackflow` el nombre de la app (solo minúsculas, números, `-`, `_` y `.`) y `1.0` la versión. |
| `--build-arg NEXT_PUBLIC_AUTH_API_URL=…` | La dirección pública de la API (ver 11.2). | **Obligatorio.** `http://` + la IP de tu VPS + `:8000`. Si se te olvida, el login del backoffice fallará en el VPS. |
| `--build-arg NEXT_PUBLIC_WEBSITE_URL=…` | La dirección de la web pública: el logo del backoffice enlaza a ella. | `http://` + la IP de tu VPS + `:3000/`. Si se te olvida, el logo apuntará a `localhost:3000`. |
| `.` | La carpeta con el `Dockerfile`: la raíz. | Ejecuta el comando **desde la raíz**. |

La primera vez tarda varios minutos. La imagen ocupa **unos 1,6 GB**, sobre todo por las librerías
de IA de Python. Es normal.

Para ver que existe:

```sh
docker image ls TU_USUARIO/trackflow
```

### 11.5 Cómo se probó en local

Antes de dar la imagen por buena se probó en tu ordenador, en puertos distintos (13000, 13001 y
18000) para no chocar con el entorno de desarrollo. Esta es la prueba repetida **después de la
unificación**:

```sh
docker build -t trackflow:test --build-arg NEXT_PUBLIC_AUTH_API_URL=http://localhost:18000 --build-arg NEXT_PUBLIC_WEBSITE_URL=http://localhost:13000/ .
docker run -d --name trackflow-test --env-file .env -e BACKOFFICE_CORS_ORIGINS=http://localhost:13001 -v trackflow-test-data:/app/data -p 13000:3000 -p 13001:3001 -p 18000:8000 trackflow:test
```

(`-e NOMBRE=valor` sustituye una variable del `.env` solo para este contenedor: aquí, el origen
CORS del backoffice de prueba.)

| Comprobación | Resultado |
| --- | --- |
| API (`/`) y documentación (`/docs`) en el 18000 | `200` ✅ |
| `/backoffice/` en el 18000 (la API ya no sirve HTML) | `404` ✅ |
| Web pública en el 13000 | `200` ✅ |
| Backoffice en el 13001: `/login`, `/`, `/incidents`, `/inventory/products`, `/talent` | `200` ✅ |
| La dirección de la API (`localhost:18000`) y de la web quedaron dentro del código compilado | Sí ✅ |
| CORS: la API permite al backoffice (`localhost:13001`) llamarla con token | Sí ✅ |
| Registrar un usuario de prueba | `201` ✅ |
| **Borrar el contenedor, crear otro nuevo con el mismo volumen** y volver a hacer login | `200`: los datos sobrevivieron ✅ |
| ¿Hay algún `.env` dentro de la imagen? | No ✅ |
| ¿Con qué usuario se ejecuta? | `node`, no `root` ✅ |
| ¿Se borraron las librerías de desarrollo (jest…)? | Sí ✅ |

Al terminar se borró todo lo de prueba:

```sh
docker rm -f trackflow-test
docker volume rm trackflow-test-data
docker image rm trackflow:test
```

> `--env-file .env` le pasa al contenedor las variables del `.env`, igual que hace Compose.
> `-p 18000:8000` es lo mismo que `ports:` en Compose: el puerto 18000 de tu ordenador lleva al 8000
> del contenedor.

### 11.6 Desplegar en el VPS, paso a paso

Hay dos caminos:

- **Camino A (recomendado): subir la imagen a Docker Hub** y que el VPS la descargue. El VPS no
  necesita el código ni compilar nada.
- **Camino B: clonar el repositorio en el VPS** y construir allí la imagen con el mismo
  `docker build`. No necesitas Docker Hub, pero el VPS tiene que compilar, y eso pide más memoria.

A continuación, el camino A completo.

#### Paso 1: subir la imagen a Docker Hub (en tu ordenador)

1. Crea una cuenta en https://hub.docker.com si no la tienes.
2. Crea un repositorio llamado `trackflow` y márcalo como **privado** (*Private*). La imagen lleva
   tu código. Los secretos no van dentro (el `.dockerignore` excluye el `.env`), pero el código sí.
   En el plan gratuito el número de repositorios privados es limitado.
3. Inicia sesión y sube la imagen:

```sh
docker login
docker push TU_USUARIO/trackflow:1.0
```

`docker login` te pide usuario y contraseña (o un *access token* de Docker Hub).

#### Paso 2: preparar el VPS

Requisitos: Ubuntu 22.04 o 24.04, **mínimo 2 GB de RAM** (mejor 4 GB), IP pública y acceso SSH.

Conéctate desde la terminal de tu ordenador:

```sh
ssh root@IP_DEL_VPS
```

A partir de aquí, todo se escribe **dentro del VPS**. Instala Docker con el script oficial:

```sh
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
docker --version
```

#### Paso 3: crear el `.env` en el VPS

```sh
mkdir -p ~/trackflow && cd ~/trackflow
nano .env
```

`nano` es un editor de texto en la terminal: escribe, guarda con `Ctrl + O` y `Enter`, y sal con
`Ctrl + X`. Contenido:

```
JWT_SECRET_KEY=PEGA_AQUI_UNA_CLAVE_NUEVA
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=TU_CADENA_DE_SUPABASE
RESEND_API_KEY=TU_API_KEY_DE_RESEND
EMAIL_FROM=TrackFlow <onboarding@resend.dev>
PASSWORD_RESET_LOG_LINK=false
FRONTEND_URL=http://IP_DEL_VPS:3001
BACKOFFICE_CORS_ORIGINS=http://IP_DEL_VPS:3001
EMBEDDINGS_PROVIDER=fastembed
```

| Variable | Qué poner y por qué |
| --- | --- |
| `JWT_SECRET_KEY` | **Una clave nueva**, distinta de la de tu ordenador. Genérala en el VPS con `openssl rand -hex 64` y pega el resultado. |
| `DATABASE_URL` | La cadena de conexión de Supabase. |
| `RESEND_API_KEY`, `EMAIL_FROM` | Para los correos de restablecer contraseña. |
| `PASSWORD_RESET_LOG_LINK` | **Siempre `false`** en el VPS (si fuera `true`, quien leyera los registros podría cambiar contraseñas). |
| `FRONTEND_URL` | La dirección pública del backoffice: es la base del enlace que llega en el correo de restablecer contraseña. |
| `BACKOFFICE_CORS_ORIGINS` | Las webs a las que la API permite llamarla: el backoffice. La web pública no llama a la API. |

> ⚠️ En el `.env`, cada línea debe ser `NOMBRE=valor` o un comentario que empiece por `#`. Nada de
> bloques JSON (ver problema 7.1).

Protege el archivo para que solo lo pueda leer el administrador:

```sh
chmod 600 .env
```

#### Paso 4: descargar y arrancar la imagen

```sh
docker login
docker pull TU_USUARIO/trackflow:1.0
docker run -d --name trackflow --restart unless-stopped --env-file .env -v trackflow-data:/app/data -p 3000:3000 -p 3001:3001 -p 8000:8000 TU_USUARIO/trackflow:1.0
```

| Parte | Significado |
| --- | --- |
| `docker pull …` | Descarga la imagen desde Docker Hub. |
| `docker run -d` | Crea y arranca un contenedor en segundo plano. |
| `--name trackflow` | Le pone nombre, para referirte a él después (`docker logs trackflow`…). |
| `--restart unless-stopped` | Si el contenedor se cae, o el VPS se reinicia, **vuelve a arrancar solo**, salvo que lo hayas parado tú a propósito. |
| `--env-file .env` | Le pasa los ajustes y secretos del `.env`. |
| `-v trackflow-data:/app/data` | Conecta un **volumen** llamado `trackflow-data` a la carpeta de datos. Los usuarios, las incidencias y el modelo de IA sobreviven aunque borres o actualices el contenedor. |
| `-p 3000:3000 -p 3001:3001 -p 8000:8000` | Publica los tres puertos: web pública, backoffice y API. |

#### Paso 5: comprobar que funciona

```sh
docker ps
docker logs trackflow --tail 30
```

Pasado un minuto, `docker ps` debería mostrar `(healthy)`. Después, desde el navegador de tu
ordenador:

| Qué | Dirección |
| --- | --- |
| Web pública | `http://IP_DEL_VPS:3000` |
| Backoffice | `http://IP_DEL_VPS:3001` |
| Talent Pipeline (pestaña del backoffice) | `http://IP_DEL_VPS:3001/talent` |
| API (documentación) | `http://IP_DEL_VPS:8000/docs` |

#### Paso 6: los datos (elige una opción)

El contenedor empieza con la base de datos TinyDB **vacía**, sin usuarios ni incidencias.

**Opción A: crear un administrador nuevo**

```sh
docker exec trackflow python -m services.api.create_admin admin@ejemplo.com 'una-contraseña-larga' --name "Admin"
```

Y, si quieres, cargar las incidencias históricas del CSV:

```sh
docker exec trackflow python scripts/seed_incidents.py
```

**Opción B: llevar tus datos locales**

Desde **tu ordenador**, en la raíz del repositorio, copia los archivos al VPS:

```sh
scp services/api/db.json services/api/db.embeddings.json root@IP_DEL_VPS:~/trackflow/
```

Y en el **VPS**, mételos en el contenedor, dale permiso al usuario `node` y reinicia:

```sh
cd ~/trackflow
docker cp db.json trackflow:/app/data/db.json
docker cp db.embeddings.json trackflow:/app/data/db.embeddings.json
docker exec -u root trackflow chown node:node /app/data/db.json /app/data/db.embeddings.json
docker restart trackflow
```

`docker exec -u root` ejecuta ese comando **como administrador**, solo esta vez, porque los
archivos copiados con `docker cp` pertenecen a `root` y el usuario `node` no podría escribir en
ellos.

### 11.7 Actualizar a una versión nueva

**En tu ordenador:**

```sh
docker build -t TU_USUARIO/trackflow:1.1 --build-arg NEXT_PUBLIC_AUTH_API_URL=http://IP_DEL_VPS:8000 --build-arg NEXT_PUBLIC_WEBSITE_URL=http://IP_DEL_VPS:3000/ .
docker push TU_USUARIO/trackflow:1.1
```

**En el VPS:**

```sh
cd ~/trackflow
docker pull TU_USUARIO/trackflow:1.1
docker rm -f trackflow
docker run -d --name trackflow --restart unless-stopped --env-file .env -v trackflow-data:/app/data -p 3000:3000 -p 3001:3001 -p 8000:8000 TU_USUARIO/trackflow:1.1
```

`docker rm -f trackflow` borra el contenedor viejo, pero **no** el volumen: tus datos siguen ahí y
el contenedor nuevo los usa. Si algo sale mal con la 1.1, vuelve a lanzar el mismo `docker run`
con `1.0`. Para eso sirve numerar las versiones.

### 11.8 Comandos útiles en el VPS

| Quiero… | Comando |
| --- | --- |
| Ver si está en marcha | `docker ps` |
| Ver los registros en directo | `docker logs -f trackflow` (salir con `Ctrl + C`) |
| Reiniciar | `docker restart trackflow` |
| Parar | `docker stop trackflow` |
| Volver a arrancarlo | `docker start trackflow` |
| Entrar dentro del contenedor | `docker exec -it trackflow sh` (salir con `exit`) |
| Ver los volúmenes | `docker volume ls` |

> ⚠️ **No ejecutes `docker volume rm trackflow-data`** salvo que quieras borrar **todos** los datos
> de producción.

### 11.9 Lo que todavía queda pendiente

Lo anterior deja la plataforma funcionando en el VPS, pero hay tres mejoras importantes para un
entorno de producción serio:

1. **HTTPS (el candado del navegador).** Ahora todo va por `http`, así que las contraseñas del
   login viajan sin cifrar. Se necesita un **dominio** que apunte a la IP del VPS y un *proxy
   inverso* como **Caddy**, que consigue el certificado gratis y automáticamente. Cuando haya
   dominio, también cambian `NEXT_PUBLIC_AUTH_API_URL` y `NEXT_PUBLIC_WEBSITE_URL` (y hay que
   reconstruir la imagen), `FRONTEND_URL` y `BACKOFFICE_CORS_ORIGINS`.
2. **Puertos abiertos al mundo.** Ojo: **Docker se salta el cortafuegos `ufw`** de Ubuntu en los
   puertos que publica con `-p`, así que activar `ufw` no basta para cerrarlos. Con un proxy
   inverso, solo se abrirían el 80 y el 443.
3. **Fotos de perfil del Talent Pipeline.** Se guardan dentro del contenedor (carpeta
   `uis/backoffice/imagenesPerfil`) y **se pierden al actualizarlo**. Arreglarlo requiere un pequeño
   cambio en el código para guardarlas en `/app/data`.

---

## 12. Unificación del backoffice y el Talent Pipeline (Next.js)

Después de dockerizar el proyecto se pidió un cambio: **el Talent Pipeline Tracker debe formar
parte del backoffice, los dos hechos con Next.js, con una pestaña en la barra superior del
backoffice para entrar al Talent, y sin perder ninguna funcionalidad.**

### 12.1 Las decisiones (preguntadas antes de empezar)

Antes de tocar nada se revisó todo el código y se preguntaron las dudas que cambiaban el resultado:

| Pregunta | Decisión |
| --- | --- |
| ¿Dónde vive la app unificada y con qué direcciones? | En `uis/backoffice`. El backoffice ocupa la raíz (`/`, `/incidents`…) y el Talent pasa a `/talent`. Un solo puerto: el **3001**. |
| Había **dos logins** (el del backoffice, solo entrar; y el de Next.js, con registro, recuperar contraseña y perfil). | **Uno solo, el de Next.js**, que es el más completo. Los dos ya guardaban el mismo token. |
| ¿Qué hacer con el backoffice antiguo (HTML estático, que también servía la API en `:8000/backoffice/`)? | **Retirarlo** y adaptar los tests para que hagan las mismas comprobaciones sobre la app nueva (opción A). |
| Dos pantallas (gestor y registro de incidencias) tenían botón español/inglés; el resto, solo español. | **Mantenerlo igual.** |

### 12.2 Antes y después

| | Antes | Después |
| --- | --- | --- |
| Carpetas | `uis/backoffice/` (HTML + JS) y `uis/talent-pipeline-tracker/` (Next.js) | `uis/backoffice/` (una sola app Next.js) |
| Puertos en Docker | 3000 web · 3001 backoffice · 3002 Talent | 3000 web · **3001 backoffice con el Talent** |
| Logins | 2 (sesiones separadas) | 1 para todo |
| Cabecera | Distinta en cada app | Común, con la pestaña **Talent Pipeline**, tu perfil y «Cerrar sesión» |
| ¿La API sirve HTML? | Sí, el backoffice en `:8000/backoffice/` | No, solo datos |

Direcciones nuevas (las antiguas **redirigen** solas a las nuevas):

| Pantalla | Antes | Ahora |
| --- | --- | --- |
| Analizador de CSV | `index.html` | `/` |
| Gestor de incidencias | `incidents.html` | `/incidents` |
| Registrar incidencia | `incident-new.html` | `/incidents/new` |
| Proveedores | `suppliers.html` | `/suppliers` |
| Inventario | `inventory/products/`… | `/inventory/products`… (y `/inventory` lleva al stock) |
| Login | `login.html` (y `/login` en el Talent) | `/login` |
| Talent: listado y detalle | `:3002/` y `:3002/records/{id}` | `/talent` y `/talent/records/{id}` |
| Perfil y contraseña | `:3002/account/...` | `/account/profile`, `/account/change-password` |

### 12.3 Conceptos nuevos (sin tecnicismos)

- **React** es una forma de construir páginas a base de **componentes**: piezas que se pintan
  solas según unos datos. El backoffice antiguo funcionaba al revés: el HTML venía fijo y un
  JavaScript iba "tocando" la página (mostrar esto, esconder aquello). Portarlo a React significa
  reescribir cada pantalla como componentes que **dicen cómo debe verse la página según el estado**
  ("si está cargando, enseña el aviso de carga").
- **Estado**: los datos que una pantalla recuerda mientras la usas (el archivo elegido, los
  filtros, si está guardando…). Cuando el estado cambia, React vuelve a pintar lo necesario.
- **Next.js (App Router)** decide las direcciones a partir de las **carpetas**: la carpeta
  `app/(protected)/incidents/new/` con un archivo `page.tsx` dentro es la página `/incidents/new`.
  Las carpetas entre paréntesis, como `(protected)`, **no** aparecen en la dirección: sirven para
  agrupar páginas que comparten algo.
- **Layout**: un marco común a varias páginas. Aquí `app/(protected)/layout.tsx` es el marco de
  todas las pantallas con sesión: primero comprueba que hay sesión (si no, lleva al login) y luego
  pinta la cabecera común. Todas las páginas de dentro lo heredan.
- **Redirección**: cuando pides una dirección antigua, el servidor te responde "eso ahora está en
  otro sitio" y el navegador va allí solo.

### 12.4 El proceso, paso a paso

**1. Leer todo antes de escribir.** Se leyeron las 11 páginas del backoffice antiguo (unas 4.000
líneas de HTML y JavaScript), la app del Talent y los tests. La propia app Next.js trae un aviso
para quien la programe (`uis/backoffice/AGENTS.md`): *esta versión de Next.js (la 16) tiene
cambios importantes; lee su documentación local antes de escribir código*. Se consultó
(`node_modules/next/dist/docs/`) para las rutas, los layouts, los títulos de página y las
redirecciones.

**2. Medir el punto de partida.** Se ejecutaron los tests de interfaz **antes** de cambiar nada,
para saber qué funcionaba ya:

```sh
node tests/ui/run.mjs backoffice inventory talent
```

Resultado: inventario 39/39 ✅; las suites `backoffice` y `talent` **ya fallaban**, porque se
escribieron antes de que existiera el login. Al adaptarlas, también se arreglaron.

**3. Retirar lo antiguo y mover la app.** Con los contenedores parados (`docker compose down`,
porque tenían esas carpetas montadas):

```sh
cd uis
rm -rf backoffice                                   # el HTML/JS antiguo (sigue en el historial de Git)
rm -rf talent-pipeline-tracker/.next talent-pipeline-tracker/coverage   # archivos generados
mv talent-pipeline-tracker backoffice               # la app Next.js pasa a ser el backoffice
```

**4. Llevar el Talent a `/talent`.** Bastó con mover carpetas dentro de `app/(protected)/`:

```sh
cd backoffice/app/\(protected\)
mkdir talent
mv page.tsx talent/page.tsx          # el listado: de / a /talent
mv records talent/records            # el detalle: de /records/{id} a /talent/records/{id}
```

Al mover un archivo un nivel más adentro, sus `import` con rutas relativas (`../../lib/…`) dejan
de apuntar bien: se corrigieron. También los enlaces internos (`/records/…` → `/talent/records/…`,
«Volver al listado» → `/talent`).

**5. Código común.** Para que las pantallas no repitan código:

| Archivo | Qué tiene |
| --- | --- |
| `app/lib/auth.ts` (ya existía) | Se añadió `backofficeFetch`: hace la llamada a la API **con el token** y, si la sesión ha caducado, la cierra y el guard lleva al login. Las funciones que ya usaba el Talent no cambiaron. |
| `app/lib/incidents.ts` | Valores del modelo de incidencias, llamadas a `/api/incidents`, mensajes de error y **los textos en español e inglés**. |
| `app/lib/suppliers.ts` | Categorías, monedas, llamadas a `/suppliers` y mensajes de error. |
| `app/lib/inventory.ts` | Llamadas a `/inventory`, traducción de los errores de la API (stock insuficiente, validación…), niveles de stock y formatos. |
| `app/ui/incidents-lang.tsx` | El idioma de las pantallas de incidencias (se recuerda en el navegador). |
| `app/ui/backoffice-header.tsx` | La cabecera común con la pestaña **Talent Pipeline**. |

Los textos bilingües (unas 260 líneas) **no se copiaron a mano**: se sacaron del archivo
original guardado en Git, para no cometer erratas:

```sh
git show HEAD:uis/backoffice/incidents-common.js
```

`git show HEAD:ruta` enseña cómo era un archivo en el último commit, aunque ya no exista.

**6. Portar cada pantalla.** Una a una (analizador, gestor, registro, proveedores y las cuatro de
inventario), conservando **los mismos textos, colores, identificadores de los elementos y
comportamiento**: los mismos mensajes de error, los mismos avisos, el mismo orden de validación, el
cambio de estado "optimista" que vuelve atrás si falla, etc. Cada pantalla tiene dos archivos:

- `page.tsx`: pone el **título** de la pestaña del navegador y carga el componente.
- `…-client.tsx`: la pantalla en sí. Empieza por `"use client"` porque se ejecuta en el navegador
  (lee el token, reacciona a clics…).

**7. Redirecciones** para no romper enlaces ni marcadores antiguos, en `uis/backoffice/next.config.ts`:

```ts
{ source: "/incidents.html", destination: "/incidents", permanent: false },
{ source: "/records/:id", destination: "/talent/records/:id", permanent: false },
// …
```

**8. Backend.** En `services/api/main.py` se quitaron las líneas que servían el HTML en
`/backoffice/`, y los orígenes CORS por defecto pasaron a ser el del backoffice
(`http://localhost:3001`).

**9. Docker.** Todo pasa del 3002 al 3001:

| Archivo | Cambio |
| --- | --- |
| `uis/Dockerfile` | Instala browser-sync para la web y las librerías del backoffice en `/app/backoffice`. |
| `uis/start.sh` | Arranca dos servidores: la web (3000) y `next dev` del backoffice (3001). |
| `docker-compose.yml` | Quita el puerto 3002, protege `/app/backoffice/node_modules`, `FRONTEND_URL` y CORS al 3001, añade `NEXT_PUBLIC_WEBSITE_URL` y la API ya no monta `uis/backoffice`. |
| `Dockerfile` (producción), `docker/start-app.sh`, `.dockerignore` | Compilan y arrancan el backoffice en el 3001 (ver sección 11). |
| `.env.example` y tu `.env` | `FRONTEND_URL` al 3001; fuera `TALENT_TRACKER_PORT`; CORS solo al 3001; nueva `NEXT_PUBLIC_WEBSITE_URL`. |

**10. Tests.** Para demostrar que no se ha perdido nada:

| Qué | Comando | Resultado |
| --- | --- | --- |
| Tests del backend | `uv run --frozen pytest -q` | **773 ✅** (los 4 que comprobaban el HTML en `/backoffice/` se sustituyeron por uno que comprueba que ya no se sirve, y se añadió uno de CORS) |
| Tests unitarios de la app (Jest) | `npm --prefix uis/backoffice test` | **148 ✅** |
| Tipos de TypeScript | `npx tsc --noEmit` (en `uis/backoffice`) | sin errores ✅ |
| Compilación de producción | `npx next build` (en `uis/backoffice`) | ✅ las 19 rutas |
| Tests de interfaz (navegador real) | `node tests/ui/run.mjs` | **180/181** (el que falla es `TAL-004-typing`, un fallo que ya tenía el Talent: ver 12.7) |
| Dataset real por el analizador | `node tests/ui/ua4_dataset_reference.mjs` | **13/13 ✅**, igual que el *golden* |

Los tests de interfaz abren un Chrome sin ventana, inician sesión con una cuenta de prueba y usan
la app como lo haría una persona:

| Suite | Pantallas | Comprobaciones |
| --- | --- | --- |
| `website` | web pública (sin cambios) | 36 |
| `backoffice` | analizador `/` + cabecera con la pestaña *Talent Pipeline* | 31 |
| `incidents` (**nueva**) | `/incidents` e `/incidents/new`, en los dos idiomas | 23 |
| `suppliers` (**nueva**) | `/suppliers` | 14 |
| `inventory` | las cuatro de `/inventory` | 40 |
| `talent` | `/talent` (contra la API real de 4Geeks, solo lectura) | 37 (36 en las ejecuciones completas; ver 12.7) |

Las suites de incidencias y proveedores no existían: se crearon para que **esas pantallas también
quedaran probadas** tras el cambio.

### 12.5 Problemas que aparecieron

1. **Los tests no podían "escribir" en los formularios de React.** Los tests antiguos ponían el
   valor directamente (`campo.value = "7"`). React no se entera de eso: guarda su propia copia del
   valor. La solución fue usar el mismo mecanismo interno que usa el navegador cuando escribes
   (*setter nativo* + evento), en `tests/ui/lib/backoffice-app.mjs`.
2. **El lint de React marcaba un patrón.** La configuración del proyecto no permite cambiar el
   estado nada más abrir una pantalla (provoca repintados de más). Se reorganizaron las cargas para
   que el estado inicial ya sea "cargando" y solo se actualice al llegar la respuesta.
3. **Un error real que encontraron los tests nuevos.** En Proveedores, tras pulsar «Suspender», el
   botón «Reactivar» se quedaba deshabilitado. La causa: React reutilizaba la fila porque el
   proveedor no cambiaba su fecha de última tarifa. Se arregló haciendo que la fila se rehaga
   siempre que cambie el proveedor, como hacía el backoffice antiguo al repintar la tabla.
4. **Tests desactualizados del Talent.** Uno esperaba el texto «Ocurrió un error… 404», pero el
   Talent ya mostraba «Candidatura no encontrada» antes de este cambio. Se actualizó la prueba.

### 12.6 Cómo comprobarlo tú

```sh
docker compose up -d --build -V
```

`-V` es importante la primera vez después de este cambio: crea de cero la "caja" de librerías del
backoffice (antes era la del Talent). Luego abre http://localhost:3001, inicia sesión (o
regístrate) y usa la barra superior: **Incidentes, Gestor de incidencias, Registrar incidencia,
Proveedores, Inventario y Talent Pipeline**.

Para repetir las pruebas (necesitas `uv sync`, `npm ci` en `uis/backoffice` y Google Chrome):

```sh
uv run --frozen pytest -q
npm --prefix uis/backoffice test
node tests/ui/run.mjs
```

### 12.7 Observaciones

- **Fallo previo del Talent: se pueden perder letras en la búsqueda.** La prueba `TAL-004-typing`
  (escribir una búsqueda letra a letra) pasa cuando la suite del Talent se ejecuta sola, pero falla
  en la ejecución completa, cuando el ordenador va más cargado. La causa está en el código del
  Talent, que no se ha tocado: el cuadro de búsqueda no guarda lo que escribes, sino que muestra el
  valor de la dirección (`?search=…`) y cambia la dirección con cada tecla. Si se teclea más rápido
  de lo que se actualiza la dirección, la siguiente letra se escribe sobre el valor antiguo y se
  pierde. Se arregla guardando el texto en el propio cuadro y actualizando la dirección después.
  Queda pendiente de decidir, porque cambia el comportamiento del Talent.
- El lint del Talent tiene **dos avisos que ya existían** antes de este cambio (en el detalle de una
  candidatura). No se han tocado para no cambiar su comportamiento.
- El registro de cuentas (`/register`) sigue siendo **público**, como en el Talent. Si el panel
  interno no debe permitir que cualquiera se cree una cuenta, habría que quitarlo o limitarlo.

---

## 13. Resumen de archivos creados y modificados

**Creados**

| Archivo | Para qué |
| --- | --- |
| `docker-compose.yml` | Plano del jardín: los dos contenedores, puertos, red, variables y carpetas compartidas. |
| `uis/Dockerfile` | Receta del contenedor de interfaces. |
| `uis/start.sh` | Arranca la web pública y el backoffice dentro del contenedor. |
| `uis/.dockerignore` | Qué no meter en la imagen de interfaces. |
| `uis/website/package.json` + `package-lock.json` | Dependencia browser-sync del website. |
| `services/Dockerfile` | Receta del contenedor de la API. |
| `services/.dockerignore` | Qué no meter en la imagen de la API. |
| `services/requirements.txt` | Lista de librerías de Python (generada desde `uv.lock`). |
| `.gitattributes` | Fuerza finales de línea de Linux en los `.sh`. |
| `Dockerfile` (raíz) | Receta de la **imagen de producción** autónoma para el VPS. |
| `docker/start-app.sh` | Arranca la API, la web pública y el backoffice en la imagen de producción. |
| `.dockerignore` (raíz) | Lista blanca de lo que puede entrar en la imagen de producción. |
| `hito_10.md` | Este documento. |

**Creados en la unificación (sección 12)**

| Archivo | Para qué |
| --- | --- |
| `uis/backoffice/app/(protected)/page.tsx` + `analyzer-client.tsx` | Analizador de CSV (`/`). |
| `uis/backoffice/app/(protected)/incidents/…` | Gestor (`/incidents`) y registro (`/incidents/new`) de incidencias. |
| `uis/backoffice/app/(protected)/suppliers/…` | Proveedores (`/suppliers`). |
| `uis/backoffice/app/(protected)/inventory/…` | Las cuatro pantallas de inventario y su subnavegación. |
| `uis/backoffice/app/lib/incidents.ts`, `suppliers.ts`, `inventory.ts` | Llamadas a la API, textos y reglas de cada sección. |
| `uis/backoffice/app/ui/backoffice-header.tsx` | Cabecera común con la pestaña **Talent Pipeline**. |
| `uis/backoffice/app/ui/incidents-lang.tsx`, `incidents-common.tsx`, `inventory-ui.tsx` | Idioma y piezas visuales compartidas. |
| `tests/ui/lib/backoffice-app.mjs` | Arranque de API + backoffice y sesión para los tests de interfaz. |
| `tests/ui/incidents.mjs`, `tests/ui/suppliers.mjs` | Tests de interfaz nuevos. |

**Modificados**

| Archivo | Cambio |
| --- | --- |
| `.env.example` | Nueva sección de Docker; `FRONTEND_URL` y CORS al 3001 (backoffice). |
| `.gitignore` | Añadido `node_modules/`. |
| `README.md` | Nueva sección "Entorno de desarrollo con Docker". |
| `services/database.py` | TinyDB abre el archivo siempre en UTF-8. |
| `services/api/main.py` | Ya no sirve el HTML de `/backoffice/`; CORS por defecto al 3001. |
| `uis/backoffice/` (antes `uis/talent-pipeline-tracker/`) | Es la app unificada: Talent en `/talent`, login para todo, `package.json` con el puerto 3001, `next.config.ts` con redirecciones. |
| `tests/test_api_characterization.py`, `tests/test_auth.py` | Adaptados a que la API ya no sirve `/backoffice/`. |
| `tests/ui/backoffice.mjs`, `inventory.mjs`, `talent.mjs`, `ua4_dataset_reference.mjs` | Adaptados a la app Next.js con sesión. |
| `.env` (no se sube a Git) | Bloque JSON comentado y `FRONTEND_URL` al 3001. |
| `services/api/db.json` (no se sube a Git) | Convertido a UTF-8. |

**Eliminados**

| Archivo | Motivo |
| --- | --- |
| `uis/backoffice/*.html`, `*.js`, `inventory/` (el backoffice estático) | Sustituidos por las pantallas Next.js. Siguen en el historial de Git. |

---

## 14. Glosario

| Término | Significado sencillo |
| --- | --- |
| **API** | Programa que no tiene pantalla: recibe peticiones y devuelve datos. Aquí, la hecha con FastAPI. |
| **Backend / frontend** | Backend = la parte "de detrás" (API, datos). Frontend = lo que se ve en el navegador. |
| **Bind mount** | Carpeta compartida entre tu ordenador y un contenedor. |
| **Build arg (`--build-arg`)** | Valor que se le pasa a `docker build` y que queda fijado dentro de la imagen al construirla. |
| **browser-sync** | Pequeño servidor web que recarga la página al guardar cambios. |
| **Contenedor** | Programa en marcha dentro de su "maceta" aislada. |
| **CORS** | Regla de seguridad de los navegadores: una web solo puede llamar a una API de otro puerto/dominio si la API lo permite. |
| **Dependencia / librería** | Código hecho por otros que tu proyecto usa. |
| **Docker Compose** | Herramienta para arrancar varios contenedores juntos a partir de `docker-compose.yml`. |
| **Docker Hub** | "Almacén" en internet donde se suben imágenes para descargarlas desde otro ordenador (por ejemplo, el VPS). |
| **Etiqueta (tag)** | La parte tras los dos puntos en el nombre de una imagen (`:1.0`); normalmente, la versión. |
| **Lista blanca** | Forma de excluir: se prohíbe todo y solo se permite lo que se nombra expresamente. |
| **Multi-stage build** | Dockerfile en varias etapas: se compila en una y a la imagen final solo pasa el resultado. |
| **Proxy inverso** | Programa (como Caddy) que recibe las visitas en los puertos 80/443, pone el HTTPS y las reparte a cada app. |
| **Dockerfile** | Receta para fabricar una imagen. |
| **`.env`** | Archivo con ajustes y secretos. Nunca se sube a Git. |
| **Healthcheck** | Pregunta periódica de Docker a un contenedor: "¿estás bien?". |
| **Hot reload** | Recarga automática al guardar un archivo. |
| **Imagen** | Molde ya preparado a partir del cual se crean contenedores. |
| **`localhost`** | "Este mismo ordenador". Dentro de un contenedor: "este mismo contenedor". |
| **Next.js** | Herramienta para crear webs con React. |
| **App Router** | Forma de Next.js de definir las direcciones con carpetas: `app/incidents/page.tsx` es `/incidents`. |
| **Componente (React)** | Pieza de una pantalla que se pinta sola a partir de unos datos (una tabla, un botón, un formulario…). |
| **Estado** | Lo que una pantalla recuerda mientras la usas (filtros, archivo elegido, "guardando…"). |
| **Layout** | Marco común a varias páginas (por ejemplo, la cabecera y la comprobación de sesión). |
| **Jest** | Herramienta para los tests unitarios del código JavaScript/TypeScript. |
| **Lint** | Revisión automática del código que avisa de patrones problemáticos. |
| **Redirección** | Respuesta del servidor que dice "esto ahora está en otra dirección"; el navegador va allí solo. |
| **Nombre de servicio** | Nombre con el que un contenedor encuentra a otro dentro de la red de Docker (`backend`, `interfaces`). |
| **Polling (sondeo)** | Mirar cada poco si un archivo ha cambiado, en lugar de esperar a que avisen. |
| **Puerto** | "Puerta" numerada por la que entra una conexión (3000, 8000…). |
| **Red de Docker** | Red privada donde los contenedores se comunican entre sí. |
| **Uvicorn** | Programa que pone en marcha la API de FastAPI. |
| **uv** | Herramienta para instalar librerías de Python rápidamente. |
| **UTF-8** | La forma universal de guardar letras (con tildes, eñes, etc.) como números. |
| **Usuario `root`** | El administrador de un sistema Linux, con todos los permisos. Por seguridad, la imagen de producción no se ejecuta como `root`. |
| **Volumen** | Espacio de almacenamiento que gestiona Docker y que sobrevive aunque el contenedor se borre. |
| **VPS** | Servidor alquilado en internet donde se publica el proyecto (producción). |
