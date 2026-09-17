# Propuesta de arquitectura backend para TrackFlow

## 1. Propósito y contexto

TrackFlow es una empresa de logística de última milla y gestión de almacén con operación prevista en México y España. La entrega actual contiene una web estática que presenta la marca y valida, en el navegador, tres recorridos principales:

- registro e inicio de sesión;
- creación de envíos y gestión de varios paquetes;
- consulta de tracking y captación de solicitudes B2B.

El siguiente paso no debería consistir en convertir la página en un monolito que sirva HTML y acumule lógica de negocio. La recomendación es crear una API backend independiente que exponga contratos HTTP estables. El frontend seguirá siendo una aplicación separada y podrá evolucionar sin obligar a rediseñar el núcleo operativo.

Esta propuesta describe una dirección inicial. No pretende fijar todavía todos los campos de cada endpoint, el proveedor de infraestructura ni un modelo de optimización logística. Esos detalles deben confirmarse con operaciones, producto y seguridad.

## 2. Patrón arquitectónico elegido

### Modular monolith orientado a dominios, con capas ligeras

Propongo comenzar con un **monolito modular** construido con FastAPI. El proceso de despliegue puede ser uno, pero el código se organiza por dominios de negocio y cada dominio mantiene separadas sus responsabilidades:

1. **API/adaptadores**: routers FastAPI, validación de entrada y transformación de respuestas.
2. **Aplicación**: casos de uso que coordinan una operación concreta, por ejemplo registrar un usuario o consultar un envío.
3. **Dominio**: reglas y conceptos propios de envíos, tracking, identidad y clientes empresariales.
4. **Infraestructura**: base de datos, repositorios, proveedores de correo, identidad externa y servicios de terceros.

La capa de aplicación no debería depender de FastAPI directamente, y el dominio no debería conocer HTTP ni SQL. Esta separación permite probar reglas sin levantar un servidor y evita que los handlers se conviertan en una mezcla de validación, consultas y decisiones de negocio.

### Por qué encaja con TrackFlow

- **Complejidad inicial controlada**: el producto todavía está validando sus flujos. Un monolito modular evita el coste operativo de varios microservicios, redes internas, despliegues independientes y observabilidad distribuida.
- **Dominios con evolución distinta**: el tracking puede crecer hacia integraciones con transportistas y eventos en tiempo real, mientras que identidad y solicitudes B2B tienen ciclos diferentes. Los límites de módulo permiten evolucionar sin separar servicios antes de que exista una necesidad real.
- **Consistencia transaccional**: crear un envío, sus paquetes y su primer estado debe poder tratarse de forma atómica al principio.
- **Escalado posterior**: si el tracking o las integraciones externas requieren otra cadencia de escalado, el módulo puede extraerse después con un contrato ya definido.
- **Adecuación a FastAPI**: `APIRouter` permite agrupar rutas por responsabilidad e incluirlas desde un punto de entrada, una práctica documentada para aplicaciones grandes.

No recomiendo empezar con microservicios ni con una arquitectura hexagonal excesivamente abstracta. Las interfaces deben existir donde protejan una frontera real (por ejemplo, repositorios o proveedores externos), no como capas vacías que repitan cada función.

## 3. Estructura de carpetas propuesta

La API podría vivir en `services/trackflow-api/`, separada de `uis/website/trackflow-web/`:

```text
services/trackflow-api/
├── app/
│   ├── main.py                  # Crea FastAPI, middleware y routers
│   ├── core/
│   │   ├── config.py            # Configuración por entorno
│   │   ├── errors.py            # Excepciones y respuestas comunes
│   │   ├── logging.py           # Logging estructurado
│   │   └── security.py          # Hashing, tokens y dependencias de auth
│   ├── api/
│   │   ├── deps.py              # Sesión DB, usuario actual y dependencias
│   │   └── v1/
│   │       ├── router.py        # Agrupa los routers de v1
│   │       └── routers/
│   │           ├── auth.py
│   │           ├── shipments.py
│   │           ├── tracking.py
│   │           └── business_requests.py
│   ├── domains/
│   │   ├── identity/
│   │   │   ├── domain.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── repository.py
│   │   ├── shipments/
│   │   │   ├── domain.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── repository.py
│   │   ├── tracking/
│   │   │   ├── domain.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── repository.py
│   │   └── business_requests/
│   │       ├── domain.py
│   │       ├── schemas.py
│   │       ├── service.py
│   │       └── repository.py
│   └── infrastructure/
│       ├── db/
│       │   ├── models.py
│       │   ├── session.py
│       │   └── migrations/
│       ├── integrations/
│       │   ├── carriers/
│       │   └── notifications/
│       └── repositories/
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
└── README.md
```

