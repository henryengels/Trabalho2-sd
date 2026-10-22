"""Configuração do gateway.

Os valores vêm de variáveis de ambiente (no Docker, o docker-compose.yml as
preenche a partir do .env). Nenhum segredo fica no código: sem JWT_SEGREDO
válido, o gateway não inicia.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracoes(BaseSettings):
    # Fora do Docker, lê o .env da raiz do repositório (ou da pasta atual).
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Chave HMAC que assina os tokens. Com menos de 32 caracteres, o gateway recusa iniciar.
    jwt_segredo: str = Field(min_length=32)
    jwt_algoritmo: str = "HS256"
    jwt_expiracao_minutos: int = Field(default=30, ge=1, le=1440)

    # Origens autorizadas a chamar a API pelo navegador, separadas por vírgula.
    # Exemplo: https://localhost,https://34.123.45.67
    cors_origens: str = "https://localhost"

    # Endereços dos microsserviços gRPC na rede interna.
    contas_host: str = "localhost"
    contas_porta: int = 9091
    pagamentos_host: str = "localhost"
    pagamentos_porta: int = 9090
    # Prazo de cada chamada gRPC. Maior que o prazo pagamento → contas (5 s), para que
    # o gateway receba o erro do serviço de pagamentos em vez de desistir antes.
    grpc_timeout_segundos: float = 10.0

    # Swagger UI em /api/docs.
    docs_habilitada: bool = True

    @property
    def lista_cors(self) -> list[str]:
        return [origem.strip() for origem in self.cors_origens.split(",") if origem.strip()]


@lru_cache
def obter_configuracoes() -> Configuracoes:
    return Configuracoes()
