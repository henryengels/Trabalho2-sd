package aula.sd.fintech.conta;

import com.zaxxer.hikari.HikariDataSource;
import io.grpc.Server;
import io.grpc.ServerBuilder;

import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;

// Inicializa o servidor gRPC do serviço de contas: conecta ao PostgreSQL, garante que
// as tabelas existam e publica a implementação do ContaService.
public class ServidorContasGrpc {

    public static void main(String[] args) throws Exception {
        // Silencia os logs INFO do gRPC/Netty; só avisos e erros aparecem no console.
        Logger.getLogger("io.grpc").setLevel(Level.WARNING);

        // Configuração por variáveis de ambiente (definidas no docker-compose.yml a partir
        // do .env). Os valores padrão servem para rodar fora do Docker, na própria máquina.
        // O banco fintech_contas é exclusivo deste serviço (database-per-service).
        int porta = Integer.parseInt(variavel("PORTA", "9091"));
        String dbUrl = variavel("DB_URL", "jdbc:postgresql://localhost:5432/fintech_contas");
        String dbUsuario = variavel("DB_USUARIO", "conta_app");
        String dbSenha = variavel("DB_SENHA", "");

        HikariDataSource banco = BancoDeDados.conectar(dbUrl, dbUsuario, dbSenha);
        BancoDeDados.criarTabelas(banco);
        System.out.println("Conectado ao banco " + dbUrl + " (schema conta pronto)");

        // Registra o serviço que atenderá os métodos definidos no arquivo .proto.
        Server servidor = ServerBuilder.forPort(porta)
                                       .addService(new ContaServiceImpl(new ContaRepositorio(banco)))
                                       .build()
                                       .start();

        System.out.println("Servidor de contas gRPC ouvindo na porta " + porta);

        // "docker compose stop" envia SIGTERM: termina as chamadas em andamento e fecha o pool.
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("Encerrando o servidor de contas...");
            servidor.shutdown();
            try {
                servidor.awaitTermination(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            banco.close();
        }));

        // Mantém o processo ativo enquanto o servidor espera novas chamadas.
        servidor.awaitTermination();
    }

    private static String variavel(String nome, String padrao) {
        String valor = System.getenv(nome);
        return valor == null || valor.isBlank() ? padrao : valor;
    }
}
