"""Microsserviço de pagamentos (Python).

Registra cada transação no PostgreSQL e delega a movimentação dos saldos ao
conta-service (Java) por gRPC.
"""

import sys
from pathlib import Path

# conta_pb2.py, pagamento_pb2.py e os *_pb2_grpc.py são gerados pelo protoc a partir
# de proto/ dentro da pasta gerado/ (no build da imagem Docker ou com o comando do
# README). O código gerado usa imports absolutos ("import conta_pb2"), por isso a
# pasta entra no sys.path antes de qualquer import dos stubs.
_PASTA_GERADA = Path(__file__).resolve().parent.parent / "gerado"
if str(_PASTA_GERADA) not in sys.path:
    sys.path.insert(0, str(_PASTA_GERADA))
