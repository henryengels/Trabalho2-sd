# Imagem do pagamento-service (Python 3.12). Contexto de build: raiz do repositório,
# porque os stubs gRPC são gerados a partir dos .proto em proto/.
FROM python:3.12-slim

# Logs aparecem imediatamente no "docker compose logs" e nenhum .pyc é gravado.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY pagamento-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Gera conta_pb2*.py e pagamento_pb2*.py: os mesmos contratos usados pelo Java.
COPY proto /proto
RUN mkdir gerado && python -m grpc_tools.protoc -I /proto \
      --python_out=gerado --grpc_python_out=gerado \
      /proto/conta.proto /proto/pagamento.proto

COPY pagamento-service/pagamento pagamento

RUN useradd --system --no-create-home fintech
USER fintech
EXPOSE 9090
CMD ["python", "-m", "pagamento.servidor"]
