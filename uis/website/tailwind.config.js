// Tailwind compilado en build (antes se usaba el CDN `cdn.tailwindcss.com`, que genera el CSS en el
// navegador). Misma versión mayor que el CDN (v3), así que las clases se ven igual.
/** @type {import('tailwindcss').Config} */
module.exports = {
  // Las clases que se ponen desde JavaScript (carrusel, errores, pestañas) también están en estos ficheros.
  content: ["./trackflow-web/**/*.{html,js}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
