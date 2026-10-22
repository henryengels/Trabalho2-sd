# syntax=docker/dockerfile:1
# Imagem do conta-service (Java 21). Contexto de build: raiz do repositório,
# porque o build precisa do pom pai, dos .proto e do módulo contratos-grpc.

# Estágio 1: compila com Maven e gera o jar executável (target/conta-service.jar).
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
COPY proto proto
COPY contratos-grpc contratos-grpc
COPY conta-service conta-service
# O cache de ~/.m2 evita baixar todas as dependências a cada build.
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q -pl conta-service -am package

# Estágio 2: apenas o JRE e o jar, rodando com um usuário sem privilégios.
FROM eclipse-temurin:21-jre
RUN useradd --system --no-create-home fintech
WORKDIR /app
COPY --from=build /build/conta-service/target/conta-service.jar app.jar
USER fintech
EXPOSE 9091
ENTRYPOINT ["java", "-Xmx256m", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8", "-jar", "app.jar"]
