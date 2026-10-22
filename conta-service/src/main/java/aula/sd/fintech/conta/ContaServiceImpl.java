package aula.sd.fintech.conta;

import aula.sd.fintech.grpc.AutenticarRequest;
import aula.sd.fintech.grpc.AutenticarResponse;
import aula.sd.fintech.grpc.ConsultarSaldoRequest;
import aula.sd.fintech.grpc.ConsultarSaldoResponse;
import aula.sd.fintech.grpc.ContaServiceGrpc;
import aula.sd.fintech.grpc.CriarContaRequest;
import aula.sd.fintech.grpc.CriarContaResponse;
import aula.sd.fintech.grpc.DepositarRequest;
import aula.sd.fintech.grpc.DepositarResponse;
import aula.sd.fintech.grpc.TransferirRequest;
import aula.sd.fintech.grpc.TransferirResponse;
import io.grpc.Context;
import io.grpc.Status;
import io.grpc.stub.StreamObserver;
import org.mindrot.jbcrypt.BCrypt;

import java.sql.SQLException;
import java.util.Optional;
import java.util.regex.Pattern;

// Implementa no servidor o contrato gerado a partir de ContaService no .proto.
// Recebe chamadas do api-gateway e do pagamento-service (ambos em Python) e grava
// tudo no PostgreSQL por meio do ContaRepositorio.
public class ContaServiceImpl extends ContaServiceGrpc.ContaServiceImplBase {

    // Mesmas regras validadas pelo gateway. Repetidas aqui porque o serviço não deve
    // confiar que todo chamador validou a entrada (defesa em profundidade).
    private static final Pattern FORMATO_CONTA = Pattern.compile("[a-z0-9_.-]{3,30}");
    private static final int SENHA_MIN = 8;
    private static final int SENHA_MAX = 72;
    private static final int TITULAR_MAX = 100;

    // Hash usado quando a conta não existe: a verificação BCrypt é feita mesmo assim,
    // para que o tempo de resposta não revele quais contas estão cadastradas.
    private static final String HASH_PARA_CONTA_INEXISTENTE = BCrypt.hashpw("conta-inexistente", BCrypt.gensalt());

    private final ContaRepositorio repositorio;

    public ContaServiceImpl(ContaRepositorio repositorio) {
        this.repositorio = repositorio;
    }

    @Override
    public void criarConta(CriarContaRequest request, StreamObserver<CriarContaResponse> responseObserver) {
        String conta = request.getConta();
        String titular = request.getTitular().strip();
        String senha = request.getSenha();

        System.out.printf("Criação de conta recebida: conta=%s%n", conta);

        if (!FORMATO_CONTA.matcher(conta).matches()) {
            responderErro(responseObserver, Status.INVALID_ARGUMENT,
                          "Conta deve ter de 3 a 30 caracteres: letras minúsculas, números, ponto, hífen ou sublinhado.");
            return;
        }
        if (titular.isEmpty() || titular.length() > TITULAR_MAX) {
            responderErro(responseObserver, Status.INVALID_ARGUMENT, "Titular deve ter de 1 a 100 caracteres.");
            return;
        }
        if (senha.length() < SENHA_MIN || senha.length() > SENHA_MAX) {
            responderErro(responseObserver, Status.INVALID_ARGUMENT, "Senha deve ter de 8 a 72 caracteres.");
            return;
        }

        try {
            // gensalt() gera um sal aleatório por conta; ele fica embutido no próprio hash.
            boolean criada = repositorio.criar(conta, titular, BCrypt.hashpw(senha, BCrypt.gensalt()));
            if (!criada) {
                responderErro(responseObserver, Status.ALREADY_EXISTS, "Conta já cadastrada.");
                return;
            }
            System.out.printf("Conta criada: conta=%s%n", conta);
            responseObserver.onNext(CriarContaResponse.newBuilder()
                                                      .setConta(conta)
                                                      .setTitular(titular)
                                                      .setSaldoCentavos(0L)
                                                      .build());
            responseObserver.onCompleted();
        } catch (SQLException e) {
            responderErroBanco(responseObserver, e);
        }
    }

    @Override
    public void autenticar(AutenticarRequest request, StreamObserver<AutenticarResponse> responseObserver) {
        String conta = request.getConta();
        try {
            Optional<ContaRepositorio.Conta> encontrada = repositorio.buscar(conta);
            String hash = encontrada.map(ContaRepositorio.Conta::senhaHash).orElse(HASH_PARA_CONTA_INEXISTENTE);
            boolean senhaCorreta = BCrypt.checkpw(request.getSenha(), hash);

            System.out.printf("Autenticação: conta=%s, sucesso=%s%n", conta, encontrada.isPresent() && senhaCorreta);

            if (encontrada.isEmpty() || !senhaCorreta) {
                // A mesma mensagem para conta inexistente e senha errada.
                responderErro(responseObserver, Status.UNAUTHENTICATED, "Conta ou senha inválidas.");
                return;
            }
            responseObserver.onNext(AutenticarResponse.newBuilder()
                                                      .setConta(conta)
                                                      .setTitular(encontrada.get().titular())
                                                      .build());
            responseObserver.onCompleted();
        } catch (SQLException e) {
            responderErroBanco(responseObserver, e);
        }
    }

