#!/usr/bin/env bash
# Exercita a API pelo nginx (HTTPS), do mesmo jeito que o frontend faz, e confere
# o status HTTP de cada resposta: 401 sem token, 400 para dados inválidos,
# 201/200 em caso de sucesso, 404 para transação inexistente, 409 para conta
# duplicada e 422 para transação recusada. Confere também o cabeçalho Location.
#
# Uso:  bash scripts/testar-api.sh                     (padrão: https://localhost)
#       bash scripts/testar-api.sh https://34.123.45.67
#
# Requer apenas bash e curl (Git Bash no Windows, ou o terminal da VM).
# -k aceita o certificado autoassinado gerado pelo nginx.
set -u

BASE="${1:-https://localhost}"
SUFIXO="$(date +%s)"            # contas novas a cada execução
ORIGEM="ana_$SUFIXO"
DESTINO="bruno_$SUFIXO"
SENHA="senha-forte-123"
CORPO="$(mktemp)"
CABECALHOS="$(mktemp)"
trap 'rm -f "$CORPO" "$CABECALHOS"' EXIT

TOTAL=0
FALHAS=0

# requisicao MÉTODO CAMINHO [JSON] [TOKEN] → imprime o status HTTP; o corpo fica em
# $CORPO e os cabeçalhos da resposta em $CABECALHOS.
requisicao() {
    local args=(-sk -o "$CORPO" -D "$CABECALHOS" -w "%{http_code}" -X "$1" "$BASE$2" -H "Accept: application/json")
    [ -n "${3:-}" ] && args+=(-H "Content-Type: application/json" --data "$3")
    [ -n "${4:-}" ] && args+=(-H "Authorization: Bearer $4")
    curl "${args[@]}"
}

# verificar DESCRIÇÃO ESPERADO OBTIDO
verificar() {
    TOTAL=$((TOTAL + 1))
    if [ "$2" = "$3" ]; then
        printf '  \033[32mOK\033[0m   %s  %s\n' "$3" "$1"
    else
        printf '  \033[31mFALHOU\033[0m esperado %s, obtido %s  %s\n' "$2" "$3" "$1"
        FALHAS=$((FALHAS + 1))
    fi
    printf '       %s\n' "$(head -c 260 "$CORPO")"
}

echo "API em $BASE"
echo
echo "== Saúde e autenticação na borda"
verificar "GET /api/saude (pública)" 200 "$(requisicao GET /api/saude)"
verificar "GET /api/contas/me sem token" 401 "$(requisicao GET /api/contas/me)"
verificar "GET /api/contas/me com token inválido" 401 "$(requisicao GET /api/contas/me '' 'abc.def.ghi')"

echo
echo "== Cadastro (conta-service, Java)"
verificar "registro sem campos obrigatórios" 400 "$(requisicao POST /api/auth/registro '{}')"
verificar "registro com conta e senha inválidas" 400 \
    "$(requisicao POST /api/auth/registro '{"titular":"Ana","conta":"A!","senha":"123"}')"
verificar "registro com JSON malformado" 400 "$(requisicao POST /api/auth/registro '{"titular": ')"
verificar "registro de $ORIGEM" 201 \
    "$(requisicao POST /api/auth/registro "{\"titular\":\"Ana Souza\",\"conta\":\"$ORIGEM\",\"senha\":\"$SENHA\"}")"
verificar "registro de $DESTINO" 201 \
    "$(requisicao POST /api/auth/registro "{\"titular\":\"Bruno Lima\",\"conta\":\"$DESTINO\",\"senha\":\"$SENHA\"}")"
verificar "registro duplicado de $ORIGEM" 409 \
    "$(requisicao POST /api/auth/registro "{\"titular\":\"Ana Souza\",\"conta\":\"$ORIGEM\",\"senha\":\"$SENHA\"}")"

echo
echo "== Login (JWT emitido pelo gateway)"
verificar "login com senha errada" 401 \
    "$(requisicao POST /api/auth/login "{\"conta\":\"$ORIGEM\",\"senha\":\"senha-errada\"}")"
verificar "login de $ORIGEM" 200 "$(requisicao POST /api/auth/login "{\"conta\":\"$ORIGEM\",\"senha\":\"$SENHA\"}")"
TOKEN="$(sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p' "$CORPO")"

echo
echo "== Depósito (gateway → pagamento-service Python → conta-service Java)"
verificar "depósito com valor negativo" 400 "$(requisicao POST /api/transacoes/deposito '{"valor": -5}' "$TOKEN")"
verificar "depósito com 3 casas decimais" 400 "$(requisicao POST /api/transacoes/deposito '{"valor": 10.555}' "$TOKEN")"
verificar "depósito sem token" 401 "$(requisicao POST /api/transacoes/deposito '{"valor": 1000}')"
verificar "depósito de R$ 1.000,00" 201 "$(requisicao POST /api/transacoes/deposito '{"valor": 1000}' "$TOKEN")"

echo
echo "== Transferência"
verificar "transferência tentando informar a conta de origem" 400 \
    "$(requisicao POST /api/transacoes/transferencia "{\"conta_origem\":\"$DESTINO\",\"conta_destino\":\"$ORIGEM\",\"valor\":10}" "$TOKEN")"
verificar "transferência de R$ 150,50 para $DESTINO" 201 \
    "$(requisicao POST /api/transacoes/transferencia "{\"conta_destino\":\"$DESTINO\",\"valor\":150.50}" "$TOKEN")"
TRANSACAO="$(sed -n 's/.*"transacao_id":"\([^"]*\)".*/\1/p' "$CORPO")"
LOCATION="$(sed -n 's/^[Ll]ocation: *\([^[:space:]]*\).*/\1/p' "$CABECALHOS")"
verificar "cabeçalho Location do 201 aponta para o comprovante" "/api/transacoes/$TRANSACAO" "$LOCATION"
verificar "transferência acima do saldo (recusada)" 422 \
    "$(requisicao POST /api/transacoes/transferencia "{\"conta_destino\":\"$DESTINO\",\"valor\":100000}" "$TOKEN")"
verificar "transferência para conta inexistente (recusada)" 422 \
    "$(requisicao POST /api/transacoes/transferencia '{"conta_destino":"conta_que_nao_existe","valor":5}' "$TOKEN")"

echo
echo "== Consultas (dados lidos do PostgreSQL)"
verificar "saldo de $ORIGEM (esperado R\$ 849,50 = 84950 centavos)" 200 "$(requisicao GET /api/contas/me '' "$TOKEN")"
verificar "extrato de $ORIGEM (saldo do Java + transações do Python)" 200 \
    "$(requisicao GET '/api/contas/me/extrato?limite=5' '' "$TOKEN")"
verificar "extrato com limite inválido" 400 "$(requisicao GET '/api/contas/me/extrato?limite=0' '' "$TOKEN")"
verificar "comprovante da transferência (endereço do Location)" 200 "$(requisicao GET "$LOCATION" '' "$TOKEN")"
verificar "comprovante de transação inexistente" 404 \
    "$(requisicao GET /api/transacoes/00000000-0000-4000-8000-000000000000 '' "$TOKEN")"
verificar "comprovante com identificador inválido" 400 "$(requisicao GET /api/transacoes/abc '' "$TOKEN")"

echo
echo "$TOTAL verificações, $FALHAS falha(s)."
[ "$FALHAS" -eq 0 ]
