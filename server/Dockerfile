FROM node:22-alpine

WORKDIR /app/server
COPY server/package*.json ./
RUN npm install --omit=dev
COPY server/ ./

EXPOSE 5000
CMD ["node", "server.js"]
