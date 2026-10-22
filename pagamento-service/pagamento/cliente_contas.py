"""Cliente gRPC interno usado pelo serviço de pagamentos para falar com o
serviço de contas.

O conta-service é escrito em Java; aqui só existe o stub Python gerado a partir
do mesmo conta.proto. As mensagens viajam em Protobuf binário, então a linguagem
de cada lado não importa.
"""

import grpc

import conta_pb2
import conta_pb2_grpc

# Tempo máximo de espera por resposta. Sem prazo, uma chamada a um serviço travado
# prenderia a thread do servidor indefinidamente.
TIMEOUT_SEGUNDOS = 5


class ClienteContasGrpc:
    def __init__(self, host: str, porta: int):
        # O canal mantém a conexão HTTP/2 com o conta-service e é reaproveitado
        # por todas as chamadas.
        self._canal = grpc.insecure_channel(f"{host}:{porta}")
        self._stub = conta_pb2_grpc.ContaServiceStub(self._canal)

    def transferir(self, origem: str, destino: str, valor_centavos: int) -> conta_pb2.TransferirResponse:
        request = conta_pb2.TransferirRequest(
            conta_origem=origem,
            conta_destino=destino,
            valor_centavos=valor_centavos,
        )
        return self._stub.Transferir(request, timeout=TIMEOUT_SEGUNDOS)

    def depositar(self, conta: str, valor_centavos: int) -> conta_pb2.DepositarResponse:
        request = conta_pb2.DepositarRequest(conta=conta, valor_centavos=valor_centavos)
        return self._stub.Depositar(request, timeout=TIMEOUT_SEGUNDOS)

    def fechar(self) -> None:
        self._canal.close()
