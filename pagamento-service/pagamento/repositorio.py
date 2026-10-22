"""Acesso à tabela pagamento.transacoes com psycopg 3.

Todos os comandos usam parâmetros (%s); os valores nunca são concatenados no SQL,
o que impede injeção de SQL.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from psycopg_pool import ConnectionPool

_SCHEMA = Path(__file__).resolve().parent / "schema.sql"
# Lista fixa de colunas, escrita no código (nunca vem do usuário); os valores das
# consultas continuam sempre em parâmetros %s.
_COLUNAS = "id, tipo, conta_origem, conta_destino, valor_centavos, status, mensagem, criada_em"


@dataclass(frozen=True)
class TransacaoRegistrada:
    id: uuid.UUID
    tipo: str
    conta_origem: str | None
    conta_destino: str
    valor_centavos: int
    status: str
    mensagem: str
    criada_em: datetime


class TransacaoRepositorio:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def criar_tabelas(self) -> None:
        # pool.connection() faz commit ao sair do bloco sem erro (rollback se houver erro).
        with self._pool.connection() as conexao:
            conexao.execute(_SCHEMA.read_text(encoding="utf-8"))

    def registrar(self, tipo: str, origem: str | None, destino: str, valor_centavos: int) -> uuid.UUID:
        """Grava a transação como PENDENTE antes de chamar o conta-service.

        Assim existe registro mesmo que o conta-service esteja fora do ar ou que a
        chamada falhe no meio do caminho.
        """
        transacao_id = uuid.uuid4()
        with self._pool.connection() as conexao:
            conexao.execute(
                """
                INSERT INTO pagamento.transacoes
                    (id, tipo, conta_origem, conta_destino, valor_centavos, status, mensagem)
                VALUES (%s, %s, %s, %s, %s, 'PENDENTE', 'Aguardando o serviço de contas.')
                """,
                (transacao_id, tipo, origem, destino, valor_centavos),
            )
        return transacao_id

    def atualizar_status(self, transacao_id: uuid.UUID, status: str, mensagem: str) -> None:
        with self._pool.connection() as conexao:
            conexao.execute(
                """
                UPDATE pagamento.transacoes
                SET status = %s, mensagem = %s, atualizada_em = now()
                WHERE id = %s
                """,
                (status, mensagem[:200], transacao_id),
            )

    def listar(self, conta: str, limite: int) -> list[TransacaoRegistrada]:
        with self._pool.connection() as conexao:
            linhas = conexao.execute(
                f"""
                SELECT {_COLUNAS}
                FROM pagamento.transacoes
                WHERE conta_origem = %s OR conta_destino = %s
                ORDER BY criada_em DESC
                LIMIT %s
                """,
                (conta, conta, limite),
            ).fetchall()
        return [TransacaoRegistrada(*linha) for linha in linhas]

    def buscar(self, transacao_id: uuid.UUID, conta: str) -> TransacaoRegistrada | None:
        """Devolve a transação só se a conta for origem ou destino dela."""
        with self._pool.connection() as conexao:
            linha = conexao.execute(
                f"""
                SELECT {_COLUNAS}
                FROM pagamento.transacoes
                WHERE id = %s AND (conta_origem = %s OR conta_destino = %s)
                """,
                (transacao_id, conta, conta),
            ).fetchone()
        return TransacaoRegistrada(*linha) if linha else None
