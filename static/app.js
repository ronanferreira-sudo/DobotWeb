'use strict';

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Navegação entre Abas
// ---------------------------------------------------------------------------
function mudarAba(abaId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

  $(abaId).classList.add('active');
  if (abaId === 'abaControle') $('tabBtn1').classList.add('active');
  if (abaId === 'abaAdmin') $('tabBtn2').classList.add('active');
}

// ---------------------------------------------------------------------------
// Controle de Passo (Jog) — event passado como parâmetro explícito
// ---------------------------------------------------------------------------
let passoAtual = 10;

function setPasso(p, evt) {
  passoAtual = p;
  document.querySelectorAll('.btn-step').forEach(btn => btn.classList.remove('active'));
  if (evt && evt.target) {
    evt.target.classList.add('active');
  }
}

// ---------------------------------------------------------------------------
// Jog
// ---------------------------------------------------------------------------
async function moverJog(eixo) {
  try {
    const resp = await fetch('/jog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, eixo: eixo, passo: passoAtual })
    });
    const dados = await resp.json();
    if (dados.ok && dados.posicao) {
      $('posicao').textContent = dados.posicao.join(', ');
    } else if (!dados.ok) {
      alert(dados.erro || 'Erro ao movimentar robô.');
    }
  } catch (e) {
    alert('Erro de conexão ao enviar comando jog.');
  }
}

// ---------------------------------------------------------------------------
// Atuador
// ---------------------------------------------------------------------------
async function testarAtuador(tipo, estado) {
  try {
    const resp = await fetch('/atuador', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, tipo: tipo, estado: estado })
    });
    const dados = await resp.json();
    if (!dados.ok) alert(dados.erro || 'Erro ao acionar atuador.');
  } catch (e) {
    alert('Erro de conexão.');
  }
}

// ---------------------------------------------------------------------------
// Limpar Alarmes
// ---------------------------------------------------------------------------
async function limparAlarmesDoRobo() {
  try {
    const resp = await fetch('/limpar_alarmes', { method: 'POST' });
    const dados = await resp.json();
    if (dados.ok) {
      alert('Alarmes limpos com sucesso! O robô foi destravado.');
    } else {
      alert(dados.erro || 'Erro ao limpar alarmes.');
    }
  } catch (e) {
    alert('Erro de comunicação.');
  }
}

// ---------------------------------------------------------------------------
// Exemplos prontos
// ---------------------------------------------------------------------------
const EXEMPLOS = {
  ventosa: "# Exemplo: pegar e soltar com a VENTOSA\nvelocidade 200 200\nmover 200 0 50 0\nventosa on\nmover 200 0 0 0\nesperar 500\nmover 200 0 50 0\nmover 240 0 50 0\nmover 240 0 0 0\nventosa off\nmover 240 0 50 0",
  garra: "# Exemplo: pegar e soltar com a GARRA\nvelocidade 200 200\nmover 200 0 60 0\ngarra off\nmover 200 0 20 0\ngarra on\nesperar 500\nmover 200 0 60 0\nmover 250 0 60 0\nmover 250 0 20 0\ngarra off\nmover 250 0 60 0",
  desenhar: "# Exemplo: desenhar um quadrado com CANETA\nvelocidade 100 100\nmover 200 -40 30 0\nmover 200 -40 0 0\ndesenhar 240 -40\ndesenhar 240 40\ndesenhar 200 40\ndesenhar 200 -40\nmover 200 -40 30 0"
};

// ---------------------------------------------------------------------------
// Client ID persistente
// ---------------------------------------------------------------------------
function getClientId() {
  let id = localStorage.getItem('dobot_client_id');
  if (!id) {
    id = 'c_' + Math.random().toString(36).substring(2, 10) + Date.now().toString(36);
    localStorage.setItem('dobot_client_id', id);
  }
  return id;
}
const clientId = getClientId();

// ---------------------------------------------------------------------------
// Pontos A e B
// ---------------------------------------------------------------------------
let pontoA = null;
let pontoB = null;

