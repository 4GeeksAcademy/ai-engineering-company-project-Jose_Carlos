# Explicacion de index.html (TrackFlow)

- Linea 1 - 3: Apertura del documento HTML y configuracion del idioma principal en espanol. Esta estructura se usa para iniciar la pagina y ayudar a navegadores/buscadores a interpretar el idioma del contenido. Aqui lo usaremos en las lineas (151-459), donde se renderiza toda la interfaz y scripts.

- Linea 4 - 20: Metadatos SEO principales (title, description, robots, canonical, Open Graph y Twitter Card). Esta estructura se usa para mejorar indexacion, CTR en resultados y previsualizacion en redes sociales. Aqui lo usaremos junto a las lineas (44-94), donde el JSON-LD refuerza semanticamente el mismo mensaje de marca y servicio.

- Linea 21 - 43: Carga de Tailwind y extension del tema con paleta brand en tonos cyan. Esta estructura se usa para mantener consistencia visual y estilos utilitarios en toda la pagina. Aqui lo usaremos en las lineas (97-294) para maquetar componentes y en las lineas (431-433) para estados visuales de los dots del carrusel.

- Linea 44 - 94: Datos estructurados JSON-LD con @graph (Organization, WebSite y Service). Esta estructura se usa para SEO semantico, reforzando que TrackFlow es una empresa de transporte con seguimiento en tiempo real y atencion personalizada. Aqui lo usaremos en las lineas (6-20) para coherencia de metadatos y en las lineas (162-199) para reflejar en contenido visible la misma propuesta de valor.

- Linea 97 - 120: Header fijo con navegacion principal, CTA y botones de login/menu movil. Esta estructura se usa para acceso rapido a secciones clave y conversion. Aqui lo usaremos en las lineas (297-323), donde el JS controla la apertura/cierre del menu y panel de sesion.

- Linea 121 - 127: Menu movil desplegable con enlaces internos y enlace a application.html. Esta estructura se usa para navegacion responsive en pantallas pequenas. Aqui lo usaremos en las lineas (325-330), cerrando el menu al seleccionar una opcion.

- Linea 129 - 148: Panel de login oculto por defecto con validacion de email y contrasena. Esta estructura se usa para autenticar desde la landing sin cambiar de pagina. Aqui lo usaremos en las lineas (303-307) para mostrar/ocultar el panel, en las lineas (369-380) para submit, y en las lineas (382-389) para mostrar/ocultar contrasena.

- Linea 151 - 179: Bloque hero del carrusel con contenido principal, flechas y dots. Esta estructura se usa para posicionar la propuesta principal y rotar mensajes clave. Aqui lo usaremos en las lineas (415-456), donde se inyectan dinamicamente tag, titulo, texto e imagen de cada slide.

- Linea 159 - 170: Contenido interno del hero (tag, h1, texto, CTA e imagen principal). Esta estructura se usa para atacar intencion comercial de busqueda con keywords de transporte, seguimiento en tiempo real y atencion personalizada. Aqui lo usaremos en las lineas (393-411), que son las fuentes de datos del carrusel y pueden sobrescribir este contenido inicial al ejecutar setSlide(0).

- Linea 181 - 201: Seccion de beneficios con foco SEO en "seguimiento en tiempo real" y "atencion personalizada". Esta estructura se usa para reforzar relevancia tematica en H2/H3 y copy de soporte. Aqui lo usaremos en las lineas (6-20) y (44-94), manteniendo consistencia entre SEO tecnico y contenido visible.

- Linea 203 - 219: Seccion Sobre nosotros (pasado, presente, futuro). Esta estructura se usa para confianza, contexto de marca y profundidad de contenido. Aqui lo usaremos en las lineas (113-114) y (124), que enlazan esta seccion desde menu desktop/movil.

- Linea 221 - 243: Formulario de registro para captacion. Esta estructura se usa para conversion en la misma landing. Aqui lo usaremos en las lineas (365-380) para validar campos requeridos y procesar el envio en frontend.

- Linea 245 - 259: CTA de contacto con texto reforzado en atencion personalizada. Esta estructura se usa para llevar trafico cualificado al formulario de envio/rastreo en application.html. Aqui lo usaremos en las lineas (248-250), donde se concentra la llamada principal a la accion.

- Linea 262 - 294: Footer con descripcion SEO de marca, enlaces internos y contacto. Esta estructura se usa para enlazado interno, confianza y cierre de navegacion. Aqui lo usaremos en las lineas (269-273) con anclas semanticas y en las lineas (279-281) con datos de contacto.

