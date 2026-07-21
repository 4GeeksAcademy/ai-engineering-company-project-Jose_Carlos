# Explicacion de Project/main.js

- Lineas 1 - 26.- const trackFlowSlides: array con los 3 objetos de datos del carrusel. Cada objeto guarda el kicker, titulo, descripcion, caption, alt e imagen de un slide. Se usan en las lineas 98 - 109 para crear los puntos del carrusel, en las lineas 111 - 127 para pintar el contenido visible mediante renderSlide, y en las lineas 129 - 135 para calcular la navegacion anterior y siguiente mediante initializeCarousel.

- Lineas 28 - 48.- document.addEventListener('DOMContentLoaded', ...): punto de arranque del script. Espera a que el DOM exista antes de activar menus, ayudas, validaciones y logica por pagina. Se apoya en document.body.dataset.page, en las lineas 34 - 38 para la landing y en las lineas 40 - 46 para application.html, de modo que un solo archivo JS sirva a ambas paginas.

- Lineas 50 - 67.- function initializeToggles: controla elementos desplegables genericos, como el panel de login y el menu movil. Se apoya en atributos data-toggle-target y aria-expanded para localizar el panel correcto y reflejar su estado accesible mediante classList.toggle y setAttribute.

- Lineas 69 - 83.- function initializePasswordToggles: cambia inputs de tipo password a text y viceversa. Se usa sobre los botones con data-password-toggle para mostrar u ocultar la contrasena mediante la propiedad input.type, y actualiza el texto del boton en la linea 80.

- Lineas 85 - 140.- function initializeCarousel: inicializa toda la logica del hero. En las lineas 87 - 92 obtiene referencias del DOM; en las lineas 98 - 109 crea los dots clicables; en las lineas 111 - 127 define renderSlide para copiar al HTML los datos de trackFlowSlides; en las lineas 129 - 137 conecta las flechas; y en la linea 139 fuerza el primer pintado del carrusel.

- Lineas 142 - 158.- function initializeFieldHelpers: muestra los textos de ayuda de los campos cuando el usuario hace foco o clic. Se usa con elementos que tengan data-helper-target y hace visible el mensaje asociado mediante classList.remove('hidden') y aria-expanded.

- Lineas 160 - 174.- function initializeValidationListeners: registra los eventos base de validacion para todos los input, select y textarea de un contenedor. Usa blur para marcar el campo como visitado en las lineas 162 - 165, y luego input o change en las lineas 167 - 172 para revalidar mientras el usuario corrige.

- Lineas 176 - 197.- function initializeSimpleForm: resuelve formularios sencillos de la landing, concretamente login y registro. Se usa desde las lineas 36 - 37 y, al enviar, llama a validateForm en la linea 187; si todo es correcto, muestra un mensaje de estado, resetea el formulario y limpia estilos mediante resetFormVisuals.

- Lineas 199 - 232.- function initializeTabs: maneja las tabs principales Particulares y Empresas, y las subtabs Enviar y Rastrear. Se usa desde la linea 41. En las lineas 205 - 217 cambia paneles principales y clases visuales; en las lineas 219 - 231 hace lo mismo con las subtabs para mostrar send-panel o track-panel.

- Lineas 234 - 255.- function initializeCountryPostalPairs: conecta cada select de pais con su input de codigo postal. Se usa desde la linea 42. Cuando cambia el pais, en las lineas 243 - 247 habilita o bloquea el CP, cambia el placeholder y adapta el aspecto; si el pais queda vacio, en las lineas 249 - 251 borra el valor y limpia errores.

- Lineas 257 - 277.- function initializePackageClone: permite anadir paquetes dinamicos al formulario de particulares. Se usa desde la linea 43. En las lineas 267 - 269 calcula el nuevo indice y clona el template reemplazando __INDEX__; despues, en las lineas 271 - 274 reactiva ayudas y validacion para el nuevo bloque anadido.

- Lineas 279 - 302.- function initializePrivateSendForm: controla el envio del formulario de particulares en modo Enviar. Se usa desde la linea 44. Primero llama a validateForm en la linea 290; si faltan datos, muestra un error general en las lineas 291 - 293; si todo es valido, en la linea 297 lanza el alert solicitado, resetea el formulario y en la linea 300 vuelve a deshabilitar los codigos postales disparando el evento change.

- Lineas 304 - 324.- function initializePrivateTrackForm: controla la subpestana Rastrear. Se usa desde la linea 45. Valida el formato del numero de seguimiento y, si pasa, en las lineas 320 - 322 transforma el codigo a mayusculas y muestra un mensaje provisional de seguimiento sin backend.

- Lineas 326 - 356.- function initializeCompanyForm: gestiona el formulario de Empresas. Se usa desde la linea 46. Tras validar, en las lineas 342 - 344 busca telefonos y emails dentro del mensaje mediante expresiones regulares, los guarda para uso futuro en window.trackFlowLeadData en las lineas 346 - 349, y finalmente informa del resultado en la linea 351.

- Lineas 358 - 365.- function validateForm: valida todos los campos activos de un formulario antes de enviarlo. Se usa en las lineas 187, 290, 315 y 337. Filtra los campos deshabilitados y llama a validateField sobre cada uno usando every para que el resultado final sea true solo si todos son validos.

- Lineas 367 - 398.- function validateField: concentra las reglas de validacion. Revisa obligatorio, email, numerico, codigo postal y tracking. Se usa desde initializeValidationListeners en las lineas 164 y 170, y desde validateForm en la linea 363. Si detecta un error, delega la presentacion visual en showFieldError; si no, limpia el estado con clearFieldError.

- Lineas 400 - 410.- function showFieldError: pinta un campo como invalido. Anade aria-invalid, cambia clases Tailwind para borde y foco en rojo, y escribe el mensaje en el nodo de error asociado mediante el id guardado en data-error.

- Lineas 412 - 422.- function clearFieldError: revierte el estado visual de error. Se usa cuando un campo vuelve a ser valido o cuando se reinicia un formulario, restaurando las clases originales y ocultando el mensaje de error.

- Lineas 424 - 429.- function resetFormVisuals: limpia el estado visual de todos los campos de un formulario despues de un reset. Se usa en las lineas 195, 299 y 354 para poner dataset.touched en false y llamar a clearFieldError sobre cada control.

- Lineas 431 - 433.- function isEmail: utilidad pequena para comprobar el formato basico de un email con una expresion regular. Se usa en la linea 377 dentro de validateField para la validacion de login, registro y formulario de empresas.

- Lineas 435 - 462.- function createSlideImage: genera una imagen SVG en memoria y la convierte en data URL. Se usa en las lineas 8, 16 y 24 al construir trackFlowSlides. Su objetivo es que el carrusel tenga imagenes visibles sin depender de archivos externos dentro del proyecto.