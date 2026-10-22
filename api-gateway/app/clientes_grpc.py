"""Canais e stubs gRPC usados pelo gateway para falar com os microsserviços.

Os canais são assíncronos (grpc.aio): enquanto espera a resposta de um serviço,
o gateway continua atendendo outras requisições HTTP.
"""

import grpc
from fastapi import Request

import conta_pb2_grpc
import pagamento_pb2_grpc

from .config import Configuracoes


class ClientesGrpc:
    def __init__(self, config: Configuracoes):
        # Cada canal mantém uma conexão HTTP/2 reaproveitada por todas as chamadas.
        # O tráfego fica na rede interna do Docker; só o nginx é exposto para fora.
        self._canal_contas = grpc.aio.insecure_channel(f"{config.contas_host}:{config.contas_porta}")
        self._canal_pagamentos = grpc.aio.insecure_channel(f"{config.pagamentos_host}:{config.pagamentos_porta}")

        # conta-service (Java) e pagamento-service (Python).
        self.contas = conta_pb2_grpc.ContaServiceStub(self._canal_contas)
        self.pagamentos = pagamento_pb2_grpc.PagamentoServiceStub(self._canal_pagamentos)
        self.timeout = config.grpc_timeout_segundos

    async def fechar(self) -> None:
        await self._canal_contas.close()
        await self._canal_pagamentos.close()


def obter_clientes(request: Request) -> ClientesGrpc:
    """Dependência do FastAPI: devolve os clientes abertos na inicialização."""
    return request.app.state.grpc