- Linea 296 - 301: Referencias iniciales de elementos DOM para menu y login. Esta estructura se usa para centralizar accesos a nodos interactivos. Aqui lo usaremos en las lineas (303-330), donde se registran handlers de interaccion.

- Linea 303 - 330: Control de estado para menu movil y panel de login (ARIA + clases). Esta estructura se usa para accesibilidad y comportamiento responsive. Aqui lo usaremos sobre las lineas (97-127) y (129-148), que contienen los elementos objetivo.

- Linea 332 - 349: Utilidades markInvalid y clearInvalid. Esta estructura se usa para mostrar/limpiar errores de validacion en formularios. Aqui lo usaremos en las lineas (351-363), donde se ejecutan reglas de validacion.

- Linea 351 - 363: Funcion validateRequired con reglas de obligatorio y email valido. Esta estructura se usa para validar entradas requeridas de forma reutilizable. Aqui lo usaremos en las lineas (365-380), durante blur y submit.

- Linea 365 - 380: Listeners de validacion y submit para loginForm y registerForm. Esta estructura se usa para bloquear envios invalidos y dar feedback de exito en frontend. Aqui lo usaremos sobre los formularios definidos en las lineas (130-147) y (224-241).

- Linea 382 - 389: Toggle de visibilidad de contrasena con data-toggle-password. Esta estructura se usa para usabilidad en campos password. Aqui lo usaremos en las lineas (140) y (234), donde estan los botones que disparan esta accion.

- Linea 391 - 413: Array slides con los 3 mensajes del carrusel y foco comercial/SEO (transporte, seguimiento en tiempo real, atencion personalizada). Esta estructura se usa como fuente dinamica de contenido del hero. Aqui lo usaremos en las lineas (426-451), durante renderizado de dots y actualizacion del slide activo.

- Linea 415 - 422: Referencias DOM del carrusel (tag, title, text, image, dots y flechas). Esta estructura se usa para desacoplar datos de presentacion y facilitar actualizaciones dinamicas. Aqui lo usaremos en las lineas (426-456), con render y navegacion.

- Linea 424 - 439: Estado currentSlide y funcion renderDots. Esta estructura se usa para indicar visualmente el slide activo y permitir navegacion directa por punto. Aqui lo usaremos en las lineas (441-451), llamando renderDots tras cada cambio de slide.

- Linea 441 - 451: Funcion setSlide que inyecta contenido del slide activo y actualiza atributos de accesibilidad. Esta estructura se usa como motor principal del carrusel. Aqui lo usaremos en las lineas (436), (453), (454) y (456), desde dots, flechas e inicializacion.

- Linea 453 - 456: Navegacion de flechas e inicializacion con setSlide(0). Esta estructura se usa para arrancar el carrusel con contenido consistente y habilitar avance/retroceso manual. Aqui lo usaremos junto con las lineas (174-177), donde viven los controles visibles.

- Linea 457 - 459: Cierre del script y del documento. Esta estructura se usa para finalizar correctamente la carga y garantizar que el DOM ya existe antes de ejecutar el JS inline. Aqui lo usaremos indirectamente en todas las lineas (296-456).

# Explicacion de application.html (TrackFlow)

- Linea 1 - 9: Estructura base del documento (doctype, idioma, metadatos y carga de Tailwind CDN). Esta estructura se usa para iniciar la aplicacion de envio con estilos consistentes. Aqui lo usaremos en las lineas (10-423), donde se renderizan formularios y logica JS.

- Linea 10 - 16: Header con navegacion minima de la aplicacion y enlace de retorno al inicio. Esta estructura se usa para mantener continuidad entre landing y app. Aqui lo usaremos en las lineas (13-14), con rutas a index.html para branding y navegacion.

- Linea 18 - 27: Contenedor principal de la aplicacion y tarjeta base de contenido. Esta estructura se usa para centrar y limitar ancho de lectura del formulario. Aqui lo usaremos en las lineas (28-159), que incluyen tabs y formularios operativos.

- Linea 22 - 25: Tabs principales Particulares/Empresas. Esta estructura se usa para alternar entre dos flujos de usuario. Aqui lo usaremos en las lineas (198-217), donde activateMainTab cambia panel visible, estados aria y clases visuales.