// ---------------------------------------------------------------------------
// Editor: numeração de linhas
// ---------------------------------------------------------------------------
function atualizarNumeracaoLinhas() {
  const textarea = $('codigo');
  const lineNumbers = $('lineNumbers');
  const totalLinhas = textarea.value.split('\n').length;
  lineNumbers.textContent = Array.from({ length: totalLinhas }, (_, i) => i + 1).join('\n');
}

function normalizarECarregarCodigo(txt) {
  if (txt === undefined || txt === null) return;
  let str = txt.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  str = str.replace(/;\s*/g, '\n');
  const linhas = str.split('\n').map(l => l.trimEnd());
  $('codigo').value = linhas.join('\n');
  atualizarNumeracaoLinhas();
}

// ---------------------------------------------------------------------------
// Leitura de posição
// ---------------------------------------------------------------------------
async function lerPosicaoManual() {
  try {
    const resp = await fetch('/posicao');
    const dados = await resp.json();
    if (dados.ok && dados.posicao) {
      return dados.posicao;
    } else {
      alert(dados.erro || 'Não foi possível ler a posição. Verifique se o robô está conectado.');
      return null;
    }
  } catch (e) {
    alert('Erro de comunicação com o servidor.');
    return null;
  }
}

// ---------------------------------------------------------------------------
// Gerador de código Pick & Place A → B
// ---------------------------------------------------------------------------
$('btnLerPosicao').addEventListener('click', async () => {
  const pos = await lerPosicaoManual();
  if (pos) {
    $('posicao').textContent = pos.join(', ');
  }
});

$('btnCapturarA').addEventListener('click', async () => {
  const pos = await lerPosicaoManual();
  if (pos) {
    pontoA = pos;
    $('coordsPontoA').textContent = `X: ${pos[0]}, Y: ${pos[1]}, Z: ${pos[2]}, R: ${pos[3]}`;
  }
});

$('btnCapturarB').addEventListener('click', async () => {
  const pos = await lerPosicaoManual();
  if (pos) {
    pontoB = pos;
    $('coordsPontoB').textContent = `X: ${pos[0]}, Y: ${pos[1]}, Z: ${pos[2]}, R: ${pos[3]}`;
  }
});

$('btnGerarCodigoAB').addEventListener('click', () => {
  if (!pontoA || !pontoB) {
    alert('Por favor, capture o Ponto A e o Ponto B antes de gerar o código.');
    return;
  }
  const atuador = $('selectAtuador').value;
  const zSeguro = parseFloat($('alturaSeguraZ').value) || 50.0;

  const cmdOn  = atuador === 'ventosa' ? 'ventosa on'  : 'garra on';
  const cmdOff = atuador === 'ventosa' ? 'ventosa off' : 'garra off';
  const cmdPrep = atuador === 'garra' ? 'garra off\n' : '';

  const scriptGerado = `# Rotina Automática: Mover Objeto do Ponto A para o Ponto B
velocidade 200 200
${cmdPrep}# Mover para altura segura acima do Ponto A
mover ${pontoA[0]} ${pontoA[1]} ${zSeguro} ${pontoA[3]}
# Baixar para pegar no Ponto A
mover ${pontoA[0]} ${pontoA[1]} ${pontoA[2]} ${pontoA[3]}
${cmdOn}
esperar 500
# Elevar para altura segura
mover ${pontoA[0]} ${pontoA[1]} ${zSeguro} ${pontoA[3]}
# Mover para altura segura acima do Ponto B
mover ${pontoB[0]} ${pontoB[1]} ${zSeguro} ${pontoB[3]}
# Baixar para soltar no Ponto B
mover ${pontoB[0]} ${pontoB[1]} ${pontoB[2]} ${pontoB[3]}
${cmdOff}
esperar 500
# Retornar para altura segura
mover ${pontoB[0]} ${pontoB[1]} ${zSeguro} ${pontoB[3]}
home`;

  normalizarECarregarCodigo(scriptGerado);
  alert('Código de movimentação do Ponto A para o Ponto B gerado com sucesso!');
});

