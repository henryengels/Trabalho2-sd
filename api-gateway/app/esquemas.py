"""Modelos Pydantic das requisições e respostas do gateway.

Toda entrada JSON é validada aqui antes de virar mensagem Protobuf. Campo
ausente, tipo errado, formato inválido ou campo desconhecido resultam em
400 Bad Request (ver erros.py) e não chegam aos microsserviços.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Identificador da conta (login): minúsculas, números, ".", "_" ou "-".
# "Ana" vira "ana" antes da validação do padrão.
Conta = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z0-9_.-]{3,30}$"),
    Field(examples=["ana"]),
]

# Valor em reais com no máximo 2 casas decimais, convertido depois para centavos.
Valor = Annotated[
    Decimal,
    Field(gt=0, le=Decimal("1000000.00"), max_digits=9, decimal_places=2, examples=[150.50]),
]


class Entrada(BaseModel):
    # Campos que não fazem parte do contrato são recusados em vez de ignorados.
    model_config = ConfigDict(extra="forbid")


class RegistroEntrada(Entrada):
    conta: Conta
    titular: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)] = Field(
        examples=["Ana Souza"])
    # 72 é o limite do BCrypt, usado pelo conta-service para guardar a senha.
    senha: Annotated[str, StringConstraints(min_length=8, max_length=72)] = Field(examples=["senha-forte-123"])


class LoginEntrada(Entrada):
    conta: Conta
    senha: Annotated[str, StringConstraints(min_length=1, max_length=72)] = Field(examples=["senha-forte-123"])


class DepositoEntrada(Entrada):
    valor: Valor

    def valor_centavos(self) -> int:
        return int(self.valor * 100)


class TransferenciaEntrada(Entrada):
    # A conta de origem não faz parte do corpo: vem do token JWT, então cada usuário
    # só consegue movimentar a própria conta.
    conta_destino: Conta
    valor: Valor

    def valor_centavos(self) -> int:
        return int(self.valor * 100)


class ContaSaida(BaseModel):
    conta: str
    titular: str
    saldo_centavos: int


class TokenSaida(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em_segundos: int
    conta: str
    titular: str


class ResultadoTransacaoSaida(BaseModel):
    transacao_id: str
    status: str
    mensagem: str
    # Saldo da conta do usuário logado após a operação.
    saldo_centavos: int


class TransacaoSaida(BaseModel):
    id: str
    tipo: str
    conta_origem: str | None
    conta_destino: str
    valor_centavos: int
    status: str
    mensagem: str
    criada_em: datetime

    @classmethod
    def de_protobuf(cls, t) -> "TransacaoSaida":
        """Converte a mensagem Protobuf Transacao (pagamento.proto) no JSON da API."""
        return cls(
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


class ExtratoSaida(BaseModel):
    conta: ContaSaida
    transacoes: list[TransacaoSaida]


class ErroCampo(BaseModel):
    campo: str
    mensagem: str


class ErroSaida(BaseModel):
    detail: str
    erros: list[ErroCampo] | None = None
