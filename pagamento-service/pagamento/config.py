"""Configuração do serviço lida de variáveis de ambiente.

No Docker os valores vêm do docker-compose.yml (que lê o .env). Os padrões
servem para rodar o serviço direto na máquina.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    porta: int
    contas_host: str
    contas_porta: int
    db_host: str
    db_porta: int
    db_nome: str
    db_usuario: str
    db_senha: str

    def conninfo(self) -> str:
        """String de conexão no formato aceito pelo psycopg (libpq).

        options define limites para cada sessão: no máximo 2 s esperando um lock e 5 s
        por comando. Sem eles o PostgreSQL espera para sempre, e uma consulta travada
        prenderia uma thread gRPC e uma conexão do pool.
        """
        return (
            f"host={self.db_host} port={self.db_porta} dbname={self.db_nome} "
            f"user={self.db_usuario} password={self.db_senha} "
            "options='-c lock_timeout=2s -c statement_timeout=5s'"
        )


def carregar() -> Config:
    return Config(
        porta=int(os.getenv("PORTA", "9090")),
        contas_host=os.getenv("CONTAS_HOST", "localhost"),
        contas_porta=int(os.getenv("CONTAS_PORTA", "9091")),
        db_host=os.getenv("DB_HOST", "localhost"),
        db_porta=int(os.getenv("DB_PORTA", "5432")),
        # O banco fintech_pagamentos é exclusivo deste serviço (database-per-service).
        db_nome=os.getenv("DB_NOME", "fintech_pagamentos"),
        db_usuario=os.getenv("DB_USUARIO", "pagamento_app"),
        db_senha=os.getenv("DB_SENHA", ""),
    )
