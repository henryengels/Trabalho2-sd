"""Implementação do PagamentoService definido em proto/pagamento.proto."""

import functools
import uuid

import grpc
import psycopg
from google.protobuf.timestamp_pb2 import Timestamp
from psycopg import errors

import pagamento_pb2
import pagamento_pb2_grpc

from .cliente_contas import ClienteContasGrpc
from .repositorio import TransacaoRegistrada, TransacaoRepositorio

LIMITE_PADRAO = 20
LIMITE_MAXIMO = 100


def _tratar_erro_banco(metodo):
    """Converte falhas do PostgreSQL em status gRPC.

    O detalhe do erro fica só no log do servidor; o chamador recebe uma mensagem genérica.
    """

    @functools.wraps(metodo)
    def envolvido(self, request, context):
        try:
            return metodo(self, request, context)
        except (errors.LockNotAvailable, errors.QueryCanceled) as erro:
            # lock_timeout ou statement_timeout: o banco desfez o comando e nada foi gravado.
            print(f"Operação abortada por tempo no banco: {erro}")
            context.abort(grpc.StatusCode.ABORTED, "Banco de pagamentos ocupado; tente novamente.")
        except psycopg.Error as erro:
            print(f"Erro no banco de dados: {erro}")
            context.abort(grpc.StatusCode.INTERNAL, "Erro ao acessar o banco de dados.")

    return envolvido


class PagamentoServiceImpl(pagamento_pb2_grpc.PagamentoServiceServicer):
    """Recebe as solicitações do api-gateway, registra cada transação e delega a
    validação e a movimentação dos saldos ao conta-service (Java)."""

    def __init__(self, repositorio: TransacaoRepositorio, contas: ClienteContasGrpc):
        self._repositorio = repositorio
        self._contas = contas

    @_tratar_erro_banco
    def ProcessarTransacao(self, request, context):
        origem, destino, valor = request.conta_origem, request.conta_destino, request.valor_centavos
        _validar_entrada(context, valor, origem, destino)

        # A requisição já chega desserializada como uma mensagem Protobuf.
        transacao_id = self._repositorio.registrar("TRANSFERENCIA", origem, destino, valor)
        print(f"Transação {transacao_id} recebida: origem={origem}, destino={destino}, "
              f"valor={_formatar_reais(valor)}")

        # O serviço de contas (Java) valida saldo e contas e efetiva o débito/crédito.
        try:
            resultado = self._contas.transferir(origem, destino, valor)
        except grpc.RpcError as erro:
            self._registrar_falha(transacao_id, erro, context)

        status = "APROVADA" if resultado.aprovada else "RECUSADA"
        self._repositorio.atualizar_status(transacao_id, status, resultado.mensagem)
        print(f"Transação {transacao_id} {status}: {resultado.mensagem}")

        return pagamento_pb2.ProcessarTransacaoResponse(
            transacao_id=str(transacao_id),
            status=status,
            mensagem=resultado.mensagem,
            saldo_origem_centavos=resultado.saldo_origem_centavos,
        )

    @_tratar_erro_banco
    def RealizarDeposito(self, request, context):
        conta, valor = request.conta, request.valor_centavos
        _validar_entrada(context, valor, conta)

        transacao_id = self._repositorio.registrar("DEPOSITO", None, conta, valor)
        print(f"Depósito {transacao_id} recebido: conta={conta}, valor={_formatar_reais(valor)}")

        try:
            resultado = self._contas.depositar(conta, valor)
        except grpc.RpcError as erro:
            self._registrar_falha(transacao_id, erro, context)

        status = "APROVADA" if resultado.aprovada else "RECUSADA"
        self._repositorio.atualizar_status(transacao_id, status, resultado.mensagem)
        print(f"Depósito {transacao_id} {status}: {resultado.mensagem}")

        return pagamento_pb2.ProcessarTransacaoResponse(
            transacao_id=str(transacao_id),
            status=status,
            mensagem=resultado.mensagem,
            saldo_origem_centavos=resultado.saldo_centavos,
        )

    @_tratar_erro_banco
    def ListarTransacoes(self, request, context):
        if not request.conta:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Conta é obrigatória.")
        # limite = 0 significa "não informado" (valor padrão de int32 no proto3).
        limite = request.limite or LIMITE_PADRAO
        limite = max(1, min(limite, LIMITE_MAXIMO))

        transacoes = self._repositorio.listar(request.conta, limite)
        print(f"Extrato consultado: conta={request.conta}, itens={len(transacoes)}")
        return pagamento_pb2.ListarTransacoesResponse(transacoes=[_para_mensagem(t) for t in transacoes])

    @_tratar_erro_banco
    def ConsultarTransacao(self, request, context):
        if not request.conta:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Conta é obrigatória.")
        try:
            transacao_id = uuid.UUID(request.id)
        except ValueError:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Identificador de transação inválido.")

        transacao = self._repositorio.buscar(transacao_id, request.conta)
        if transacao is None:
            # A mesma resposta para id inexistente e para transação de outra conta: não revela
            # a terceiros que o identificador existe.
            context.abort(grpc.StatusCode.NOT_FOUND, "Transação não encontrada.")
        print(f"Transação consultada: id={transacao_id}, conta={request.conta}")
        return _para_mensagem(transacao)

    def _registrar_falha(self, transacao_id, erro: grpc.RpcError, context) -> None:
        """Marca a transação como FALHA e repassa ao chamador o status gRPC recebido.

        FALHA significa que o resultado não foi confirmado pelo conta-service. Não há
        nova tentativa automática: repetir uma transferência sem confirmação poderia
        debitar a conta duas vezes.
        """
        if erro.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            mensagem = "Sem resposta do serviço de contas; transação não confirmada."
        else:
            mensagem = erro.details() or "Falha ao chamar o serviço de contas."
        self._repositorio.atualizar_status(transacao_id, "FALHA", mensagem)
        print(f"Transação {transacao_id} FALHA: {erro.code().name} - {erro.details()}")
        # abort() lança uma exceção e encerra o RPC com o mesmo código (ex.: UNAVAILABLE).
        context.abort(erro.code(), mensagem)


def _validar_entrada(context, valor: int, *contas: str) -> None:
    """Defesa em profundidade: o gateway já valida, mas o serviço não confia nisso."""
    if any(not conta for conta in contas):
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Conta é obrigatória.")
    if valor <= 0:
        context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Valor deve ser maior que zero.")


def _para_mensagem(transacao: TransacaoRegistrada) -> pagamento_pb2.Transacao:
    # Timestamp do Protobuf: segundos e nanossegundos desde 1970 (UTC).
    criada_em = Timestamp(
        seconds=int(transacao.criada_em.timestamp()),
        nanos=transacao.criada_em.microsecond * 1000,
    )
    return pagamento_pb2.Transacao(
        id=str(transacao.id),
        tipo=transacao.tipo,
        conta_origem=transacao.conta_origem or "",
        conta_destino=transacao.conta_destino,
        valor_centavos=transacao.valor_centavos,
        status=transacao.status,
        mensagem=transacao.mensagem,
        criada_em=criada_em,
    )


def _formatar_reais(centavos: int) -> str:
    return f"R$ {centavos // 100},{abs(centavos % 100):02d}"
