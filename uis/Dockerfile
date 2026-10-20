# Contenedor de interfaces (desarrollo): web pública y backoffice (Next.js, con el Talent Pipeline).
# El código fuente llega por bind mount desde docker-compose.yml; la imagen solo trae Node,
# las dependencias de cada app y el script de arranque.
FROM node:22-alpine

# La web pública es HTML estático: sus dependencias son browser-sync (servidor con recarga en
# caliente) y Tailwind (compila trackflow-web/css/styles.css). Se instalan fuera de /app para que
# el bind mount del código no las tape.
WORKDIR /opt/uis/website
COPY website/package.json website/package-lock.json ./
RUN npm ci --no-audit --no-fund

# El backoffice (Next.js) necesita node_modules dentro de su carpeta: docker-compose.yml lo
# protege del bind mount con un volumen anónimo (así no se mezclan los binarios del host).
WORKDIR /app/backoffice
COPY backoffice/package.json backoffice/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Se quitan los CRLF por si el repo se clonó en Windows con core.autocrlf=true.
COPY start.sh /usr/local/bin/start.sh
RUN sed -i 's/\r$//' /usr/local/bin/start.sh && chmod +x /usr/local/bin/start.sh

WORKDIR /app
EXPOSE 3000 3001

CMD ["start.sh"]
