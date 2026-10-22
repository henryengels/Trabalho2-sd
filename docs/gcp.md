# Implantação no Google Cloud

Topologia em produção:

- **Cloud SQL for PostgreSQL 18** guarda os dados: um servidor gerenciado com dois bancos,
  `fintech_contas` e `fintech_pagamentos`.
- Uma **VM Compute Engine** roda nginx, gateway e microsserviços com Docker Compose (perfil `gcp`).
- Na VM, o **Cloud SQL Auth Proxy** conecta os microsserviços ao Cloud SQL com TLS e autorização IAM, sem
  liberar IPs na instância.
- O contêiner `preparar-banco` cria os bancos e usuários na primeira subida. Não é preciso rodar SQL à mão.
- O firewall abre apenas as portas **80** e **443** da VM.

**Nenhum arquivo de código muda para a nuvem.** A diferença entre rodar local e na GCP está só no `.env`,
que no passo 5 é montado automaticamente no Cloud Shell e copiado para a VM.

Todos os comandos `gcloud` rodam no **Cloud Shell** (ícone `>_` no canto superior direito do console), que
já tem `gcloud` e `psql`. Não é preciso instalar nada no computador. Tempo total: cerca de 30 minutos, a
maior parte esperando o Cloud SQL e o build.

## 1. Projeto, variáveis e APIs

1. Em <https://console.cloud.google.com>, crie (ou escolha) um projeto com faturamento ativo. Os créditos
   gratuitos de avaliação cobrem o trabalho. Anote o **ID do projeto** (ex.: `fintech-sd-123456`).
2. Abra o Cloud Shell e rode, trocando `ID_DO_SEU_PROJETO`:

```bash
gcloud config set project ID_DO_SEU_PROJETO

cat > ~/fintech-vars.sh <<'EOF'
export PROJETO=$(gcloud config get-value project 2>/dev/null)
export REGIAO=us-central1
export ZONA=us-central1-a
export INSTANCIA=fintech-db
export VM=fintech-vm
EOF
source ~/fintech-vars.sh

gcloud services enable compute.googleapis.com sqladmin.googleapis.com
```

> Se o Cloud Shell desconectar, rode `source ~/fintech-vars.sh` antes de continuar.

## 2. Cloud SQL for PostgreSQL 18

Gere a senha do administrador `postgres` e guarde-a nas variáveis. Rode **uma vez só**: rodar de novo
troca a senha guardada, e ela deixa de ser igual à da instância.

```bash
echo "export DB_ADMIN_SENHA=$(openssl rand -hex 24)" >> ~/fintech-vars.sh
source ~/fintech-vars.sh
```

Crie a instância (leva de 5 a 10 minutos):

```bash
gcloud sql instances create $INSTANCIA \
  --database-version=POSTGRES_18 \
  --edition=enterprise \
  --tier=db-f1-micro \
  --region=$REGIAO \
  --storage-size=10GB \
  --root-password="$DB_ADMIN_SENHA"
```

- `--edition=enterprise` é necessário para usar `db-f1-micro`, a máquina mais barata. A edição padrão
  (Enterprise Plus) não aceita esse tipo.
- **Não** crie bancos nem usuários aqui: `fintech_contas`/`conta_app` e `fintech_pagamentos`/`pagamento_app`
  são criados pelo contêiner `preparar-banco` (passo 6).

## 3. Permissão da VM para acessar o Cloud SQL

A VM usa a service account padrão do Compute Engine. O Auth Proxy precisa que ela tenha o papel
**Cloud SQL Client**:

```bash
NUMERO=$(gcloud projects describe $PROJETO --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJETO \
  --member="serviceAccount:${NUMERO}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudsql.client" --condition=None
```

## 4. VM e firewall

```bash
gcloud compute instances create $VM \
  --zone=$ZONA \
  --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=20GB \
  --tags=fintech-web \
  --scopes=cloud-platform

gcloud compute firewall-rules create fintech-permitir-web \
  --network=default --direction=INGRESS --action=ALLOW \
  --rules=tcp:80,tcp:443 --target-tags=fintech-web --source-ranges=0.0.0.0/0
```

