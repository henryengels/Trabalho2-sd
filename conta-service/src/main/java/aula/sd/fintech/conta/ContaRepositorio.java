package aula.sd.fintech.conta;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.function.BooleanSupplier;

// Acesso à tabela conta.contas por JDBC. Toda leitura e alteração de saldo do
// sistema passa por esta classe.
public class ContaRepositorio {

    // Linha da tabela conta.contas.
    public record Conta(String id, String titular, String senhaHash, long saldoCentavos) {
    }

    // Resultado de uma movimentação: motivoRecusa é null quando ela foi efetivada.
    public record Movimentacao(String motivoRecusa, long saldoCentavos) {
        public boolean aprovada() {
            return motivoRecusa == null;
        }
    }

    // Lançada quando quem chamou já desistiu (prazo gRPC esgotado) antes do commit;
    // a movimentação é desfeita.
    public static class ChamadaCanceladaException extends RuntimeException {
        public ChamadaCanceladaException() {
            super("O prazo do chamador acabou antes do commit.");
        }
    }

    private final DataSource banco;

    public ContaRepositorio(DataSource banco) {
        this.banco = banco;
    }

    // Devolve false se o identificador já existir (ON CONFLICT não sobrescreve).
    public boolean criar(String id, String titular, String senhaHash) throws SQLException {
        String sql = """
                INSERT INTO conta.contas (id, titular, senha_hash)
                VALUES (?, ?, ?)
                ON CONFLICT (id) DO NOTHING
                """;
        try (Connection conexao = banco.getConnection();
             PreparedStatement comando = conexao.prepareStatement(sql)) {
            comando.setString(1, id);
            comando.setString(2, titular);
            comando.setString(3, senhaHash);
            return comando.executeUpdate() == 1;
        }
    }

    public Optional<Conta> buscar(String id) throws SQLException {
        String sql = "SELECT id, titular, senha_hash, saldo_centavos FROM conta.contas WHERE id = ?";
        try (Connection conexao = banco.getConnection();
             PreparedStatement comando = conexao.prepareStatement(sql)) {
            comando.setString(1, id);
            try (ResultSet linha = comando.executeQuery()) {
                if (!linha.next()) {
                    return Optional.empty();
                }
                return Optional.of(new Conta(linha.getString("id"),
                                             linha.getString("titular"),
                                             linha.getString("senha_hash"),
                                             linha.getLong("saldo_centavos")));
            }
        }
    }

    // Débito e crédito acontecem na mesma transação do banco: ou os dois são
    // gravados (commit) ou nenhum (rollback). chamadaCancelada informa se quem chamou
    // já desistiu; nesse caso a transferência é desfeita em vez de confirmada.
    public Movimentacao transferir(String origem, String destino, long valor,
                                   BooleanSupplier chamadaCancelada) throws SQLException {
        try (Connection conexao = banco.getConnection()) {
            conexao.setAutoCommit(false);
            try {
                // FOR UPDATE bloqueia as duas linhas até o fim da transação, então duas
                // transferências simultâneas da mesma conta não leem o mesmo saldo.
                // ORDER BY id faz todas as transações bloquearem as contas na mesma
                // ordem, o que evita deadlock entre A→B e B→A.
                Map<String, Long> saldos = new HashMap<>();
                String sql = """
                        SELECT id, saldo_centavos FROM conta.contas
                        WHERE id IN (?, ?)
                        ORDER BY id
                        FOR UPDATE
                        """;
                try (PreparedStatement comando = conexao.prepareStatement(sql)) {
                    comando.setString(1, origem);
                    comando.setString(2, destino);
                    try (ResultSet linha = comando.executeQuery()) {
                        while (linha.next()) {
                            saldos.put(linha.getString("id"), linha.getLong("saldo_centavos"));
                        }
                    }
                }

                String motivoRecusa = validar(origem, destino, valor, saldos);
                if (motivoRecusa != null) {
                    conexao.rollback();
                    return new Movimentacao(motivoRecusa, saldos.getOrDefault(origem, 0L));
                }

                long saldoOrigem = somarAoSaldo(conexao, origem, -valor);
                somarAoSaldo(conexao, destino, valor);
                confirmar(conexao, chamadaCancelada);
                return new Movimentacao(null, saldoOrigem);
            } catch (SQLException | RuntimeException e) {
                conexao.rollback();
                throw e;
            }
        }
    }

    // Crédito numa transação, para também poder ser desfeito se quem chamou desistir.
    // RETURNING devolve o saldo resultante.
    public Movimentacao depositar(String conta, long valor, BooleanSupplier chamadaCancelada) throws SQLException {
        if (valor <= 0) {
            return new Movimentacao("Valor deve ser maior que zero.", 0L);
        }
        try (Connection conexao = banco.getConnection()) {
            conexao.setAutoCommit(false);
            try {
                Long saldo = somarAoSaldoSeExistir(conexao, conta, valor);
                if (saldo == null) {
                    conexao.rollback();
                    return new Movimentacao("Conta não encontrada.", 0L);
                }
                confirmar(conexao, chamadaCancelada);
                return new Movimentacao(null, saldo);
            } catch (SQLException | RuntimeException e) {
                conexao.rollback();
                throw e;
            }
        }
    }

    // Último ponto antes de gravar. Se o prazo do chamador (pagamento-service) já acabou,
    // ele registrou a transação como FALHA; confirmar agora movimentaria dinheiro que o
    // histórico diz não ter sido movimentado. Por isso a operação é desfeita.
    // Ainda resta uma janela pequena: o commit terminar e a resposta se perder na rede.
    private static void confirmar(Connection conexao, BooleanSupplier chamadaCancelada) throws SQLException {
        if (chamadaCancelada.getAsBoolean()) {
            throw new ChamadaCanceladaException();
        }
        conexao.commit();
    }

    // Mesmas regras do Trabalho 1, agora aplicadas aos saldos lidos do banco.
    // Devolve o motivo da recusa ou null quando a transferência pode ser feita.
    private static String validar(String origem, String destino, long valor, Map<String, Long> saldos) {
        if (valor <= 0) {
            return "Valor deve ser maior que zero.";
        }
        if (origem.equals(destino)) {
            return "Conta de origem e destino devem ser diferentes.";
        }
        if (!saldos.containsKey(origem)) {
            return "Conta de origem não encontrada.";
        }
        if (!saldos.containsKey(destino)) {
            return "Conta de destino não encontrada.";
        }
        if (saldos.get(origem) < valor) {
            return "Saldo insuficiente.";
        }
        return null;
    }

    private static long somarAoSaldo(Connection conexao, String conta, long valor) throws SQLException {
        Long saldo = somarAoSaldoSeExistir(conexao, conta, valor);
        if (saldo == null) {
            throw new SQLException("Conta " + conta + " deixou de existir durante a transação.");
        }
        return saldo;
    }

    private static Long somarAoSaldoSeExistir(Connection conexao, String conta, long valor) throws SQLException {
        String sql = """
                UPDATE conta.contas SET saldo_centavos = saldo_centavos + ?
                WHERE id = ?
                RETURNING saldo_centavos
                """;
        try (PreparedStatement comando = conexao.prepareStatement(sql)) {
            comando.setLong(1, valor);
            comando.setString(2, conta);
            try (ResultSet linha = comando.executeQuery()) {
                return linha.next() ? linha.getLong(1) : null;
            }
        }
    }
}
