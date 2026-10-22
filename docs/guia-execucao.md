# Guia de execução local

Sobe o sistema inteiro na própria máquina com Docker Compose. O servidor PostgreSQL 18 roda em contêiner
(perfil `local`). Para o ambiente no Google Cloud, com Cloud SQL, veja [gcp.md](gcp.md).

## 1. Pré-requisitos

| Ferramenta     | Versão               | Observação                                                       |
|----------------|----------------------|------------------------------------------------------------------|
| Docker Desktop | 4.x (Compose v2)     | No Linux: Docker Engine + plugin `docker compose`                |
| Git            | qualquer             | No Windows, o Git Bash também roda o script de teste             |
| curl + bash    | qualquer             | Só para `scripts/testar-api.sh`                                   |

Java, Maven e Python **não** são necessários: as imagens Docker compilam tudo.

## 2. Configuração

Na raiz do repositório:

```bash
cp .env.example .env
```

No PowerShell: `Copy-Item .env.example .env`.

Edite o `.env` e preencha:

| Variável              | Valor local                                                                |
|-----------------------|----------------------------------------------------------------------------|
| `COMPOSE_PROFILES`    | `local`                                                                    |
| `DB_ADMIN_SENHA`      | senha do administrador `postgres` do contêiner (qualquer valor)            |
| `DB_CONTAS_SENHA`     | senha do usuário `conta_app` (qualquer valor)                              |
| `DB_PAGAMENTOS_SENHA` | senha do usuário `pagamento_app` (qualquer valor)                          |
| `JWT_SEGREDO`         | texto aleatório com 32 caracteres ou mais                                  |

Para gerar valores aleatórios (rode uma vez para cada campo):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# ou
openssl rand -hex 32
```

`CORS_ORIGENS=https://localhost` e `DOMINIO_CERTIFICADO=localhost` já servem para o uso local.

## 3. Subir

```bash
docker compose up -d --build
```

O primeiro build leva alguns minutos (Maven e pip baixam as dependências). Para acompanhar:

```bash
docker compose ps -a
docker compose logs -f preparar-banco conta-service pagamento-service api-gateway
```

Saída esperada nos logs:

```text
preparar-banco-1     | Bancos prontos: fintech_contas (conta_app) e fintech_pagamentos (pagamento_app).
conta-service-1      | Conectado ao banco jdbc:postgresql://banco:5432/fintech_contas (schema conta pronto)
conta-service-1      | Servidor de contas gRPC ouvindo na porta 9091
pagamento-service-1  | Conectado ao banco banco:5432/fintech_pagamentos (schema pagamento pronto)
pagamento-service-1  | Servidor de pagamentos gRPC ouvindo na porta 9090 (serviço de contas em conta-service:9091)
api-gateway-1        | INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
nginx-1              | Certificado TLS autoassinado gerado para localhost (DNS:localhost).
```

`preparar-banco` aparece como `Exited (0)` no `docker compose ps -a`. É esperado: ele só cria os bancos e
termina.

## 4. Usar

- Frontend: <https://localhost>. O navegador avisa que o certificado é autoassinado: escolha
  **Avançado → Continuar para localhost**.
- Swagger do gateway: <https://localhost/api/docs>. Para as rotas protegidas, use o botão **Authorize** com
  o `access_token` devolvido por `/api/auth/login`.

Roteiro de demonstração no frontend:

1. **Abrir conta** com `Bruno Lima` / `bruno` / `senha-forte-123`, e depois **Sair**.
2. **Abrir conta** com `Ana Souza` / `ana` / `senha-forte-123`. O frontend entra direto no painel.
3. Depositar `1000,00`. O saldo vai a R$ 1.000,00 e o extrato mostra o depósito APROVADO.
4. Transferir `150,50` para `bruno`. O saldo vai a R$ 849,50.
5. Transferir `10000` para `bruno`: a transferência é **RECUSADA** por saldo insuficiente (HTTP 422) e
   aparece no extrato.
6. Transferir para `zeca`: **RECUSADA**, porque a conta de destino não existe.
7. Tentar abrir conta com `Ana!` e senha `123`: os erros de validação (HTTP 400) aparecem embaixo de cada
   campo.

## 5. Testar os endpoints

Base da API: `https://localhost/api`. As rotas protegidas exigem o cabeçalho
`Authorization: Bearer <access_token>`, e o token vem de `POST /api/auth/login`.

### Swagger (já incluso, pelo navegador)

