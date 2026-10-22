#!/bin/sh
# Executado pela imagem oficial do nginx antes de iniciar o servidor (pasta
# /docker-entrypoint.d/). Gera um certificado TLS autoassinado para o nome ou IP
# em DOMINIO_CERTIFICADO, a menos que já exista um certificado em /etc/nginx/certs
# (por exemplo, um emitido por uma autoridade certificadora e montado como volume).
set -eu

PASTA=/etc/nginx/certs
NOME="${DOMINIO_CERTIFICADO:-localhost}"

if [ -s "$PASTA/fintech.crt" ] && [ -s "$PASTA/fintech.key" ]; then
    echo "Certificado TLS encontrado em $PASTA; mantendo."
    exit 0
fi

mkdir -p "$PASTA"

# O navegador compara o endereço acessado com o Subject Alternative Name:
# IP para endereços IPv4 (ex.: IP público da VM), DNS para nomes.
if echo "$NOME" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; then
    SAN="IP:$NOME"
else
    SAN="DNS:$NOME"
fi
if [ "$NOME" != "localhost" ]; then
    SAN="$SAN,DNS:localhost"
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -subj "/CN=$NOME/O=Fintech SD" \
    -addext "subjectAltName=$SAN" \
    -keyout "$PASTA/fintech.key" -out "$PASTA/fintech.crt" 2>/dev/null
chmod 600 "$PASTA/fintech.key"

echo "Certificado TLS autoassinado gerado para $NOME ($SAN)."