- `e2-medium` (4 GB) compila as imagens Java e Python sem falta de memória.
- `--scopes=cloud-platform` permite que a VM use o papel IAM do passo 3.

## 5. Gerar o `.env` da VM (no Cloud Shell)

O bloco abaixo descobre o IP público da VM e o nome de conexão do Cloud SQL, gera as senhas restantes e o
segredo JWT, e grava tudo em `~/fintech.env`. Copie e cole inteiro:

```bash
source ~/fintech-vars.sh
IP=$(gcloud compute instances describe $VM --zone=$ZONA --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
CONEXAO=$(gcloud sql instances describe $INSTANCIA --format='value(connectionName)')

cat > ~/fintech.env <<EOF
COMPOSE_PROFILES=gcp
CLOUD_SQL_INSTANCIA=$CONEXAO
DB_ADMIN_SENHA=$DB_ADMIN_SENHA
DB_CONTAS_SENHA=$(openssl rand -hex 24)
DB_PAGAMENTOS_SENHA=$(openssl rand -hex 24)
JWT_SEGREDO=$(openssl rand -hex 32)
JWT_EXPIRACAO_MINUTOS=30
CORS_ORIGENS=https://$IP
DOMINIO_CERTIFICADO=$IP
PORTA_HTTP=80
PORTA_HTTPS=443
DOCS_HABILITADA=true
EOF
chmod 600 ~/fintech.env
cat ~/fintech.env
```

Confira a saída. `CLOUD_SQL_INSTANCIA` deve estar no formato `projeto:us-central1:fintech-db`, e
`CORS_ORIGENS`/`DOMINIO_CERTIFICADO` devem ter o IP da VM. Então copie o arquivo para a VM:

```bash
gcloud compute scp ~/fintech.env $VM:~/fintech.env --zone=$ZONA
```

Na primeira vez, o `gcloud` cria uma chave SSH: aperte **Enter** nas perguntas (a frase-senha pode ficar
vazia).

> O `~/fintech.env` guarda segredos. Ele fica só no Cloud Shell e na VM: não o coloque no Git.

## 6. Instalar Docker e subir o sistema na VM

Entre na VM:

```bash
gcloud compute ssh $VM --zone=$ZONA
```

Dentro da VM, instale o Docker:

```bash
sudo apt-get update && sudo apt-get install -y git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Entre de novo (`gcloud compute ssh $VM --zone=$ZONA`) para o grupo `docker` valer e então:

```bash
git clone https://github.com/henryengels/Trabalho2-sd.git
cd Trabalho2-sd
cp ~/fintech.env .env
docker compose up -d --build
```

O primeiro build leva de 3 a 6 minutos. Depois, confira:

```bash
docker compose ps -a
docker compose logs cloud-sql-proxy preparar-banco conta-service pagamento-service
```

Resultado esperado:

```text
cloud-sql-proxy-1    | The proxy has started successfully and is ready for new connections!
preparar-banco-1     | Bancos prontos: fintech_contas (conta_app) e fintech_pagamentos (pagamento_app).
conta-service-1      | Conectado ao banco jdbc:postgresql://banco:5432/fintech_contas (schema conta pronto)
conta-service-1      | Servidor de contas gRPC ouvindo na porta 9091
pagamento-service-1  | Conectado ao banco banco:5432/fintech_pagamentos (schema pagamento pronto)
pagamento-service-1  | Servidor de pagamentos gRPC ouvindo na porta 9090 (serviço de contas em conta-service:9091)
```

No `docker compose ps -a`, `preparar-banco` aparece como `Exited (0)` (terminou com sucesso) e os demais
como `Up`. Os contêineres têm `restart: unless-stopped`, então voltam sozinhos quando a VM reinicia.

## 7. Acessar e testar

- Frontend: `https://IP_DA_VM`. O certificado é autoassinado: clique em **Avançado → Continuar**.
- Swagger: `https://IP_DA_VM/api/docs`.
- Teste automático (na VM, dentro de `Trabalho2-sd`, ou no Git Bash do computador):

```bash
bash scripts/testar-api.sh https://IP_DA_VM
```

