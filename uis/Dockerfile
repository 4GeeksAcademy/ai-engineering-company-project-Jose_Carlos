# Contenedor de interfaces (desarrollo): website, backoffice y talent-pipeline-tracker.
# El código fuente llega por bind mount desde docker-compose.yml; la imagen solo trae Node,
# las dependencias de cada app y el script de arranque.
FROM node:22-alpine

# website y backoffice son HTML/JS estático: su única dependencia es browser-sync (servidor con
# recarga en caliente). Se instala fuera de /app para que el bind mount del código no la tape.
WORKDIR /opt/uis/website
COPY website/package.json website/package-lock.json ./
RUN npm ci --no-audit --no-fund

WORKDIR /opt/uis/backoffice
COPY backoffice/package.json backoffice/package-lock.json ./
RUN npm ci --no-audit --no-fund

# La app Next.js necesita node_modules dentro de su carpeta: docker-compose.yml lo protege del
# bind mount con un volumen anónimo (así no se mezclan los binarios de Windows/macOS del host).
WORKDIR /app/talent-pipeline-tracker
COPY talent-pipeline-tracker/package.json talent-pipeline-tracker/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Se quitan los CRLF por si el repo se clonó en Windows con core.autocrlf=true.
COPY start.sh /usr/local/bin/start.sh
RUN sed -i 's/\r$//' /usr/local/bin/start.sh && chmod +x /usr/local/bin/start.sh

WORKDIR /app
EXPOSE 3000 3001 3002

CMD ["start.sh"]