La estructura es una guía de dependencias, no una obligación de crear todos los archivos el primer día. Un módulo puede empezar con menos piezas y crecer cuando aparezca una regla o integración que lo justifique.

## 4. Organización de rutas y dominios

### Convenciones de API

Las rutas públicas deberían versionarse desde el inicio, por ejemplo `/api/v1/auth/...` y `/api/v1/shipments/...`. La versión protege al frontend y a futuras integraciones de cambios incompatibles. Las rutas deben nombrar recursos y dejar las acciones excepcionales para operaciones que realmente no encajen en CRUD.

El router debe hacer lo mínimo:

- recibir un esquema Pydantic;
- obtener dependencias, usuario y transacción;
- llamar a un caso de uso;
- devolver el esquema de respuesta y el código HTTP adecuado.

Los esquemas de entrada y salida no deben reutilizarse automáticamente como modelos de persistencia. Un cambio en la tabla no tiene por qué cambiar el contrato público.

### Identidad y autenticación

Responsabilidades iniciales:

- registro y autenticación;
- hash seguro de contraseñas;
- recuperación o verificación de cuenta cuando producto lo defina;
- roles mínimos para particulares, empresas y personal interno;
- identificación del usuario en las dependencias protegidas.

El frontend no debe decidir permisos. El backend debe comprobar la identidad y autorización en cada operación protegida. La estrategia concreta (tokens de acceso con refresh, proveedor de identidad gestionado o sesiones) debe seleccionarse antes del primer endpoint real y documentarse junto con expiración, revocación y almacenamiento.

### Envíos

Este es el dominio transaccional principal. Debe modelar, como mínimo, el envío, remitente, destinatario, origen, destino y sus paquetes. Crear un envío debe validar reglas como países soportados, peso y dimensiones, y asignar un identificador que no revele datos sensibles.

Los estados no deberían ser texto libre. Conviene definir una máquina de estados explícita y registrar el historial de transiciones, quién las produjo y cuándo. Así se evita que un endpoint permita pasar directamente de “creado” a “entregado” sin una regla autorizada.

### Tracking

Tracking es una consulta de eventos y estado actual, no simplemente un campo `status` dentro del usuario. La API pública puede exponer una consulta por código, limitada a la información que corresponde mostrar al cliente. Las actualizaciones internas o provenientes de transportistas deben entrar por una frontera distinta y autenticada.

El diseño debe dejar espacio para eventos duplicados, desordenados o retrasados. Para notificaciones futuras, el historial de eventos será más fiable que sobrescribir únicamente el estado actual.

### Solicitudes B2B

Este módulo recibe consultas de empresas interesadas en contratar el servicio. Debe separar la recepción pública del lead de su gestión interna, aplicar validación y protección contra abuso, y conservar el estado de atención. No debe compartir automáticamente el modelo de “usuario” si una empresa aún no tiene una cuenta.

## 5. Frontend y backend como sistemas separados

El frontend actual se sirve como aplicación web y el backend debería exponerse como API. El navegador llamará a la API mediante `fetch` (o un cliente equivalente), en vez de acceder a la base de datos o duplicar reglas de negocio.

Decisiones iniciales recomendadas:

- definir contratos JSON, códigos HTTP y formato de errores antes de conectar cada formulario;
- mantener URLs y secretos en configuración por entorno, nunca en el repositorio;
- restringir CORS a los orígenes conocidos de desarrollo, staging y producción; no usar `allow_origins=["*"]` junto con credenciales;
- separar datos públicos de datos autenticados y aplicar autorización en servidor;
- servir documentación OpenAPI de FastAPI en entornos de desarrollo y proteger o desactivar su exposición pública según el entorno;
- configurar timeouts, reintentos y trazabilidad para llamadas a transportistas o notificaciones.

La separación implica que frontend y backend pueden tener despliegues, dominios y ciclos de release distintos. También introduce trabajo explícito: CORS, autenticación entre orígenes, gestión de versiones y coordinación de contratos. Es un coste aceptable porque evita acoplar el negocio al ciclo de una sola interfaz.