- Postman ou Insomnia: importe `docs/postman/Fintech-SD.postman_collection.json` e troque a variável
  `base_url` para `https://IP_DA_VM`. As instruções completas, inclusive as do Swagger, estão na seção 5 do
  [guia de execução](guia-execucao.md).

## 8. Consultar e alterar os dados no Cloud SQL

Os dados da nuvem ficam só no Cloud SQL e não se misturam com o banco local da sua máquina.

**Opção A: Cloud SQL Studio (navegador).** Acesse **SQL → fintech-db → Cloud SQL Studio** e entre com:

| Banco                | Usuário    | Senha                                              |
|----------------------|------------|----------------------------------------------------|
| `fintech_contas`     | `postgres` | `DB_ADMIN_SENHA` (`grep ADMIN ~/fintech.env` no Cloud Shell) |
| `fintech_pagamentos` | `postgres` | a mesma                                            |

```sql
-- banco fintech_contas
SELECT id, titular, saldo_centavos, criada_em FROM conta.contas ORDER BY criada_em;

-- banco fintech_pagamentos
SELECT tipo, conta_origem, conta_destino, valor_centavos, status, mensagem, criada_em
FROM pagamento.transacoes ORDER BY criada_em DESC;
```

**Opção B: `psql` na VM**, passando pelo mesmo Auth Proxy da aplicação:

```bash
cd ~/Trabalho2-sd
docker compose run --rm --entrypoint psql preparar-banco -d fintech_contas
docker compose run --rm --entrypoint psql preparar-banco -d fintech_pagamentos
```

**Opção C: `psql` no Cloud Shell.**

```bash
gcloud sql connect $INSTANCIA --user=postgres --database=fintech_contas
```

O `gcloud` libera o IP do Cloud Shell por 5 minutos e pede a senha do `postgres`.

**Opção D: DBeaver no seu computador.** O Cloud SQL só aceita conexões vindas da internet de IPs
autorizados. Libere o IP da sua conexão e exija criptografia. No Cloud Shell:

```bash
source ~/fintech-vars.sh
gcloud sql instances patch $INSTANCIA --ssl-mode=ENCRYPTED_ONLY
```

Descubra o IP público da sua internet abrindo <https://ifconfig.me> no navegador do computador onde está
o DBeaver. Troque `SEU_IP` abaixo:

```bash
gcloud sql instances patch $INSTANCIA --authorized-networks=SEU_IP/32
gcloud sql instances describe $INSTANCIA --format='value(ipAddresses[0].ipAddress)'
```

Responda `Y` se o `gcloud` pedir confirmação. A última linha mostra o **IP do Cloud SQL**, que não é o IP
da VM. No DBeaver, em **Nova conexão → PostgreSQL**:

| Campo             | Valor                                                              |
|-------------------|--------------------------------------------------------------------|
| Host              | IP do Cloud SQL                                                    |
| Port              | `5432`                                                             |
| Database          | `postgres`                                                         |
| Username          | `postgres`                                                         |
| Password          | `DB_ADMIN_SENHA` (`grep ADMIN ~/fintech.env` no Cloud Shell)       |
| Aba **PostgreSQL**| marque **Show all databases**                                      |
| Aba **SSL**       | marque **Use SSL** e escolha **SSL mode: require**                 |

Cuidados:

- `--authorized-networks` substitui a lista inteira de IPs liberados.
- O IP de casa costuma mudar. Se o DBeaver parar de conectar, repita o comando com o IP novo.
- Ao terminar, retire a liberação com `gcloud sql instances patch $INSTANCIA --clear-authorized-networks`.

A aplicação não é afetada por nenhum desses comandos, porque usa o Auth Proxy.

## 9. Atualizar o código na VM

```bash
cd ~/Trabalho2-sd
git pull
docker compose up -d --build
```

## 10. Custos: pausar, retomar e apagar

Pausar quando não estiver usando. A VM parada não cobra CPU, e o Cloud SQL com `NEVER` não cobra a
instância (o disco continua sendo cobrado):

```bash
source ~/fintech-vars.sh
gcloud compute instances stop $VM --zone=$ZONA
gcloud sql instances patch $INSTANCIA --activation-policy=NEVER
```