1. Abra <https://localhost/api/docs>.
2. Em `POST /api/auth/login`, clique em **Try it out**, preencha `conta` e `senha` e clique em **Execute**.
3. Copie o valor de `access_token` da resposta.
4. Clique em **Authorize** (cadeado no topo), cole **só o token**, sem a palavra `Bearer`, e confirme.
5. As demais rotas passam a enviar o token. Use **Try it out → Execute** em cada uma.

### Postman

O arquivo [postman/Fintech-SD.postman_collection.json](postman/Fintech-SD.postman_collection.json) traz
todas as rotas, na ordem, com os casos de sucesso e de erro (201, 200, 400, 401, 409, 422).

1. No Postman: **Import** → selecione o arquivo da coleção.
2. Desative a verificação do certificado autoassinado: **Settings → General → SSL certificate
   verification: OFF**.
3. Na coleção, aba **Variables**, confira `base_url` (`https://localhost`, ou `https://IP_DA_VM` na GCP).
4. Rode tudo com **Run collection**, ou uma requisição por vez, de cima para baixo.

Os registros criam contas novas a cada execução, e o login guarda o JWT na variável `token`, que as rotas
protegidas usam automaticamente. Cada requisição tem testes que conferem o status HTTP esperado.

### Insomnia

**Import** → selecione o mesmo arquivo `Fintech-SD.postman_collection.json` (o Insomnia aceita coleções do
Postman). Em **Preferences → Request/Response**, desmarque **Validate certificates**. Se os scripts da
coleção não rodarem na sua versão do Insomnia, depois do login copie o `access_token` para a variável
`token` e preencha `conta`/`destino` com os identificadores usados nos registros.

O CORS não afeta Postman nem Insomnia: ele só vale para páginas abertas no navegador.

### Script de linha de comando

```bash
bash scripts/testar-api.sh https://localhost
```

No Windows, rode pelo **Git Bash**. O script termina com `22 verificações, 0 falha(s).`

Se os testes forem executados várias vezes seguidas, pode aparecer `429 Too Many Requests`: é o rate
limit do nginx nas rotas de login e cadastro (30 por minuto). Aguarde um minuto e rode de novo.

## 6. Consultar e alterar o banco local

O servidor fica no contêiner `postgres`, com os dados no volume Docker `fintech_dados-postgres`. Eles
sobrevivem a `docker compose restart` e `docker compose down` e são independentes do Cloud SQL: o que é
criado aqui não aparece na nuvem, e vice-versa.

### Pelo DBeaver (ou pgAdmin)

No perfil `local`, o PostgreSQL fica acessível **só na própria máquina**, em `127.0.0.1:15432` (variável
`PORTA_BANCO_LOCAL` do `.env`). No DBeaver, crie a conexão em **Banco de dados → Nova conexão → PostgreSQL**:

| Campo             | Valor                                                        |
|-------------------|--------------------------------------------------------------|
| Host              | `localhost`                                                  |
| Port              | `15432`                                                      |
| Database          | `postgres`                                                   |
| Username          | `postgres`                                                   |
| Password          | o valor de `DB_ADMIN_SENHA` no `.env`                        |
| Aba **PostgreSQL**| marque **Show all databases**                                |

Com **Show all databases**, os dois bancos aparecem na árvore: `fintech_contas → Schemas → conta →
Tables → contas` e `fintech_pagamentos → Schemas → pagamento → Tables → transacoes`. Dê dois cliques na
tabela e abra a aba **Data** para ver e editar os registros.

Para entrar só no banco de um serviço, como a aplicação faz, use `Database: fintech_contas`,
`Username: conta_app` e `Password: DB_CONTAS_SENHA`. Esse usuário não consegue abrir o `fintech_pagamentos`.

O DBeaver baixa o driver do PostgreSQL na primeira conexão; aceite o download.

### Pelo terminal (psql)

Abrir o `psql` em cada banco, com o administrador:

```bash
docker compose exec postgres psql -U postgres -d fintech_contas
docker compose exec postgres psql -U postgres -d fintech_pagamentos
```

Dentro do `psql`: `\dt conta.*` ou `\dt pagamento.*` lista as tabelas, `\d conta.contas` mostra as colunas
e `\q` sai. Consultas úteis:

```sql
-- banco fintech_contas
SELECT id, titular, saldo_centavos, criada_em FROM conta.contas ORDER BY criada_em;

-- banco fintech_pagamentos
SELECT tipo, conta_origem, conta_destino, valor_centavos, status, mensagem, criada_em
FROM pagamento.transacoes ORDER BY criada_em DESC LIMIT 20;
```