## 6. Decisiones técnicas iniciales

1. **FastAPI + Pydantic** para endpoints tipados, validación y OpenAPI.
2. **Python con tipado estático y linting** desde el inicio para mantener contratos claros.
3. **Base de datos relacional** para usuarios, envíos, paquetes, estados y solicitudes; las relaciones y transacciones son centrales en este dominio.
4. **Migraciones versionadas** y cambios de esquema revisables; no crear tablas manualmente en producción.
5. **Repositorio y servicios por dominio**, con dependencias inyectadas para que las pruebas puedan sustituir la base de datos y proveedores.
6. **Errores uniformes**, sin ocultar excepciones ni convertir fallos de dependencias en respuestas exitosas.
7. **Logging estructurado y correlation ID** para seguir una solicitud entre API e integraciones sin registrar contraseñas, tokens ni datos innecesarios.
8. **Pruebas unitarias de reglas y pruebas de integración de rutas críticas**: autenticación, creación de envío, consulta de tracking y registro de lead.
9. **Tareas asíncronas o una cola** solo cuando haya trabajo desacoplable, como notificaciones o sincronización con transportistas; no introducir un broker antes de identificar esa necesidad.

## 7. Riesgos y puntos de atención

| Riesgo o confusión | Consecuencia | Mitigación |
| --- | --- | --- |
| Tratar la validación del frontend como seguridad | Datos inválidos o acceso no autorizado | Repetir validación y autorización en backend; el navegador es un cliente no confiable. |
| Mezclar router, SQL y reglas de negocio | Endpoints difíciles de probar y modificar | Mantener routers delgados y casos de uso por operación. |
| Usar “envío” y “tracking” como el mismo concepto | Estados inconsistentes y consultas ambiguas | Separar entidad de envío, estado actual e historial de eventos. |
| Permitir estados arbitrarios | Transiciones imposibles de auditar | Máquina de estados y reglas explícitas de transición. |
| Exponer demasiados datos en una consulta pública de tracking | Riesgo de privacidad | DTO público mínimo, códigos no predecibles y límites de consulta. |
| Confundir lead B2B con usuario autenticado | Modelo rígido y pérdida de solicitudes | Mantener el ciclo de vida de la solicitud independiente hasta convertirla en cuenta. |
| Activar CORS amplio para “que funcione” | Lecturas o acciones desde orígenes no confiables | Lista explícita por entorno y pruebas de configuración. |
| Introducir microservicios demasiado pronto | Mayor coste de despliegue y depuración | Monolito modular, contratos internos claros y extracción solo con evidencia. |
| Ignorar México y España como contextos distintos | Errores de zona horaria, moneda, dirección o regulación | Normalizar país, región y zona horaria; validar requisitos legales antes de fijar el modelo. |
| Integrar transportistas directamente desde los routers | Acoplamiento a proveedores y fallos difíciles de recuperar | Adaptadores en infraestructura, timeouts, idempotencia y registro de eventos externos. |

## 8. Secuencia recomendada

1. Acordar vocabulario, estados de envío, roles y límites de privacidad con negocio.
2. Definir el contrato `v1` para autenticación, envío, tracking y lead, incluyendo errores.
3. Crear el esqueleto FastAPI, configuración, migraciones, observabilidad básica y pruebas.
4. Implementar identidad y creación de envíos con transacciones.
5. Implementar consulta de tracking usando historial, aunque la primera fuente de eventos sea interna.
6. Conectar los formularios del frontend uno por uno, validando el contrato en integración.
7. Añadir proveedores externos, notificaciones y procesamiento asíncrono cuando los flujos reales lo requieran.

## 9. Referencias

- [FastAPI: Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/): uso de `APIRouter` e inclusión modular de rutas.
- [FastAPI: CORS](https://fastapi.tiangolo.com/tutorial/cors/): implicaciones de servir frontend y backend desde orígenes distintos.
- [FastAPI: Static Files](https://fastapi.tiangolo.com/tutorial/static-files/): alternativa para servir archivos desde FastAPI, no recomendada como límite principal para esta separación.
- [FastAPI: OpenAPI docs](https://fastapi.tiangolo.com/features/): documentación automática y contratos explorables de la API.
