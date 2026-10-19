# Hito 10 — Dockerizar el proyecto TrackFlow (ticket #infra-40)

Este documento explica, paso a paso y sin dar nada por sabido, cómo se ha preparado el proyecto
para que **cualquier persona pueda arrancarlo en su ordenador con un solo comando**, sin tener que
instalar Python, Node.js ni ninguna librería a mano.

Está pensado para leerse de principio a fin. Si en algún momento quieres repetir el proceso tú
solo, la [sección 6](#6-el-proceso-paso-a-paso) tiene todos los pasos en orden, con los comandos
exactos.

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
11. [Lo que queda pendiente (el VPS)](#11-lo-que-queda-pendiente-el-vps)
12. [Resumen de archivos creados y modificados](#12-resumen-de-archivos-creados-y-modificados)
13. [Glosario](#13-glosario)

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
| Backoffice | http://localhost:3001 |
| Talent Pipeline Tracker | http://localhost:3002 |
| API (documentación interactiva) | http://localhost:8000/docs |

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

### Cuándo hay que reconstruir (`--build`)

Solo cuando cambia algo que está **dentro de la imagen**, no el código normal:

| Cambio | Qué hacer |
| --- | --- |
| Editar páginas, componentes o código de la API | Nada, se recarga solo. |
| Añadir/cambiar una librería de **Python** | `uv export --frozen --no-dev --no-hashes --no-emit-project --no-header -o services/requirements.txt` y luego `docker compose up -d --build backend` |
| Añadir/cambiar una librería de la app **Next.js** | `docker compose up -d --build -V interfaces` |
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

## 11. Lo que queda pendiente (el VPS)

El brief también pedía desplegar en el VPS de producción. **Se acordó dejarlo para más adelante y
que lo hagas tú.** Cosas a tener en cuenta cuando llegue el momento:

- Lo que hemos montado es un entorno de **desarrollo** (recarga en caliente, carpetas compartidas).
  En producción no se usan carpetas compartidas: el código tiene que ir **dentro** de la imagen.
- La imagen del backend necesitará incluir también `scripts/` y `packages/` (hoy llegan por carpeta
  compartida). Lo habitual es construirla desde la raíz del repositorio.
- Las webs estáticas se servirían con un servidor web normal y la app Next.js con
  `next build` + `next start`.
- El `.env` de producción vive **solo en el VPS**, nunca en Git, con valores propios (otra
  `JWT_SECRET_KEY`, las URLs públicas reales en `FRONTEND_URL`, `NEXT_PUBLIC_AUTH_API_URL` y
  `BACKOFFICE_CORS_ORIGINS`, y `PASSWORD_RESET_LOG_LINK=false`).

---

## 12. Resumen de archivos creados y modificados

**Creados**

| Archivo | Para qué |
| --- | --- |
| `docker-compose.yml` | Plano del jardín: los dos contenedores, puertos, red, variables y carpetas compartidas. |
| `uis/Dockerfile` | Receta del contenedor de interfaces. |
| `uis/start.sh` | Arranca las tres webs dentro del contenedor. |
| `uis/.dockerignore` | Qué no meter en la imagen de interfaces. |
| `uis/website/package.json` + `package-lock.json` | Dependencia browser-sync del website. |
| `uis/backoffice/package.json` + `package-lock.json` | Dependencia browser-sync del backoffice. |
| `services/Dockerfile` | Receta del contenedor de la API. |
| `services/.dockerignore` | Qué no meter en la imagen de la API. |
| `services/requirements.txt` | Lista de librerías de Python (generada desde `uv.lock`). |
| `.gitattributes` | Fuerza finales de línea de Linux en los `.sh`. |
| `hito_10.md` | Este documento. |

**Modificados**

| Archivo | Cambio |
| --- | --- |
| `.env.example` | Nueva sección de Docker y `FRONTEND_URL` al 3002. |
| `.gitignore` | Añadido `node_modules/`. |
| `README.md` | Nueva sección "Entorno de desarrollo con Docker". |
| `services/database.py` | TinyDB abre el archivo siempre en UTF-8. |
| `.env` (no se sube a Git) | Bloque JSON comentado y `FRONTEND_URL` al 3002. |
| `services/api/db.json` (no se sube a Git) | Convertido a UTF-8. |

---

## 13. Glosario

| Término | Significado sencillo |
| --- | --- |
| **API** | Programa que no tiene pantalla: recibe peticiones y devuelve datos. Aquí, la hecha con FastAPI. |
| **Backend / frontend** | Backend = la parte "de detrás" (API, datos). Frontend = lo que se ve en el navegador. |
| **Bind mount** | Carpeta compartida entre tu ordenador y un contenedor. |
| **browser-sync** | Pequeño servidor web que recarga la página al guardar cambios. |
| **Contenedor** | Programa en marcha dentro de su "maceta" aislada. |
| **CORS** | Regla de seguridad de los navegadores: una web solo puede llamar a una API de otro puerto/dominio si la API lo permite. |
| **Dependencia / librería** | Código hecho por otros que tu proyecto usa. |
| **Docker Compose** | Herramienta para arrancar varios contenedores juntos a partir de `docker-compose.yml`. |
| **Dockerfile** | Receta para fabricar una imagen. |
| **`.env`** | Archivo con ajustes y secretos. Nunca se sube a Git. |
| **Healthcheck** | Pregunta periódica de Docker a un contenedor: "¿estás bien?". |
| **Hot reload** | Recarga automática al guardar un archivo. |
| **Imagen** | Molde ya preparado a partir del cual se crean contenedores. |
| **`localhost`** | "Este mismo ordenador". Dentro de un contenedor: "este mismo contenedor". |
| **Next.js** | Herramienta para crear webs con React. |
| **Nombre de servicio** | Nombre con el que un contenedor encuentra a otro dentro de la red de Docker (`backend`, `interfaces`). |
| **Polling (sondeo)** | Mirar cada poco si un archivo ha cambiado, en lugar de esperar a que avisen. |
| **Puerto** | "Puerta" numerada por la que entra una conexión (3000, 8000…). |
| **Red de Docker** | Red privada donde los contenedores se comunican entre sí. |
| **Uvicorn** | Programa que pone en marcha la API de FastAPI. |
| **uv** | Herramienta para instalar librerías de Python rápidamente. |
| **UTF-8** | La forma universal de guardar letras (con tildes, eñes, etc.) como números. |
| **Volumen** | Espacio de almacenamiento que gestiona Docker y que sobrevive aunque el contenedor se borre. |
| **VPS** | Servidor alquilado en internet donde se publica el proyecto (producción). |