Sem entrar no `psql`:

```bash
docker compose exec postgres psql -U postgres -d fintech_contas -c "SELECT id, titular, saldo_centavos FROM conta.contas;"
```

Alterar dados direto no banco (`UPDATE`, `DELETE`) funciona, mas ignora as regras da aplicação: por
exemplo, mudar um saldo à mão não gera transação no extrato. Para movimentar dinheiro, use o frontend ou a
API.

Para apagar todos os dados locais e começar do zero: `docker compose down -v` e depois
`docker compose up -d`.

## 7. Parar

```bash
docker compose down        # para e remove os contêineres; os dados continuam no volume
docker compose down -v     # remove também o volume (apaga o banco local)
```

Depois de alterar o código, reconstrua com `docker compose up -d --build`.

## 8. Rodar um serviço fora do Docker (desenvolvimento)

Precisa de um PostgreSQL acessível em `localhost:5432` com os bancos já criados por
`banco/preparar-bancos.sql`, e das variáveis `DB_*` exportadas no terminal.

```bash
# conta-service (Java 21)
./mvnw -pl conta-service -am package
java -jar conta-service/target/conta-service.jar

# pagamento-service (Python 3.12)
cd pagamento-service
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
mkdir gerado
python -m grpc_tools.protoc -I ../proto --python_out=gerado --grpc_python_out=gerado ../proto/conta.proto ../proto/pagamento.proto
python -m pagamento.servidor

# api-gateway
cd api-gateway
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
mkdir gerado
python -m grpc_tools.protoc -I ../proto --python_out=gerado --grpc_python_out=gerado ../proto/conta.proto ../proto/pagamento.proto
uvicorn app.main:app --port 8000                  # lê o ../.env
```

A pasta `gerado` está no `.gitignore`.

## 9. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `required variable ... is missing a value` | `.env` ausente ou com campo vazio | Crie o `.env` (passo 2) e preencha as senhas e o `JWT_SEGREDO` |
| `service "preparar-banco" didn't complete successfully` | Senha do administrador errada ou servidor inacessível | `docker compose logs preparar-banco`. Se `DB_ADMIN_SENHA` mudou depois de o volume ser criado, rode `docker compose down -v` |
| `Bind for 0.0.0.0:443 failed: port is already allocated` | Outra aplicação usa a porta 80 ou 443 | Mude `PORTA_HTTP`/`PORTA_HTTPS` no `.env` (ex.: 8080/8443) e acesse `https://localhost:8443` |
| `SSLError ... UNEXPECTED_EOF_WHILE_READING` no `pip install` durante o build | O DNS do Docker Desktop resolve `files.pythonhosted.org` para um IP errado (acontece com algumas redes, VPNs e antivírus) | Em Docker Desktop → Settings → Docker Engine, adicione `"dns": ["8.8.8.8", "1.1.1.1"]`, clique em **Apply & restart** e rode o build de novo |
| Navegador mostra "Sua conexão não é particular" | Certificado autoassinado | Esperado; avance pelo botão **Avançado** |
| `503 Serviço temporariamente indisponível` | Algum microsserviço parado ou ainda iniciando | `docker compose ps -a` e `docker compose logs <serviço>` |
| `401 Token expirado` no frontend | O JWT passou do prazo (`JWT_EXPIRACAO_MINUTOS`) | Entre de novo |
| `429 Too Many Requests` | Rate limit do nginx | Aguarde um minuto |
| `postgres` reiniciando com aviso sobre `/var/lib/postgresql/data` | Volume criado por uma versão anterior (PostgreSQL 16) | `docker compose down -v` e suba de novo |
| `Ports are not available ... 15432` ou `bind: ... forbidden by its access permissions` | Porta ocupada ou reservada pelo Windows (Hyper-V/WSL) | Troque `PORTA_BANCO_LOCAL` no `.env` (ex.: 25432). As faixas reservadas aparecem em `netsh interface ipv4 show excludedportrange protocol=tcp` |
| DBeaver: `Connection refused` | Perfil `gcp` no `.env` ou contêiner `postgres` parado | Confira `COMPOSE_PROFILES=local` e `docker compose ps` |
| Postman: `SSL Error: Self signed certificate` | Verificação SSL ligada | **Settings → General → SSL certificate verification: OFF** |
