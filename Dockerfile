# Build the static bundle, then serve it from nginx. No app server is needed:
# the client talks to Telegram's DCs directly from the browser.
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_TG_API_ID
ARG VITE_TG_API_HASH
ARG VITE_APP_NAME
ARG VITE_APP_NAME_EN
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
