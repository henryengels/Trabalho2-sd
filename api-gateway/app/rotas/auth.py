"""Cadastro e login (rotas públicas)."""

from fastapi import APIRouter, Depends, Response, status

import conta_pb2

from ..clientes_grpc import ClientesGrpc, obter_clientes
from ..config import Configuracoes, obter_configuracoes
from ..esquemas import ContaSaida, ErroSaida, LoginEntrada, RegistroEntrada, TokenSaida
from ..seguranca import emitir_token

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])


@router.post(
    "/registro",
    status_code=status.HTTP_201_CREATED,
    response_model=ContaSaida,
    responses={400: {"model": ErroSaida}, 409: {"model": ErroSaida, "description": "Conta já cadastrada"}},
    summary="Abre uma conta nova (saldo inicial zero)",
)
async def registrar(
    dados: RegistroEntrada,
    response: Response,
    clientes: ClientesGrpc = Depends(obter_clientes),
):
    # JSON já validado pelo Pydantic → mensagem Protobuf → chamada gRPC binária ao
    # conta-service (Java), que grava a conta no PostgreSQL.
    resposta = await clientes.contas.CriarConta(
        conta_pb2.CriarContaRequest(conta=dados.conta, titular=dados.titular, senha=dados.senha),
        timeout=clientes.timeout,
    )
    # A conta criada é consultada, depois do login, em /api/contas/me.
    response.headers["Location"] = "/api/contas/me"
    return ContaSaida(conta=resposta.conta, titular=resposta.titular, saldo_centavos=resposta.saldo_centavos)


@router.post(
    "/login",
    response_model=TokenSaida,
    responses={400: {"model": ErroSaida}, 401: {"model": ErroSaida, "description": "Conta ou senha inválidas"}},
    summary="Confere a senha e devolve um token JWT",
)
async def login(
    dados: LoginEntrada,
    clientes: ClientesGrpc = Depends(obter_clientes),
    config: Configuracoes = Depends(obter_configuracoes),
):
    # Senha incorreta volta do conta-service como UNAUTHENTICATED → 401 (ver erros.py).
    resposta = await clientes.contas.Autenticar(
        conta_pb2.AutenticarRequest(conta=dados.conta, senha=dados.senha),
        timeout=clientes.timeout,
    )
    token, validade = emitir_token(resposta.conta, resposta.titular, config)
    return TokenSaida(
        access_token=token,
        expira_em_segundos=validade,
        conta=resposta.conta,
        titular=resposta.titular,
    )
