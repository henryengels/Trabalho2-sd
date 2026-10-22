"""Inicializa o servidor gRPC do serviço de pagamentos.

Executar com: python -m pagamento.servidor
"""

import signal
from concurrent import futures

import grpc
from psycopg_pool import ConnectionPool

import pagamento_pb2_grpc

from . import config as configuracao
from .cliente_contas import ClienteContasGrpc
from .repositorio import TransacaoRepositorio
from .servico import PagamentoServiceImpl


def main() -> None:
    config = configuracao.carregar()

    # Pool de conexões com o PostgreSQL. Em contêineres, o banco (ou o Cloud SQL Auth
    # Proxy) pode demorar a aceitar conexões; open(wait=True) espera até 60 s.
    pool = ConnectionPool(config.conninfo(), name="pagamento-service", min_size=1, max_size=10, open=False)
    pool.open(wait=True, timeout=60)

    repositorio = TransacaoRepositorio(pool)
    repositorio.criar_tabelas()
    print(f"Conectado ao banco {config.db_host}:{config.db_porta}/{config.db_nome} (schema pagamento pronto)")

    contas = ClienteContasGrpc(config.contas_host, config.contas_porta)

    # Cada chamada gRPC é atendida por uma thread do pool.
    servidor = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pagamento_pb2_grpc.add_PagamentoServiceServicer_to_server(PagamentoServiceImpl(repositorio, contas), servidor)
    servidor.add_insecure_port(f"0.0.0.0:{config.porta}")
    servidor.start()

    print(f"Servidor de pagamentos gRPC ouvindo na porta {config.porta} "
          f"(serviço de contas em {config.contas_host}:{config.contas_porta})")

    # "docker compose stop" envia SIGTERM: termina as chamadas em andamento (até 5 s).
    def encerrar(_sinal, _quadro):
        print("Encerrando o servidor de pagamentos...")
        servidor.stop(grace=5)

    signal.signal(signal.SIGTERM, encerrar)
    signal.signal(signal.SIGINT, encerrar)

    # Mantém o processo ativo enquanto o servidor espera novas chamadas.
    servidor.wait_for_termination()
    contas.fechar()
    pool.close()


if __name__ == "__main__":
    main()