// ---------------------------------------------------------------------------
// Gerador de escrita de texto
// ---------------------------------------------------------------------------
$('btnGerarEscrita').addEventListener('click', async () => {
  const texto = ($('textoEscrever').value || '').trim();
  if (!texto) {
    alert('Digite um texto para escrever.');
    return;
  }
  const x = parseFloat($('escreverX').value) || 231.4;
  const y = parseFloat($('escreverY').value) || -48.3;
  const z = parseFloat($('escreverZ').value) || -43.5;
  const zInicioRaw = $('escreverZInicio').value;
  const zInicio = zInicioRaw === '' || zInicioRaw === null || zInicioRaw === undefined ? undefined : parseFloat(zInicioRaw);
  const r = parseFloat($('escreverR').value) || 0.0;
  const esp = parseFloat($('escreverEsp').value) || 4.0;

  const payload = { texto, x, y, z, espacamento: esp, r };
  if (Number.isFinite(zInicio)) payload.z_inicio = zInicio;

  try {
    const resp = await fetch('/escrever', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const dados = await resp.json();
    if (!dados.ok) {
      alert(dados.erro || 'Erro ao gerar escrita.');
      return;
    }
    normalizarECarregarCodigo(dados.codigo);
    alert('Código de escrita gerado! Verifique o editor antes de executar.');
  } catch (e) {
    alert('Erro de conexão ao gerar escrita.');
  }
});

// ---------------------------------------------------------------------------
// Scripts salvos
// ---------------------------------------------------------------------------
function carregarCodigosSalvosSelect() {
  const optgroup = $('optgroupSalvos');
  optgroup.innerHTML = '';
  const salvos = JSON.parse(localStorage.getItem('dobot_user_scripts') || '{}');
  const chaves = Object.keys(salvos);
  if (chaves.length === 0) {
    const opt = document.createElement('option');
    opt.disabled = true;
    opt.textContent = '(Nenhum código personalizado salvo)';
    optgroup.appendChild(opt);
  } else {
    chaves.forEach(nome => {
      const opt = document.createElement('option');
      opt.value = 'custom:' + nome;
      opt.textContent = '📜 ' + nome;
      optgroup.appendChild(opt);
    });
  }
}

function puxarCodigoSelecionado() {
  const val = $('savedScriptsSelect').value;
  if (!val) return;
  let texto = '';
  if (val.startsWith('custom:')) {
    const nome = val.replace('custom:', '');
    const salvos = JSON.parse(localStorage.getItem('dobot_user_scripts') || '{}');
    texto = salvos[nome] || '';
  } else if (EXEMPLOS[val]) {
    texto = EXEMPLOS[val];
  }
  normalizarECarregarCodigo(texto);
}

function salvarCodigoAtual() {
  const codigo = $('codigo').value.trim();
  if (!codigo) {
    alert('O campo de código está vazio.');
    return;
  }
  const nome = prompt('Digite um nome para identificar este código:');
  if (!nome) return;
  const salvos = JSON.parse(localStorage.getItem('dobot_user_scripts') || '{}');
  salvos[nome] = codigo;
  localStorage.setItem('dobot_user_scripts', JSON.stringify(salvos));
  carregarCodigosSalvosSelect();
  $('savedScriptsSelect').value = 'custom:' + nome;
  alert(`Código "${nome}" salvo com sucesso!`);
}

function baixarCodigoArquivo() {
  const codigo = $('codigo').value;
  const blob = new Blob([codigo], { type: 'text/plain;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'codigo_dobot.txt';
  link.click();
  URL.revokeObjectURL(link.href);
}

function abrirArquivoLocal(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(evt) {
    normalizarECarregarCodigo(evt.target.result);
  };
  reader.readAsText(file);
  e.target.value = '';
}

// ---------------------------------------------------------------------------
// Portas seriais
// ---------------------------------------------------------------------------
async function carregarPortas() {
  try {
    const resp = await fetch('/portas');
    const dados = await resp.json();
    const sel = $('portaSelect');
    sel.innerHTML = '';
    const auto = document.createElement('option');
    auto.value = '';
    auto.textContent = 'Automático (primeira porta)';
    sel.appendChild(auto);
    for (const p of dados.portas) {
      const opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      if (p === dados.atual) opt.selected = true;
      sel.appendChild(opt);
    }
  } catch (e) {}
}

// ---------------------------------------------------------------------------
// Permissões admin / usuário
// ---------------------------------------------------------------------------
const ELEMENTOS_CONTROLE = [
  'portaSelect','btnConectar','btnLerPosicao',
  'btnCapturarA','btnCapturarB','btnGerarCodigoAB',
  'btnGerarEscrita','textoEscrever','escreverX','escreverY','escreverZ','escreverZInicio','escreverR','escreverEsp',
  'btnExecutar','codigo','savedScriptsSelect','btnPuxarCodigo','btnFormatarLinhas',
  'btnSalvarCodigo','btnBaixarCodigo','inputAbrirArquivo'
];

function aplicarPermissoesAdmin(isAdmin, autorizado) {
  const adminElements = document.querySelectorAll('.admin-only');
  adminElements.forEach(el => {
    el.classList.toggle('admin-only', !isAdmin);
  });

  const tabBtn2 = $('tabBtn2');
  const abaAdmin = $('abaAdmin');

  if (!isAdmin) {
    if (tabBtn2) tabBtn2.style.display = 'none';
    if (abaAdmin) abaAdmin.classList.add('admin-only');
    mudarAba('abaControle');
  } else {
    if (tabBtn2) tabBtn2.style.display = '';
    if (abaAdmin) abaAdmin.classList.remove('admin-only');
  }

  ELEMENTOS_CONTROLE.forEach(id => {
    const el = $(id);
    if (!el) return;
    if (isAdmin || autorizado) {
      el.classList.remove('user-blocked');
      el.removeAttribute('disabled');
      el.removeAttribute('readonly');
    } else {
      el.classList.add('user-blocked');
      if (el.tagName === 'BUTTON' || el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        el.setAttribute('disabled', 'disabled');
      }
      if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
        el.setAttribute('readonly', 'readonly');
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Polling de status
// ---------------------------------------------------------------------------
async function atualizarStatus() {
  try {
    const resp = await fetch('/status?client_id=' + encodeURIComponent(clientId));
    const dados = await resp.json();

    aplicarPermissoesAdmin(!!(dados.seu_status && dados.seu_status.is_admin), !!(dados.seu_status && dados.seu_status.autorizado));

    // Atualiza Status do Braço
    const cx = $('conexao');
    if (dados.conectado) {
      cx.innerHTML = '<span class="dot on"></span>Conectado (' + (dados.porta || '?') + ')';
    } else {
      cx.innerHTML = '<span class="dot off"></span>Não conectado';
    }

    $('posicao').textContent = dados.posicao ? dados.posicao.join(', ') : '—';

    const ex = $('execucao');
    if (dados.executando) {
      ex.innerHTML = '<span class="dot run"></span>Executando…';
    } else {
      ex.innerHTML = '<span class="dot off"></span>Parado';
    }

    // Atualiza Monitor da Aba 2 (Código em Execução Agora)
    const codeBox = $('activeCodeBox');
    const labelSol = $('labelSolicitante');
    if (dados.executando && dados.job_atual) {
      labelSol.textContent = `Executando via IP: ${dados.job_atual.ip || 'Local'}`;
      codeBox.textContent = dados.job_atual.codigo || '// Sem código';
    } else {
      labelSol.textContent = 'Nenhuma execução ativa';
      codeBox.textContent = '// Nenhuma execução em andamento no momento.';
    }

    // Atualiza Log
    const log = $('log');
    log.innerHTML = '';
    for (const linha of dados.log) {
      const div = document.createElement('div');
      div.textContent = linha;
      log.appendChild(div);
    }
    if (dados.erro) {
      const div = document.createElement('div');
      div.className = 'err';
      div.textContent = 'ERRO: ' + dados.erro;
      log.appendChild(div);
    }
    log.scrollTop = log.scrollHeight;

    // Atualiza Status do Cliente Atual e Banner de Autorização
    const seuStatus = dados.seu_status || {};
    const btnExec = $('btnExecutar');
    const banner = $('authBanner');
    const statusText = $('authStatusText');
    const btnSolicitar = $('btnSolicitarInline');

    // Reabilitar o botão Executar somente após o polling confirmar autorização e sem execução
    if (seuStatus.autorizado && !dados.executando) {
      btnExec.disabled = false;
    } else if (!seuStatus.autorizado) {
      btnExec.disabled = true;
    }

    if (seuStatus.autorizado) {
      banner.className = 'auth-banner ok';
      statusText.textContent = '✅ Você está autorizado a executar comandos no robô.';
      btnSolicitar.style.display = 'none';
    } else if (seuStatus.solicitou) {
      banner.className = 'auth-banner warn';
      statusText.textContent = '⏳ Sua solicitação foi enviada. Aguardando aprovação do administrador do notebook...';
      btnSolicitar.style.display = 'none';
    } else {
      banner.className = 'auth-banner err';
      statusText.textContent = '⚠️ Devido ao número de conexões na porta 5000, você precisa de autorização para executar.';
      btnSolicitar.style.display = 'inline-block';
    }

    // Atualiza Lista de Pessoas Conectadas
    const clientes = dados.clientes || [];
    $('totalConectados').textContent = clientes.length + (clientes.length === 1 ? ' pessoa' : ' pessoas');

    const tbody = $('tabelaClientes');
    tbody.innerHTML = '';

    if (clientes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted); text-align:center;">Nenhuma conexão detectada.</td></tr>';
    } else {
      const souAdmin = seuStatus.is_admin;
      clientes.forEach(c => {
        const tr = document.createElement('tr');

        // Coluna Nome
        const tdNome = document.createElement('td');
        tdNome.textContent = c.nome || '—';
        tr.appendChild(tdNome);

        // Coluna IP & Badges
        const tdIp = document.createElement('td');
        tdIp.textContent = c.ip;
        if (c.is_you) {
          const b = document.createElement('span');
          b.className = 'badge badge-tag';
          b.textContent = 'Você';
          tdIp.appendChild(b);
        }
        if (c.is_admin) {
          const b = document.createElement('span');
          b.className = 'badge badge-tag';
          b.style.background = '#0284c7';
          b.textContent = 'Admin (Host)';
          tdIp.appendChild(b);
        }
        tr.appendChild(tdIp);

        // Coluna ID
        const tdId = document.createElement('td');
        tdId.style.fontFamily = 'monospace';
        tdId.textContent = c.id.substring(0, 12) + '…';
        tr.appendChild(tdId);

        // Coluna Status
        const tdStatus = document.createElement('td');
        if (c.autorizado) {
          tdStatus.innerHTML = '<span class="badge badge-ok">Autorizado</span>';
        } else if (c.solicitou) {
          tdStatus.innerHTML = '<span class="badge badge-warn">Aguardando Autorização</span>';
        } else {
          tdStatus.innerHTML = '<span class="badge badge-err">Não Autorizado</span>';
        }
        tr.appendChild(tdStatus);

        // Coluna Ações
        const tdAcoes = document.createElement('td');
        if (souAdmin && !c.is_admin) {
          if (c.autorizado) {
            const btnRev = document.createElement('button');
            btnRev.className = 'btn-revoke btn-sm';
            btnRev.textContent = 'Revogar Acesso';
            btnRev.onclick = () => alterarAutorizacao(c.id, false);
            tdAcoes.appendChild(btnRev);
          } else {
            const btnAut = document.createElement('button');
            btnAut.className = 'btn-auth btn-sm';
            btnAut.textContent = 'Autorizar Execução';
            btnAut.onclick = () => alterarAutorizacao(c.id, true);
            tdAcoes.appendChild(btnAut);
          }
        } else if (c.is_admin) {
          tdAcoes.textContent = 'Administrador do sistema';
          tdAcoes.style.color = 'var(--muted)';
        } else if (c.is_you && !c.autorizado) {
          if (!c.solicitou) {
            const btnSol = document.createElement('button');
            btnSol.className = 'btn-req btn-sm';
            btnSol.textContent = 'Solicitar Permissão';
            btnSol.onclick = solicitarAutorizacao;
            tdAcoes.appendChild(btnSol);
          } else {
            tdAcoes.textContent = 'Aguardando aprovação...';
            tdAcoes.style.color = 'var(--warn)';
          }
        } else {
          tdAcoes.textContent = '—';
          tdAcoes.style.color = 'var(--muted)';
        }
        tr.appendChild(tdAcoes);

        tbody.appendChild(tr);
      });
    }
  } catch (e) {}
}

// ---------------------------------------------------------------------------
// Autorização
// ---------------------------------------------------------------------------
async function solicitarAutorizacao() {
  const nome = prompt('Digite seu nome para identificação do administrador:');
  if (!nome || !nome.trim()) {
    alert('Informe um nome para solicitar autorização.');
    return;
  }
  try {
    const resp = await fetch('/solicitar_autorizacao', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, nome: nome.trim() })
    });
    const dados = await resp.json();
    if (!dados.ok) alert(dados.erro || 'Erro ao solicitar autorização.');
    atualizarStatus();
  } catch (e) {
    alert('Erro de conexão ao solicitar autorização.');
  }
}

async function alterarAutorizacao(targetId, autorizado) {
  try {
    const resp = await fetch('/autorizar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        admin_id: clientId,
        target_id: targetId,
        autorizado: autorizado
      })
    });
    const dados = await resp.json();
    if (!dados.ok) alert(dados.erro || 'Erro ao alterar autorização.');
    atualizarStatus();
  } catch (e) {
    alert('Erro de conexão ao alterar autorização.');
  }
}

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
const textareaCodigo = $('codigo');
textareaCodigo.addEventListener('input', atualizarNumeracaoLinhas);
textareaCodigo.addEventListener('scroll', () => {
  $('lineNumbers').scrollTop = textareaCodigo.scrollTop;
});

