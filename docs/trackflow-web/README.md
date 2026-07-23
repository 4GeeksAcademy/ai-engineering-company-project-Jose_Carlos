# TrackFlow Web

Landing page y aplicacion web de captacion para una empresa de transporte con seguimiento en tiempo real, pensada para presentar la marca, convertir visitas en solicitudes y ofrecer un flujo inicial de envio, rastreo y contacto para empresas.

## Resumen del proyecto

Este desarrollo web representa la presencia digital inicial de TrackFlow. La solucion se divide en dos experiencias conectadas:

- Una landing corporativa orientada a marca, confianza y conversion.
- Una aplicacion operativa para particulares y empresas con formularios guiados.

El objetivo principal ha sido construir una experiencia clara, responsive y facil de mantener usando HTML, Tailwind CSS y JavaScript vanilla, sin depender de frameworks complejos ni backend en esta primera fase.

## Objetivos del desarrollo

- Comunicar con claridad la propuesta de valor de TrackFlow.
- Reforzar el posicionamiento SEO en torno a transporte, rastreo y atencion personalizada.
- Facilitar la captacion de usuarios mediante registro, login y llamadas a la accion.
- Ofrecer un flujo inicial de envio y rastreo para validar la experiencia del usuario.
- Preparar una base sencilla sobre la que despues se pueda integrar backend, autenticacion real y persistencia.

## Que incluye la web

### 1. Landing corporativa

La pagina principal concentra los elementos de presentacion y conversion mas importantes:

- Hero con carrusel de mensajes comerciales.
- Seccion de beneficios clave.
- Bloque "Sobre nosotros" con pasado, presente y futuro de la marca.
- Formulario de registro en la misma landing.
- Panel de inicio de sesion desplegable.
- CTA final hacia la aplicacion de envio.
- Footer con enlaces, contacto y presencia de marca.

### 2. Aplicacion de envio

La segunda pagina amplia la experiencia con un flujo mas funcional:

- Vista para particulares con dos modos: enviar y rastrear.
- Vista para empresas con formulario de contacto B2B.
- Seleccion de paises europeos para origen y destino.
- Activacion progresiva de codigos postales.
- Alta dinamica de multiples paquetes.
- Validacion del formato de tracking.
- Captura inicial de leads empresariales.

## Funcionalidades destacadas

### UX y navegacion

- Navegacion responsive con menu movil.
- Panel de login accesible desde desktop y mobile.
- Carrusel manual con indicadores y flechas.
- Interfaz separada por tipo de cliente y accion.

### Validaciones e interaccion

- Validacion de campos requeridos en frontend.
- Validacion de email y campos numericos.
- Restriccion de caracteres en tracking y codigos postales.
- Toggle para mostrar u ocultar contrasenas.
- Feedback visual inmediato ante errores o envios validos.

### SEO y estructura semantica

- Metadatos SEO completos en la landing.
- Open Graph y Twitter Cards para compartir en redes.
- Datos estructurados JSON-LD para Organization, WebSite y Service.
- Jerarquia clara de encabezados y secciones orientadas a indexacion.

### Accesibilidad y mantenimiento

- Uso de atributos ARIA en menus, tabs, formularios y carrusel.
- Componentes construidos con HTML semantico.
- Logica de interfaz separada por responsabilidades en JavaScript vanilla.
- Estructura suficientemente simple para evolucionar sin rehacer la base.

## Stack utilizado

- HTML5
- Tailwind CSS via CDN
- JavaScript vanilla
- JSON-LD para SEO semantico
- Open Graph y Twitter metadata

## Estructura principal

- [uis/website/trackflow-web/index.html](../../uis/website/trackflow-web/index.html): landing corporativa de TrackFlow.
- [uis/website/trackflow-web/application.html](../../uis/website/trackflow-web/application.html): aplicacion de envio, rastreo y contacto.
- [docs/trackflow-web/explicacion-index-html-trackflow.md](./explicacion-index-html-trackflow.md): desglose tecnico de la implementacion.

## Decisiones tecnicas

### Por que una solucion sin framework

Se eligio una base ligera para priorizar velocidad de desarrollo, claridad de la implementacion y facilidad de revision academica o tecnica. Para una primera version funcional, HTML + Tailwind + JavaScript permiten:

- Iterar rapido.
- Mantener bajo el coste de complejidad.
- Entender con facilidad toda la logica desde el navegador.
- Preparar la migracion futura a componentes o a un frontend mas robusto si el proyecto crece.

### Por que separar landing y aplicacion

La separacion entre presentacion comercial y flujo operativo ayuda a mantener objetivos distintos:

- La landing vende la propuesta de valor.
- La aplicacion recoge interacciones y datos del usuario.

Esto mejora la claridad del recorrido y permite evolucionar cada superficie por separado.

## Valor que aporta este desarrollo

Esta web no solo presenta la marca. Tambien valida un flujo de negocio realista para una empresa logistica:

- Atrae trafico con una propuesta clara.
- Convierte visitas en registros o solicitudes.
- Simula procesos clave del negocio digital: enviar, rastrear y contactar.
- Sienta las bases para integraciones futuras con APIs, CRM, autenticacion y analitica.

## Como ejecutar el proyecto

Al tratarse de una solucion estatica, basta con abrir la landing en el navegador:

1. Abrir [uis/website/trackflow-web/index.html](../../uis/website/trackflow-web/index.html).
2. Navegar a la aplicacion desde el CTA o abrir [uis/website/trackflow-web/application.html](../../uis/website/trackflow-web/application.html).

Opcionalmente se puede usar una extension tipo Live Server para una experiencia de desarrollo mas comoda.

## Mejoras recomendadas

- Conectar formularios a un backend real.
- Sustituir alerts por componentes de feedback mas solidos.
- Persistir usuarios, solicitudes y codigos de seguimiento.
- Incorporar autenticacion real.
- Automatizar pruebas de interfaz y validaciones.
- Medir conversion, eventos y comportamiento con analitica.
- Mejorar el rastreo con estados reales del envio.

## Estado actual

La web ya cubre una primera version funcional de la experiencia digital de TrackFlow. El desarrollo actual resuelve presentacion, navegacion, validacion e interaccion principal en frontend, y deja preparada una base clara para la siguiente fase del proyecto.

## Ubicacion dentro del monorepo

La estructura ahora queda separada segun responsabilidad:

- [uis/website/trackflow-web](../../uis/website/trackflow-web): codigo fuente de la web publica.
- [docs/trackflow-web](./): documentacion funcional y tecnica de esta entrega.
