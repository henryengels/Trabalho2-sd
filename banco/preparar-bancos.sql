-- Prepara um banco e um usuário para cada microsserviço (padrão database-per-service).
--
-- Executado pelo contêiner "preparar-banco" do docker-compose.yml, com o usuário
-- administrador "postgres", antes de os microsserviços iniciarem. Funciona igual no
-- PostgreSQL local e no Cloud SQL. Pode rodar várias vezes: só cria o que não existe
-- e atualiza as senhas a partir do .env.
--
-- Variáveis do psql (passadas com -v): senha_contas, senha_pagamentos.

\set ON_ERROR_STOP on
-- Esconde avisos informativos (ex.: "já é membro") quando o script roda de novo.
SET client_min_messages = warning;

-- Usuários das aplicações: sem privilégios de administrador.
SELECT 'CREATE ROLE conta_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'conta_app')\gexec
SELECT 'CREATE ROLE pagamento_app LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pagamento_app')\gexec

ALTER ROLE conta_app WITH LOGIN PASSWORD :'senha_contas';
ALTER ROLE pagamento_app WITH LOGIN PASSWORD :'senha_pagamentos';

-- Um banco por microsserviço.
SELECT 'CREATE DATABASE fintech_contas'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'fintech_contas')\gexec
SELECT 'CREATE DATABASE fintech_pagamentos'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'fintech_pagamentos')\gexec

-- Por padrão, qualquer usuário pode se conectar a qualquer banco (privilégio do grupo
-- PUBLIC). Removendo esse privilégio, cada usuário só acessa o banco do seu serviço:
-- pagamento_app não consegue abrir o banco de contas, e vice-versa.
REVOKE ALL ON DATABASE fintech_contas FROM PUBLIC;
REVOKE ALL ON DATABASE fintech_pagamentos FROM PUBLIC;

-- CONNECT para abrir conexões; CREATE para o serviço criar o próprio schema.
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE fintech_contas TO conta_app;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE fintech_pagamentos TO pagamento_app;

-- As tabelas pertencem aos usuários das aplicações, que as criam na inicialização.
-- No Cloud SQL o "postgres" não é superusuário: sem isto, ele recebe "permission denied"
-- ao consultar conta.contas ou pagamento.transacoes (Cloud SQL Studio, DBeaver, psql).
-- Aqui o administrador passa a herdar os privilégios dos dois usuários para consultar e
-- corrigir dados. Os usuários das aplicações continuam sem acesso ao banco um do outro.
GRANT conta_app TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;
GRANT pagamento_app TO CURRENT_USER WITH INHERIT TRUE, SET TRUE;

\echo 'Bancos prontos: fintech_contas (conta_app) e fintech_pagamentos (pagamento_app).'
