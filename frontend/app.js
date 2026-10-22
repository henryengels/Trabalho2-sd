// Frontend da fintech. Fala apenas com o API Gateway, pelo caminho relativo /api
// (o nginx encaminha para o FastAPI). Nunca acessa os microsserviços gRPC diretamente.
"use strict";

const API = "/api";
const CHAVE_SESSAO = "fintech.sessao";

const moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const dataHora = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

const $ = (id) => document.getElementById(id);

// Sessão = token JWT + dados da conta. Fica no sessionStorage: some ao fechar a aba.
let sessao = carregarSessao();

class ErroApi extends Error {
  constructor(status, corpo) {
    super((corpo && corpo.detail) || `Erro HTTP ${status}`);
    this.status = status;
    this.erros = (corpo && corpo.erros) || [];
  }
}

// Envia JSON ao gateway e devolve o JSON da resposta. Respostas fora da faixa 2xx
// viram ErroApi com a mensagem enviada pelo gateway.
async function chamarApi(caminho, { metodo = "GET", corpo } = {}) {
  const cabecalhos = { Accept: "application/json" };
  if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  // Rotas protegidas exigem o token no cabeçalho Authorization: Bearer <token>.
  if (sessao) cabecalhos.Authorization = `Bearer ${sessao.token}`;

  let resposta;
  try {
    resposta = await fetch(API + caminho, {
      method: metodo,
      headers: cabecalhos,
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ErroApi(0, { detail: "Não foi possível falar com o servidor." });
  }

  let dados = null;
  try { dados = await resposta.json(); } catch { /* corpo vazio */ }

  if (resposta.status === 401 && sessao) {
    // Token expirado ou inválido: volta para a tela de login.
    encerrarSessao();
    throw new ErroApi(401, { detail: "Sua sessão expirou. Entre novamente." });
  }
  if (!resposta.ok) throw new ErroApi(resposta.status, dados);
  return dados;
}

// ---------- sessão ----------

function carregarSessao() {
  try {
    const salva = JSON.parse(sessionStorage.getItem(CHAVE_SESSAO));
    if (salva && salva.token && salva.expiraEm > Date.now()) return salva;
  } catch { /* armazenamento indisponível */ }
  return null;
}

function iniciarSessao(login) {
  sessao = {
    token: login.access_token,
    conta: login.conta,
    titular: login.titular,
    expiraEm: Date.now() + login.expira_em_segundos * 1000,
  };
  try { sessionStorage.setItem(CHAVE_SESSAO, JSON.stringify(sessao)); } catch { /* ignora */ }
  mostrarPainel();
}

function encerrarSessao() {
  sessao = null;
  try { sessionStorage.removeItem(CHAVE_SESSAO); } catch { /* ignora */ }
  mostrarAcesso();
}

// ---------- telas ----------

function mostrarAcesso() {
  $("tela-painel").hidden = true;
  $("usuario-topo").hidden = true;
  $("tela-acesso").hidden = false;
}

function mostrarPainel() {
  $("tela-acesso").hidden = true;
  $("tela-painel").hidden = false;
  $("usuario-topo").hidden = false;
  $("topo-titular").textContent = sessao.titular;
  $("topo-conta").textContent = sessao.conta;
  atualizarExtrato();
}

function trocarAba(registro) {
  $("aba-login").classList.toggle("ativa", !registro);
  $("aba-registro").classList.toggle("ativa", registro);
  $("aba-login").setAttribute("aria-selected", String(!registro));
  $("aba-registro").setAttribute("aria-selected", String(registro));
  $("form-login").hidden = registro;
  $("form-registro").hidden = !registro;
}

let temporizadorAviso;
function avisar(mensagem, tipo = "sucesso") {
  const aviso = $("aviso");
  aviso.textContent = mensagem;
  aviso.className = `aviso aviso-${tipo}`;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 4500);
}

// ---------- extrato ----------

async function atualizarExtrato() {
  try {
    const extrato = await chamarApi("/contas/me/extrato?limite=30");
    $("saldo").textContent = moeda.format(extrato.conta.saldo_centavos / 100);
    desenharExtrato(extrato.transacoes);
  } catch (erro) {
    avisar(erro.message, "erro");
  }
}

function desenharExtrato(transacoes) {
  const corpo = $("linhas-extrato");
  corpo.replaceChildren();
  $("extrato-vazio").hidden = transacoes.length > 0;

  for (const t of transacoes) {
    const enviada = t.tipo === "TRANSFERENCIA" && t.conta_origem === sessao.conta;
    let descricao;
    if (t.tipo === "DEPOSITO") descricao = "Depósito";
    else if (enviada) descricao = `Transferência para ${t.conta_destino}`;
    else descricao = `Transferência de ${t.conta_origem}`;

    const valor = moeda.format(t.valor_centavos / 100);
    const aprovada = t.status === "APROVADA";

    const linha = document.createElement("tr");
    // textContent (e não innerHTML) evita que dados vindos da API sejam interpretados como HTML.
    linha.append(
      celula(dataHora.format(new Date(t.criada_em))),
      celula(descricao, "descricao", aprovada ? "" : t.mensagem),
      celulaSelo(t.status),
      celula(
        aprovada ? `${enviada ? "−" : "+"} ${valor}` : valor,
        `num ${aprovada ? (enviada ? "valor-negativo" : "valor-positivo") : "valor-neutro"}`,
      ),
    );
    corpo.append(linha);
  }
}

function celula(texto, classe = "", detalhe = "") {
  const td = document.createElement("td");
  td.textContent = texto;
  if (classe) td.className = classe;
  if (detalhe) {
    const span = document.createElement("span");
    span.className = "detalhe";
    span.textContent = detalhe;
    td.append(span);
  }
  return td;
}

function celulaSelo(status) {
  const td = document.createElement("td");
  const selo = document.createElement("span");
  selo.className = `selo selo-${status}`;
  selo.textContent = status;
  td.append(selo);
  return td;
}

// ---------- formulários ----------

// "150,50" → 150.5. Texto que não é número segue como está, e o gateway responde 400.
function lerValor(texto) {
  const normalizado = texto.trim().replace(/\./g, (m, i, s) => (s.includes(",") ? "" : m)).replace(",", ".");
  const numero = Number(normalizado);
  return normalizado !== "" && Number.isFinite(numero) ? numero : texto;
}

function limparErros(form) {
  form.querySelectorAll(".erro-campo").forEach((e) => e.remove());
  form.querySelectorAll(".invalido").forEach((e) => e.classList.remove("invalido"));
}

// Mostra, ao lado de cada campo, os erros de validação devolvidos pelo gateway (400).
function mostrarErros(form, erro) {
  for (const { campo, mensagem } of erro.erros) {
    const input = form.elements[campo];
    if (!input) continue;
    input.classList.add("invalido");
    const span = document.createElement("span");
    span.className = "erro-campo";
    span.textContent = mensagem;
    input.after(span);
  }
  avisar(erro.message, "erro");
}

// Liga um formulário a uma ação assíncrona, cuidando do botão e das mensagens de erro.
function aoEnviar(form, acao) {
  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    limparErros(form);
    const botao = form.querySelector("button[type=submit]");
    botao.disabled = true;
    try {
      await acao(new FormData(form));
    } catch (erro) {
      if (erro instanceof ErroApi) mostrarErros(form, erro);
      else avisar("Erro inesperado no navegador.", "erro");
    } finally {
      botao.disabled = false;
    }
  });
}