$('btnPuxarCodigo').addEventListener('click', puxarCodigoSelecionado);
$('btnFormatarLinhas').addEventListener('click', () => normalizarECarregarCodigo(textareaCodigo.value));
$('btnSalvarCodigo').addEventListener('click', salvarCodigoAtual);
$('btnBaixarCodigo').addEventListener('click', baixarCodigoArquivo);
$('inputAbrirArquivo').addEventListener('change', abrirArquivoLocal);
$('btnSolicitarInline').addEventListener('click', solicitarAutorizacao);

$('btnExecutar').addEventListener('click', async () => {
  const btnExec = $('btnExecutar');
  // Desabilitar imediatamente ao clicar para evitar duplo-envio
  btnExec.disabled = true;

  const codigo = $('codigo').value;
  try {
    const resp = await fetch('/executar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codigo, client_id: clientId })
    });
    const dados = await resp.json();
    if (!dados.ok) {
      alert(dados.erro || 'Erro ao executar.');
      // Reabilitar se falhou (ex: código vazio, não autorizado)
      btnExec.disabled = false;
    }
    // Se ok: permanece desabilitado até o próximo polling confirmar execução concluída
  } catch (e) {
    alert('Erro de conexão ao executar.');
    btnExec.disabled = false;
  }
});

$('btnParar').addEventListener('click', async () => {
  await fetch('/parar', { method: 'POST' });
});

$('btnConectar').addEventListener('click', async () => {
  const porta = $('portaSelect').value;
  const resp = await fetch('/conectar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ porta: porta || null })
  });
  const dados = await resp.json();
  alert(dados.ok ? 'Conectado em ' + dados.porta : (dados.erro || 'Erro ao conectar.'));
  carregarPortas();
});

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------
carregarPortas();
carregarCodigosSalvosSelect();
normalizarECarregarCodigo(textareaCodigo.value);
atualizarStatus();
setInterval(atualizarStatus, 1500);
