"""Aplicação FastAPI: monta middlewares, tratadores de erro e rotas.

Executar com: uvicorn app.main:app --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .clientes_grpc import ClientesGrpc
from .config import obter_configuracoes
from .erros import registrar_tratadores
from .rotas import auth, contas, transacoes
from .seguranca import AutenticacaoJWTMiddleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

config = obter_configuracoes()


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Os canais gRPC assíncronos precisam ser criados dentro do event loop do servidor.
    app.state.grpc = ClientesGrpc(config)
    yield
    await app.state.grpc.fechar()


app = FastAPI(
    title="Fintech — API Gateway",
    version="2.0.0",
    description=(
        "Ponto único de entrada da fintech. Recebe JSON, valida com Pydantic, autentica com JWT "
        "e encaminha as operações por gRPC ao conta-service (Java) e ao pagamento-service (Python)."
    ),
    docs_url="/api/docs" if config.docs_habilitada else None,
    openapi_url="/api/openapi.json" if config.docs_habilitada else None,
    redoc_url=None,
    lifespan=ciclo_de_vida,
)

registrar_tratadores(app)

app.include_router(auth.router)
app.include_router(contas.router)
app.include_router(transacoes.router)


@app.get("/api/saude", tags=["Saúde"], summary="Verificação simples de funcionamento")
async def saude():
    return {"status": "ok"}


# No Starlette, o último middleware adicionado é o mais externo. A ordem fica:
# CORS → autenticação JWT → rotas. Assim as respostas 401 também recebem os
# cabeçalhos CORS e as requisições preflight (OPTIONS) não exigem token.
app.add_middleware(AutenticacaoJWTMiddleware, config=config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.lista_cors,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
    max_age=600,
)
