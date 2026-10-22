-- Tabelas do pagamento-service, no banco fintech_pagamentos. Só o usuário pagamento_app
-- tem acesso a esse banco; os saldos ficam no banco fintech_contas, do conta-service.
-- Executado a cada inicialização: os comandos IF NOT EXISTS não apagam dados.
CREATE SCHEMA IF NOT EXISTS pagamento;

CREATE TABLE IF NOT EXISTS pagamento.transacoes (
    id             UUID         PRIMARY KEY,
    tipo           VARCHAR(15)  NOT NULL CHECK (tipo IN ('TRANSFERENCIA', 'DEPOSITO')),
    -- NULL em depósitos, que não têm conta de origem.
    conta_origem   VARCHAR(30),
    conta_destino  VARCHAR(30)  NOT NULL,
    valor_centavos BIGINT       NOT NULL CHECK (valor_centavos > 0),
    -- PENDENTE enquanto o conta-service processa; depois APROVADA, RECUSADA ou FALHA.
    status         VARCHAR(10)  NOT NULL CHECK (status IN ('PENDENTE', 'APROVADA', 'RECUSADA', 'FALHA')),
    mensagem       VARCHAR(200) NOT NULL DEFAULT '',
    criada_em      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    atualizada_em  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- O extrato busca as transações em que a conta é origem ou destino, das mais recentes
-- para as mais antigas.
CREATE INDEX IF NOT EXISTS transacoes_origem_idx  ON pagamento.transacoes (conta_origem, criada_em DESC);
CREATE INDEX IF NOT EXISTS transacoes_destino_idx ON pagamento.transacoes (conta_destino, criada_em DESC);
