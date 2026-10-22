# Imagem do nginx: proxy HTTPS na borda + arquivos do frontend.
# Contexto de build: raiz do repositório (usa nginx/ e frontend/).
FROM nginx:1.27-alpine

# openssl gera o certificado autoassinado na inicialização.
RUN apk add --no-cache openssl

COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/snippets /etc/nginx/snippets
COPY nginx/10-gerar-certificado.sh /docker-entrypoint.d/10-gerar-certificado.sh
# Garante quebras de linha LF (o repositório pode ter sido clonado no Windows).
RUN sed -i 's/\r$//' /docker-entrypoint.d/10-gerar-certificado.sh \
 && chmod +x /docker-entrypoint.d/10-gerar-certificado.sh

RUN rm -rf /usr/share/nginx/html/*
COPY frontend /usr/share/nginx/html

EXPOSE 80 443