    @Override
    public void consultarSaldo(ConsultarSaldoRequest request,
                               StreamObserver<ConsultarSaldoResponse> responseObserver) {
        String conta = request.getConta();
        try {
            Optional<ContaRepositorio.Conta> encontrada = repositorio.buscar(conta);
            boolean existe = encontrada.isPresent();

            System.out.printf("Consulta de saldo: conta=%s, existe=%s%n", conta, existe);

            ConsultarSaldoResponse response = ConsultarSaldoResponse.newBuilder()
                                                                    .setConta(conta)
                                                                    .setExiste(existe)
                                                                    .setSaldoCentavos(existe ? encontrada.get().saldoCentavos() : 0L)
                                                                    .setTitular(existe ? encontrada.get().titular() : "")
                                                                    .setMensagem(existe
                                                                                 ? "Conta encontrada."
                                                                                 : "Conta não encontrada.")
                                                                    .build();

            responseObserver.onNext(response);
            responseObserver.onCompleted();
        } catch (SQLException e) {
            responderErroBanco(responseObserver, e);
        }
    }

    @Override
    public void transferir(TransferirRequest request, StreamObserver<TransferirResponse> responseObserver) {
        String origem = request.getContaOrigem();
        String destino = request.getContaDestino();
        long valor = request.getValorCentavos();

        System.out.printf("Transferência recebida: origem=%s, destino=%s, valor=%s%n",
                          origem, destino, formatarReais(valor));

        try {
            // A validação e o débito/crédito acontecem dentro de uma transação do banco,
            // com as linhas das duas contas bloqueadas (ver ContaRepositorio.transferir).
            // Context.current() é esta chamada gRPC: fica cancelado quando o prazo enviado
            // pelo pagamento-service se esgota ou quando ele desiste da chamada.
            Context chamada = Context.current();
            ContaRepositorio.Movimentacao resultado =
                    repositorio.transferir(origem, destino, valor, chamada::isCancelled);

            TransferirResponse resposta = TransferirResponse.newBuilder()
                                                            .setAprovada(resultado.aprovada())
                                                            .setMensagem(resultado.aprovada()
                                                                         ? "Transferência efetivada."
                                                                         : resultado.motivoRecusa())
                                                            .setSaldoOrigemCentavos(resultado.saldoCentavos())
                                                            .build();

            System.out.printf("Resultado: aprovada=%s, mensagem=%s%n", resposta.getAprovada(), resposta.getMensagem());

            responseObserver.onNext(resposta);
            responseObserver.onCompleted();
        } catch (ContaRepositorio.ChamadaCanceladaException e) {
            responderCancelada(responseObserver, "Transferência desfeita");
        } catch (SQLException e) {
            responderErroBanco(responseObserver, e);
        }
    }

    @Override
    public void depositar(DepositarRequest request, StreamObserver<DepositarResponse> responseObserver) {
        String conta = request.getConta();
        long valor = request.getValorCentavos();

        System.out.printf("Depósito recebido: conta=%s, valor=%s%n", conta, formatarReais(valor));

        try {
            Context chamada = Context.current();
            ContaRepositorio.Movimentacao resultado = repositorio.depositar(conta, valor, chamada::isCancelled);

            DepositarResponse resposta = DepositarResponse.newBuilder()
                                                          .setAprovada(resultado.aprovada())
                                                          .setMensagem(resultado.aprovada()
                                                                       ? "Depósito efetivado."
                                                                       : resultado.motivoRecusa())
                                                          .setSaldoCentavos(resultado.saldoCentavos())
                                                          .build();

            System.out.printf("Resultado: aprovada=%s, mensagem=%s%n", resposta.getAprovada(), resposta.getMensagem());

            responseObserver.onNext(resposta);
            responseObserver.onCompleted();
        } catch (ContaRepositorio.ChamadaCanceladaException e) {
            responderCancelada(responseObserver, "Depósito desfeito");
        } catch (SQLException e) {
            responderErroBanco(responseObserver, e);
        }
    }

    // O chamador já desistiu; a resposta provavelmente não chegará, mas a chamada é encerrada
    // com o código correto e o log registra que nada foi gravado.
    private static void responderCancelada(StreamObserver<?> responseObserver, String operacaoDesfeita) {
        System.out.printf("%s: o prazo do chamador acabou antes do commit.%n", operacaoDesfeita);
        responderErro(responseObserver, Status.DEADLINE_EXCEEDED, operacaoDesfeita + ": prazo da chamada esgotado.");
    }

    // Erros de negócio viram status gRPC padronizados; o gateway converte cada um no
    // status HTTP correspondente (INVALID_ARGUMENT → 400, ALREADY_EXISTS → 409...).
    private static void responderErro(StreamObserver<?> responseObserver, Status status, String mensagem) {
        responseObserver.onError(status.withDescription(mensagem).asRuntimeException());
    }

    // O detalhe do erro SQL fica só no log do servidor; o chamador recebe uma mensagem genérica.
    private static void responderErroBanco(StreamObserver<?> responseObserver, SQLException e) {
        // 55P03 = lock_timeout (outra transação segurou a conta por mais de 2 s);
        // 57014 = statement_timeout (comando passou de 5 s). Nos dois casos houve rollback,
        // nada foi gravado e a operação pode ser repetida: ABORTED vira 409 no gateway.
        if ("55P03".equals(e.getSQLState()) || "57014".equals(e.getSQLState())) {
            System.err.printf("Operação abortada por tempo no banco: %s%n", e.getMessage());
            responderErro(responseObserver, Status.ABORTED, "Conta ocupada por outra operação; tente novamente.");
            return;
        }
        System.err.printf("Erro no banco de dados: %s%n", e.getMessage());
        responderErro(responseObserver, Status.INTERNAL, "Erro ao acessar o banco de dados.");
    }

    private static String formatarReais(long centavos) {
        return String.format("R$ %d,%02d", centavos / 100, Math.abs(centavos % 100));
    }
}