Retomar:

```bash
source ~/fintech-vars.sh
gcloud sql instances patch $INSTANCIA --activation-policy=ALWAYS
gcloud compute instances start $VM --zone=$ZONA
```

> O IP público da VM é efêmero e **muda** depois de parar e iniciar. Nesse caso, na VM, troque o IP antigo
> pelo novo em `CORS_ORIGENS` e `DOMINIO_CERTIFICADO` do `.env` e rode
> `docker compose up -d --force-recreate nginx api-gateway`. Para manter o IP fixo, promova-o a estático em
> **VPC network → IP addresses**. Há cobrança enquanto a VM estiver parada.

Apagar tudo no fim do semestre:

```bash
source ~/fintech-vars.sh
gcloud compute instances delete $VM --zone=$ZONA
gcloud compute firewall-rules delete fintech-permitir-web
gcloud sql instances delete $INSTANCIA
```

## 11. Certificado de uma autoridade certificadora (opcional)

Com um domínio apontando para o IP da VM, um certificado Let's Encrypt elimina o aviso do navegador:

```bash
docker compose stop nginx
sudo apt-get install -y certbot
sudo certbot certonly --standalone -d seu.dominio.com
mkdir -p nginx/certs
sudo cp /etc/letsencrypt/live/seu.dominio.com/fullchain.pem nginx/certs/fintech.crt
sudo cp /etc/letsencrypt/live/seu.dominio.com/privkey.pem  nginx/certs/fintech.key
sudo chown $USER nginx/certs/*
```

Em seguida:

1. Adicione ao serviço `nginx` do `docker-compose.yml` o volume `- ./nginx/certs:/etc/nginx/certs:ro`.
2. Troque `CORS_ORIGENS` para `https://seu.dominio.com`.
3. Rode `docker compose up -d nginx api-gateway`.

O script de inicialização do nginx só gera um certificado autoassinado quando não encontra um em
`/etc/nginx/certs`.

## 12. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Invalid Tier (db-f1-micro) for (ENTERPRISE_PLUS) Edition` | Faltou `--edition=enterprise` | Repita o comando do passo 2 com o parâmetro |
| `cloud-sql-proxy` com `NOT_AUTHORIZED` ou `403` | Falta o papel Cloud SQL Client ou a VM foi criada sem `--scopes=cloud-platform` | Refaça o passo 3. Se o escopo estiver errado, pare a VM e ajuste em **Editar → Escopos de acesso → Permitir acesso completo** |
| `cloud-sql-proxy` com `invalid instance connection name` | `CLOUD_SQL_INSTANCIA` vazio ou errado | Confira com `gcloud sql instances describe $INSTANCIA --format='value(connectionName)'` |
| `service "preparar-banco" didn't complete successfully` e log com `password authentication failed for user "postgres"` | `DB_ADMIN_SENHA` diferente da senha do `postgres` no Cloud SQL | No Cloud Shell: `gcloud sql users set-password postgres --instance=$INSTANCIA --password=SENHA_DO_.ENV`; depois `docker compose up -d` na VM |
| `preparar-banco` repetindo `Aguardando o PostgreSQL em banco...` | Proxy sem acesso ao Cloud SQL ou instância parada | `docker compose logs cloud-sql-proxy`; confira se a instância está `RUNNABLE` no console |
| Navegador não abre `https://IP` | Regra de firewall ausente ou IP mudou | Confira o passo 4 e o IP atual da VM |
| Build interrompido (`Killed`) | Pouca memória na VM | Use `e2-medium` ou maior |
| `permission denied ... docker.sock` | Usuário fora do grupo `docker` | Saia e entre de novo na VM após o `usermod` |
| `permission denied for schema conta` (ou `pagamento`) ao consultar como `postgres` | No Cloud SQL o `postgres` não é superusuário, e as tabelas pertencem a `conta_app`/`pagamento_app`. Versões do `banco/preparar-bancos.sql` sem os comandos `GRANT ... TO CURRENT_USER` | `git pull && docker compose up -d` na VM. O `preparar-banco` roda de novo e dá ao `postgres` acesso às tabelas |
