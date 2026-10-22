"""Depósito e transferência da conta autenticada."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

import pagamento_pb2

from ..clientes_grpc import ClientesGrpc, obter_clientes
from ..esquemas import DepositoEntrada, ErroSaida, ResultadoTransacaoSaida, TransferenciaEntrada
from ..seguranca import Usuario, usuario_atual

router = APIRouter(prefix="/api/transacoes", tags=["Transações"])

RESPOSTAS_ERRO = {
    400: {"model": ErroSaida},
    401: {"model": ErroSaida},
    422: {"model": ErroSaida, "description": "Transação recusada pela regra de negócio (ex.: saldo insuficiente)"},
    503: {"model": ErroSaida, "description": "Microsserviço indisponível"},
}


def _responder(resposta: pagamento_pb2.ProcessarTransacaoResponse):
    resultado = ResultadoTransacaoSaida(
        transacao_id=resposta.transacao_id,
        status=resposta.status,
        mensagem=resposta.mensagem,
        saldo_centavos=resposta.saldo_origem_centavos,
    )
    if resposta.status != "APROVADA":
        # A requisição era válida, mas a regra de negócio recusou (saldo insuficiente,
        # conta de destino inexistente...). A transação fica registrada como RECUSADA.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": resposta.mensagem, **resultado.model_dump()},
        )
    return resultado


@router.post(
    "/deposito",
    status_code=status.HTTP_201_CREATED,
    response_model=ResultadoTransacaoSaida,
    responses=RESPOSTAS_ERRO,
    summary="Deposita um valor na conta do usuário autenticado",
)
async def depositar(
    dados: DepositoEntrada,
    usuario: Usuario = Depends(usuario_atual),
    clientes: ClientesGrpc = Depends(obter_clientes),
):
    resposta = await clientes.pagamentos.RealizarDeposito(
        pagamento_pb2.RealizarDepositoRequest(conta=usuario.conta, valor_centavos=dados.valor_centavos()),
        timeout=clientes.timeout,
    )
    return _responder(resposta)


@router.post(
    "/transferencia",
    status_code=status.HTTP_201_CREATED,
    response_model=ResultadoTransacaoSaida,
    responses=RESPOSTAS_ERRO,
    summary="Transfere da conta do usuário autenticado para outra conta",
)
async def transferir(
    dados: TransferenciaEntrada,
    usuario: Usuario = Depends(usuario_atual),
    clientes: ClientesGrpc = Depends(obter_clientes),
):
    if dados.conta_destino == usuario.conta:
        raise HTTPException(status_code=400, detail="A conta de destino deve ser diferente da sua.")

    # Fluxo: gateway (Python) → pagamento-service (Python) → conta-service (Java).
    # A origem vem do token, nunca do corpo da requisição.
    resposta = await clientes.pagamentos.ProcessarTransacao(
        pagamento_pb2.ProcessarTransacaoRequest(
            conta_origem=usuario.conta,
            conta_destino=dados.conta_destino,
            valor_centavos=dados.valor_centavos(),
        ),
        timeout=clientes.timeout,
    )
    return _responder(resposta)
