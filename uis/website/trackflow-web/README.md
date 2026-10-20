# TrackFlow Web App

Aplicacion web estatica de TrackFlow compuesta por una landing corporativa y un flujo operativo basico para envio, rastreo y contacto.

## Contenido

- [index.html](./index.html): pagina principal orientada a marca, SEO y conversion.
- [application.html](./application.html): flujo operativo para particulares y empresas.

## Objetivo

Esta app representa la presencia web inicial de TrackFlow y sirve como base para:

- presentar la propuesta de valor de la compania,
- captar usuarios y leads,
- validar una experiencia de envio y rastreo en frontend,
- preparar futuras integraciones con backend y analitica.

## Stack

- HTML5
- Tailwind CSS v3 compilado en build ([css/styles.css](./css/styles.css), generado: no se edita a mano)
- JavaScript vanilla (validacion de formularios compartida en [js/form-validation.js](./js/form-validation.js))
- Imagenes del carrusel en WebP propio, en tres anchos ([img/](./img))

## Ejecucion local

Desde `uis/website`:

```sh
npm ci
npm run build   # compila Tailwind -> trackflow-web/css/styles.css (repetir si cambian las clases del HTML/JS)
npm run start   # servidor estatico de produccion en http://localhost:3000
```

Mientras se editan clases, `npm run watch` recompila el CSS en cada cambio.

## Documentacion relacionada

- [docs/trackflow-web/README.md](../../../docs/trackflow-web/README.md)
- [docs/trackflow-web/explicacion-index-html-trackflow.md](../../../docs/trackflow-web/explicacion-index-html-trackflow.md)