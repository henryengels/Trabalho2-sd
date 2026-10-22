package aula.sd.fintech.conta;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;

// Abre o pool de conexões com o PostgreSQL e prepara as tabelas do serviço.
public final class BancoDeDados {

    private BancoDeDados() {
    }

    public static HikariDataSource conectar(String url, String usuario, String senha) {
        HikariConfig config = new HikariConfig();
        config.setPoolName("conta-service");
        config.setJdbcUrl(url);
        config.setUsername(usuario);
        config.setPassword(senha);
        config.setMaximumPoolSize(10);
        // Em contêineres, o banco (ou o Cloud SQL Auth Proxy) pode demorar alguns
        // segundos para aceitar conexões. O pool insiste por até 60 s antes de desistir.
        config.setInitializationFailTimeout(60_000);
        return new HikariDataSource(config);
    }

    // Executa o schema.sql empacotado no jar. Como ele usa IF NOT EXISTS, pode rodar
    // a cada inicialização sem apagar dados.
    public static void criarTabelas(DataSource banco) throws IOException, SQLException {
        String sql;
        try (InputStream entrada = BancoDeDados.class.getResourceAsStream("/schema.sql")) {
            if (entrada == null) {
                throw new IOException("schema.sql não encontrado no classpath.");
            }
            sql = new String(entrada.readAllBytes(), StandardCharsets.UTF_8);
        }
        try (Connection conexao = banco.getConnection(); Statement comando = conexao.createStatement()) {
            comando.execute(sql);
        }
    }
}
