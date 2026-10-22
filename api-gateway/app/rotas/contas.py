"""Consulta de saldo e extrato da conta autenticada."""

import asyncio
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query

import conta_pb2
import pagamento_pb2

from ..clientes_grpc import ClientesGrpc, obter_clientes
from ..esquemas import ContaSaida, ErroSaida, ExtratoSaida, TransacaoSaida
from ..seguranca import Usuario, usuario_atual

router = APIRouter(prefix="/api/contas", tags=["Contas"])


def _conta_saida(resposta: conta_pb2.ConsultarSaldoResponse) -> ContaSaida:
    if not resposta.existe:
        raise HTTPException(status_code=404, detail=resposta.mensagem)
    return ContaSaida(conta=resposta.conta, titular=resposta.titular, saldo_centavos=resposta.saldo_centavos)


@router.get(
    "/me",
    response_model=ContaSaida,
    responses={401: {"model": ErroSaida}},
    summary="Saldo da conta do usuário autenticado",
)
async def minha_conta(
    usuario: Usuario = Depends(usuario_atual),
    clientes: ClientesGrpc = Depends(obter_clientes),
):
    resposta = await clientes.contas.ConsultarSaldo(
        conta_pb2.ConsultarSaldoRequest(conta=usuario.conta),
        timeout=clientes.timeout,
    )
    return _conta_saida(resposta)


@router.get(
    "/me/extrato",
    response_model=ExtratoSaida,
    responses={400: {"model": ErroSaida}, 401: {"model": ErroSaida}},
    summary="Saldo (conta-service) e últimas transações (pagamento-service)",
)
async def extrato(
    limite: int = Query(default=20, ge=1, le=100),
    usuario: Usuario = Depends(usuario_atual),
    clientes: ClientesGrpc = Depends(obter_clientes),
):
    # Orquestração no gateway: as duas consultas vão para serviços diferentes (Java e
    # Python) ao mesmo tempo, e as respostas são combinadas num único JSON.
    saldo, lista = await asyncio.gather(
        clientes.contas.ConsultarSaldo(
            conta_pb2.ConsultarSaldoRequest(conta=usuario.conta),
            timeout=clientes.timeout,
        ),
        clientes.pagamentos.ListarTransacoes(
            pagamento_pb2.ListarTransacoesRequest(conta=usuario.conta, limite=limite),
            timeout=clientes.timeout,
        ),
    )
    transacoes = [
        TransacaoSaida(
            id=t.id,
            tipo=t.tipo,
            conta_origem=t.conta_origem or None,
            conta_destino=t.conta_destino,
            valor_centavos=t.valor_centavos,
            status=t.status,
            mensagem=t.mensagem,
            # google.protobuf.Timestamp → datetime com fuso UTC.
            criada_em=t.criada_em.ToDatetime(tzinfo=timezone.utc),
        )
        for t in lista.transacoes
    ]
    return ExtratoSaida(conta=_conta_saida(saldo), transacoes=transacoes)
