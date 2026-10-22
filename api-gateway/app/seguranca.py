"""Autenticação JWT na borda do sistema.

O middleware intercepta todas as requisições antes das rotas: sem um token
válido no cabeçalho "Authorization: Bearer <token>", a resposta é 401 e nada é
repassado aos microsserviços.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import Configuracoes

EMISSOR = "fintech-api-gateway"

# Rotas acessíveis sem token: cadastro, login, verificação de saúde e documentação.
ROTAS_PUBLICAS = frozenset({
    "/api/saude",
    "/api/auth/login",
    "/api/auth/registro",
    "/api/docs",
    "/api/docs/oauth2-redirect",
    "/api/openapi.json",
})


@dataclass(frozen=True)
class Usuario:
    conta: str
    titular: str


def emitir_token(conta: str, titular: str, config: Configuracoes) -> tuple[str, int]:
    """Gera o JWT assinado com HS256. Devolve o token e a validade em segundos."""
    agora = datetime.now(timezone.utc)
    validade = timedelta(minutes=config.jwt_expiracao_minutos)
    claims = {
        "sub": conta,          # identifica a conta dona do token
        "nome": titular,
        "iss": EMISSOR,
        "iat": agora,
        "exp": agora + validade,
    }
    token = jwt.encode(claims, config.jwt_segredo, algorithm=config.jwt_algoritmo)
    return token, int(validade.total_seconds())


def validar_token(token: str, config: Configuracoes) -> Usuario:
    """Confere assinatura, emissor e expiração. Lança jwt.InvalidTokenError se algo falhar."""
    claims = jwt.decode(
        token,
        config.jwt_segredo,
        # Lista fixa de algoritmos: impede tokens com "alg": "none" ou outro algoritmo.
        algorithms=[config.jwt_algoritmo],
        issuer=EMISSOR,
        options={"require": ["sub", "exp", "iat", "iss"]},
    )
    return Usuario(conta=claims["sub"], titular=claims.get("nome", ""))


class AutenticacaoJWTMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: Configuracoes):
        super().__init__(app)
        self._config = config

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in ROTAS_PUBLICAS:
            return await call_next(request)

        esquema, _, token = request.headers.get("Authorization", "").partition(" ")
        if esquema.lower() != "bearer" or not token.strip():
            return _nao_autorizado("Token de acesso ausente. Envie o cabeçalho Authorization: Bearer <token>.")

        try:
            # O usuário autenticado fica disponível para as rotas em request.state.
            request.state.usuario = validar_token(token.strip(), self._config)
        except jwt.ExpiredSignatureError:
            return _nao_autorizado("Token expirado. Faça login novamente.")
        except jwt.InvalidTokenError:
            return _nao_autorizado("Token inválido.")

        return await call_next(request)


def _nao_autorizado(mensagem: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": mensagem},
        headers={"WWW-Authenticate": "Bearer"},
    )


# Declara o esquema Bearer no OpenAPI (botão "Authorize" do Swagger). A validação
# em si é feita pelo middleware acima.
esquema_bearer = HTTPBearer(auto_error=False, description="JWT obtido em POST /api/auth/login")


def usuario_atual(
    request: Request,
    _credenciais: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
) -> Usuario:
    return request.state.usuario