function configurar() {
  $("aba-login").addEventListener("click", () => trocarAba(false));
  $("aba-registro").addEventListener("click", () => trocarAba(true));
  $("botao-sair").addEventListener("click", encerrarSessao);
  $("botao-atualizar").addEventListener("click", atualizarExtrato);

  aoEnviar($("form-login"), async (dados) => {
    const login = await chamarApi("/auth/login", {
      metodo: "POST",
      corpo: { conta: dados.get("conta"), senha: dados.get("senha") },
    });
    $("form-login").reset();
    iniciarSessao(login);
  });

  aoEnviar($("form-registro"), async (dados) => {
    const credenciais = { conta: dados.get("conta"), senha: dados.get("senha") };
    const conta = await chamarApi("/auth/registro", {
      metodo: "POST",
      corpo: { titular: dados.get("titular"), ...credenciais },
    });
    // Conta criada (201): entra direto com as mesmas credenciais.
    const login = await chamarApi("/auth/login", { metodo: "POST", corpo: { ...credenciais, conta: conta.conta } });
    $("form-registro").reset();
    trocarAba(false);
    iniciarSessao(login);
    avisar(`Conta ${conta.conta} aberta com sucesso.`);
  });

  aoEnviar($("form-deposito"), async (dados) => {
    const resultado = await chamarApi("/transacoes/deposito", {
      metodo: "POST",
      corpo: { valor: lerValor(dados.get("valor")) },
    });
    $("form-deposito").reset();
    avisar(`${resultado.mensagem} Novo saldo: ${moeda.format(resultado.saldo_centavos / 100)}.`);
    atualizarExtrato();
  });

  aoEnviar($("form-transferencia"), async (dados) => {
    try {
      const resultado = await chamarApi("/transacoes/transferencia", {
        metodo: "POST",
        corpo: { conta_destino: dados.get("conta_destino"), valor: lerValor(dados.get("valor")) },
      });
      $("form-transferencia").reset();
      avisar(`${resultado.mensagem} Novo saldo: ${moeda.format(resultado.saldo_centavos / 100)}.`);
    } finally {
      // Transferências recusadas (422) também ficam registradas no extrato.
      if (sessao) atualizarExtrato();
    }
  });

  if (sessao) mostrarPainel();
  else mostrarAcesso();
}

configurar();
