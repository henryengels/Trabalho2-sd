"""Respostas de erro padronizadas do gateway.

- Falha de validação do Pydantic (inclusive JSON malformado) → 400 Bad Request.
- Erro devolvido por um microsserviço gRPC → status HTTP equivalente.
"""

import logging

import grpc
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("api-gateway")

# Tradução dos códigos de status gRPC para HTTP.
GRPC_PARA_HTTP = {
    grpc.StatusCode.INVALID_ARGUMENT: 400,
    grpc.StatusCode.UNAUTHENTICATED: 401,
    grpc.StatusCode.PERMISSION_DENIED: 403,
    grpc.StatusCode.NOT_FOUND: 404,
    grpc.StatusCode.ALREADY_EXISTS: 409,
    # Operação desfeita por concorrência (conta bloqueada por outra operação além do
    # lock_timeout): nada foi gravado e pode ser repetida.
    grpc.StatusCode.ABORTED: 409,
    grpc.StatusCode.UNAVAILABLE: 503,
    grpc.StatusCode.DEADLINE_EXCEEDED: 503,
}

# Mensagens em português para os erros de validação mais comuns do Pydantic.
MENSAGENS_VALIDACAO = {
    "missing": "Campo obrigatório.",
    "extra_forbidden": "Campo não permitido.",
    "json_invalid": "JSON malformado.",
    "model_attributes_type": "O corpo da requisição deve ser um objeto JSON.",
    "dict_type": "O corpo da requisição deve ser um objeto JSON.",
    "string_type": "Deve ser um texto.",
    "string_too_short": "Deve ter pelo menos {min_length} caracteres.",
    "string_too_long": "Deve ter no máximo {max_length} caracteres.",
    "string_pattern_mismatch": "Formato inválido.",
    "decimal_parsing": "Deve ser um número.",
    "decimal_type": "Deve ser um número.",
    "decimal_max_places": "Use no máximo {decimal_places} casas decimais.",
    "decimal_max_digits": "Valor muito grande.",
    "greater_than": "Deve ser maior que {gt}.",
    "greater_than_equal": "Deve ser maior ou igual a {ge}.",
    "less_than_equal": "Deve ser menor ou igual a {le}.",
    "int_parsing": "Deve ser um número inteiro.",
}

MENSAGEM_FORMATO_CONTA = "Use de 3 a 30 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado."


def _traduzir(erro: dict) -> dict:
    # loc vem como ("body", "valor") ou ("query", "limite"); o primeiro item é a origem.
    # Erros do corpo inteiro (JSON malformado, corpo que não é objeto) são atribuídos a "corpo".
    if erro["type"] == "json_invalid" or len(erro["loc"]) == 1:
        campo = "corpo"
    else:
        campo = ".".join(str(p) for p in erro["loc"][1:])
    if erro["type"] == "string_pattern_mismatch" and campo.startswith("conta"):
        return {"campo": campo, "mensagem": MENSAGEM_FORMATO_CONTA}
    modelo = MENSAGENS_VALIDACAO.get(erro["type"])
    try:
        mensagem = modelo.format(**erro.get("ctx", {})) if modelo else erro["msg"]
    except (KeyError, IndexError):
        mensagem = erro["msg"]
    return {"campo": campo, "mensagem": mensagem}


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def dados_invalidos(_request: Request, erro: RequestValidationError) -> JSONResponse:
        # O FastAPI responderia 422; aqui a resposta é 400 Bad Request com a lista de campos.
        return JSONResponse(
            status_code=400,
            content={"detail": "Dados inválidos.", "erros": [_traduzir(e) for e in erro.errors()]},
        )

    @app.exception_handler(grpc.aio.AioRpcError)
    async def erro_grpc(request: Request, erro: grpc.aio.AioRpcError) -> JSONResponse:
        status = GRPC_PARA_HTTP.get(erro.code(), 502)
        log.warning("gRPC %s em %s %s: %s", erro.code().name, request.method, request.url.path, erro.details())
        if status == 503:
            mensagem = "Serviço temporariamente indisponível. Tente novamente em instantes."
        elif status >= 500:
            # Detalhes internos (ex.: erro de banco) não são expostos ao cliente.
            mensagem = "Falha ao processar a solicitação nos serviços internos."
        else:
            mensagem = erro.details() or "Requisição recusada."
        return JSONResponse(status_code=status, content={"detail": mensagem})
