FROM node:22-alpine

WORKDIR /app/client
COPY client/package*.json ./
RUN npm install
COPY client/ ./

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