- Linea 28 - 33: Panel de Particulares con subtabs Enviar/Rastrear. Esta estructura se usa para separar acciones dentro del mismo perfil. Aqui lo usaremos en las lineas (219-238), donde activateSubTab alterna bloques y estados aria.

- Linea 34 - 71: Formulario de envio (origen y destino) con pais y codigo postal dependiente. Esta estructura se usa para capturar ruta del envio y forzar validacion progresiva. Aqui lo usaremos en las lineas (163-197), donde se cargan paises europeos y se habilitan/deshabilitan codigos postales segun seleccion.

- Linea 72 - 120: Primer bloque de datos del paquete y acciones de anadir paquete/enviar. Esta estructura se usa para recoger dimensiones y peso, y permitir formularios multipaquete. Aqui lo usaremos en las lineas (316-357), donde se clona dinamicamente el bloque package-item.

- Linea 123 - 130: Bloque Rastrear con trackingCode y boton de validacion. Esta estructura se usa para consultas rapidas de estado de envio. Aqui lo usaremos en las lineas (378-391), que validan formato y muestran estado.

- Linea 134 - 157: Panel de Empresas con formulario de contacto (nombre, email y mensaje). Esta estructura se usa para captar leads B2B y solicitudes complejas. Aqui lo usaremos en las lineas (393-417), donde se valida, procesa y confirma el envio.

- Linea 162 - 168: Array europeanCountries. Esta estructura se usa como fuente de datos para poblar selects de pais sin backend. Aqui lo usaremos en las lineas (175-184), creando opciones para origen y destino.

- Linea 170 - 197: Referencias de pais/codigo postal y funcion enablePostal. Esta estructura se usa para logica dependiente entre campos y mejorar UX. Aqui lo usaremos en las lineas (195-196), vinculando eventos change en ambos selects.

- Linea 198 - 217: Referencias de tabs principales y funcion activateMainTab. Esta estructura se usa para controlar el estado de Particulares vs Empresas. Aqui lo usaremos en las lineas (216-217) y en la linea (419) para inicializacion.

- Linea 219 - 238: Referencias de subtabs y funcion activateSubTab. Esta estructura se usa para alternar entre Enviar y Rastrear dentro de Particulares. Aqui lo usaremos en las lineas (237-238), en la linea (364) al enviar y en la linea (420) al iniciar.

- Linea 240 - 292: Sistema de validacion reutilizable (markInvalid, clearInvalid, helpers regex y validateInput). Esta estructura se usa para normalizar reglas de obligatorio, numerico, email y tracking. Aqui lo usaremos en las lineas (294-299), (362-367), (382-384) y (399-403).

- Linea 294 - 314: Listeners globales de blur, focusin e input. Esta estructura se usa para validacion en tiempo real, apertura de ayudas contextuales y saneado de entrada (solo numeros / tracking alfanumerico). Aqui lo usaremos en las lineas (257-266) y (272-292), que contienen la logica auxiliar aplicada por esos eventos.

- Linea 316 - 357: Logica para clonado de paquetes (addPackage). Esta estructura se usa para multiplicar bloques de paquete sin romper ids, labels, hints ni mensajes de error. Aqui lo usaremos en las lineas (320-323) para titulo dinamico y en las lineas (329-354) para renombrado/reset de campos clonados.

- Linea 359 - 377: Submit de sendForm para Enviar. Esta estructura se usa para validar solo los campos activos de bloqueEnviar y mostrar confirmacion o errores de forma clara. Aqui lo usaremos en las lineas (365-367), donde se filtran campos required habilitados antes de evaluar validez.

- Linea 378 - 391: Validacion de rastreo en trackButton. Esta estructura se usa para evaluar trackingCode contra el patron definido y dar feedback inmediato. Aqui lo usaremos en las lineas (286-289), donde se valida el formato 0000XXXX.

- Linea 393 - 417: Submit de businessForm y extraccion de telefonos/emails del mensaje. Esta estructura se usa para lead enrichment basico sin backend, detectando datos de contacto adicionales en texto libre. Aqui lo usaremos en las lineas (410-412), donde se aplican expresiones regulares para capturar esos datos.

- Linea 419 - 423: Inicializacion final de estado de tabs y cierre del documento. Esta estructura se usa para arrancar la UI en Particulares > Enviar y cerrar el ciclo de carga correctamente. Aqui lo usaremos en las lineas (203-238), que contienen la logica de activacion referenciada por esas llamadas iniciales.
