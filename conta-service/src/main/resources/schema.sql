-- Tabelas do conta-service, no banco fintech_contas. Só o usuário conta_app tem acesso
-- a esse banco; os demais serviços consultam as contas apenas pelas chamadas gRPC do
-- ContaService. Executado a cada inicialização: os comandos IF NOT EXISTS não apagam dados.
CREATE SCHEMA IF NOT EXISTS conta;

CREATE TABLE IF NOT EXISTS conta.contas (
    -- Identificador escolhido pelo cliente; também é o login.
    id             VARCHAR(30)  PRIMARY KEY,
    titular        VARCHAR(100) NOT NULL,
    -- Hash BCrypt (60 caracteres, com sal embutido). A senha em texto nunca é gravada.
    senha_hash     VARCHAR(60)  NOT NULL,
    -- Saldo em centavos. O CHECK impede saldo negativo mesmo se a validação falhar.
    saldo_centavos BIGINT       NOT NULL DEFAULT 0 CHECK (saldo_centavos >= 0),
    criada_em      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
