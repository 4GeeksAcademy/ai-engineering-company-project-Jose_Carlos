# TrackFlow Web Project

[![4Geeks Academy](https://img.shields.io/badge/4Geeks-Academy-blue)](https://4geeksacademy.com)
[![AI Engineering](https://img.shields.io/badge/track-AI%20Engineering-green)](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)

Entrega del proyecto web de TrackFlow, una empresa de transporte y logistica con seguimiento en tiempo real y atencion personalizada.

## Vision general

Este repositorio presenta una primera version funcional de la presencia digital de TrackFlow. El proyecto resuelve dos necesidades principales:

- presentar la marca con una landing clara, responsive y orientada a conversion,
- ofrecer un flujo inicial para enviar, rastrear y solicitar contacto desde una aplicacion web.

La solucion se ha desarrollado con una arquitectura frontend simple y mantenible, priorizando claridad, usabilidad y una organizacion de repo mas cercana a un proyecto real de entrega.

## Alcance de la entrega

La entrega actual incluye:

- Landing corporativa con propuesta de valor, beneficios, historia de marca y CTAs.
- Aplicacion operativa para particulares y empresas.
- Formularios con validacion en frontend.
- Flujo de rastreo con formato controlado.
- SEO basico tecnico con metadatos, Open Graph y JSON-LD.
- Documentacion funcional y tecnica separada del codigo fuente.

## Estructura final del proyecto

El repositorio ya no usa la raiz como contenedor de archivos sueltos. La entrega queda organizada por responsabilidad:

- [uis/website/trackflow-web](uis/website/trackflow-web): codigo fuente de la web publica.
- [uis/website/trackflow-web/index.html](uis/website/trackflow-web/index.html): landing principal.
- [uis/website/trackflow-web/application.html](uis/website/trackflow-web/application.html): aplicacion de envio, rastreo y contacto.
- [uis/website/trackflow-web/README.md](uis/website/trackflow-web/README.md): README especifico de la app web.
- [docs/trackflow-web](docs/trackflow-web): documentacion de la entrega.
- [docs/trackflow-web/README.md](docs/trackflow-web/README.md): resumen funcional y tecnico.
- [docs/trackflow-web/explicacion-index-html-trackflow.md](docs/trackflow-web/explicacion-index-html-trackflow.md): desglose detallado de la implementacion.

## Funcionalidades principales

### Landing

- Hero con carrusel de mensajes comerciales.
- Menu responsive y panel de login desplegable.
- Seccion de beneficios orientada a propuesta de valor.
- Registro de usuarios desde la propia portada.
- CTA hacia el flujo operativo.

### Aplicacion

- Flujo para particulares con envio y rastreo.
- Flujo para empresas con formulario de consulta.
- Seleccion de paises europeos.
- Gestion dinamica de multiples paquetes.
- Validacion de emails, numericos y tracking.

### Calidad de la experiencia

- Interfaz responsive.
- Uso de HTML semantico.
- Estados accesibles con atributos ARIA.
- JavaScript vanilla con logica separada por comportamiento.

## Stack tecnologico

- HTML5
- Tailwind CSS via CDN
- JavaScript vanilla
- JSON-LD para SEO semantico

## Como revisar la entrega

1. Abrir [uis/website/trackflow-web/index.html](uis/website/trackflow-web/index.html).
2. Recorrer la landing y validar navegacion, formularios y CTA.
3. Entrar en [uis/website/trackflow-web/application.html](uis/website/trackflow-web/application.html) para probar los flujos de envio, rastreo y contacto.
4. Consultar [docs/trackflow-web/README.md](docs/trackflow-web/README.md) para la explicacion global de la solucion.

## Estado actual

El proyecto esta preparado como entrega frontend seria y ordenada. La base resuelve presentacion, experiencia de usuario, validaciones y documentacion. La siguiente fase natural seria conectar esta interfaz con servicios reales de autenticacion, tracking y gestion operativa.

## Siguientes ampliaciones posibles

- Integracion con backend real.
- Persistencia de usuarios y solicitudes.
- Tracking conectado a datos reales.
- Analitica de conversion y eventos.
- Automatizacion de pruebas de interfaz.

## Autor y contexto

Proyecto desarrollado dentro del itinerario de AI Engineering de 4Geeks Academy, adaptado al caso de negocio TrackFlow como entrega estructurada de producto web y documentacion.
Is it a CLI tool with its own package?     → internal/
```

---

## Repository structure (tree)

```text
ai-engineering-company-project-monorepo/
├── README.md / README.es.md   # This guide
├── CONTEXT.md                 # ← Replace with your company briefing
├── docker-compose.yml         # ← Local dev orchestration (repo root)
├── uis/                       # Frontends (website, backoffice, dashboards)
├── services/                  # Centralized FastAPI company API
├── data/
│   ├── raw/                   # Source datasets
│   ├── pipelines/             # ETL/ELT jobs
│   ├── process/               # Clean / intermediate outputs
│   └── eval/                  # Evaluation sets and metrics
├── agents/                    # AI agents (+ _template/ starter)
├── skills/                    # Reusable agent skills
├── mcps/                      # MCP servers for tool access
├── workflows/                 # n8n and automation flows
├── packages/                  # Shared libraries (@repo/shared-types, …)
├── shared/                    # Schemas, templates, loose assets
├── docs/                      # Architecture and cross-cutting docs
├── infra/                     # Docker, Terraform, deployment
├── scripts/                   # Helper scripts
└── internal/                  # Internal CLIs and dev tools
```

---

## Links

- [4Geeks Academy — AI Engineering](https://4geeksacademy.com/es/programas-de-carrera/ingenieria-ia)
- [How to start a coding project](https://4geeks.com/lesson/how-to-start-a-project)

---

## Contributors

This template was built as part of the 4Geeks Academy AI Engineering Career Program by [@marcogonzalo](https://www.linkedin.com/in/marcogonzalo) and [@alezanchezr](https://x.com/alesanchezr) and many other contributors. Find out more about our [AI Engineering Course](https://4geeksacademy.com/en/career-programs/ai-engineering), and [other courses](https://4geeksacademy.com/en/program-comparison).

You can find other templates and resources like this at the [4Geeks Academy GitHub page](https://github.com/4geeksacademy).

_This template is maintained by 4Geeks Academy for the AI Engineering track. For exclusive use in the programme._
