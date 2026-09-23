# Manual do Usuário — Controle Dobot (Acesso Não-Admin)

> **Guia rápido para operar o braço robótico Dobot Magician Lite sem ser administrador do sistema.**

---

## 1. Acesso ao Sistema

| Passo | Ação |
|---|---|
| 1 | Conecte-se à **mesma rede Wi-Fi** do notebook que controla o robô. |
| 2 | Abra um navegador no seu celular ou computador. |
| 3 | Digite o endereço IP do notebook com a porta 5000: |

```
http://192.168.1.22:5000
```

> Substitua `192.168.1.22` pelo IP real do notebook. Pergunte ao administrador se não souber qual é.

---

## 2. Tela de Controle

A tela que você vê tem três áreas principais:

| Área | Acesso | Detalhes |
|---|---|---|
| **Painel de Conexão** | Não | Você não pode conectar ou desconectar o robô. Só o admin pode. |
| **Editor de Código** | Sim | Digite comandos aqui. Você pode ver e editar. |
| **Saída do Terminal** | Sim | Mostra o log de execução. Você pode ver. |

Na barra superior, há abas para alternar entre funcionalidades:

| Aba | Permissão | Descrição |
|---|---|---|
| **Controle** | Todos | Jog, botões de movimento, garra, ventosa. |
| **Autorizações & Monitoramento** | Admin exclusivo | Gerencia solicitações de autorização e conexões. |

---

## 3. Como Solicitar Autorização

| Passo | Ação | Resultado |
|---|---|---|
| 1 | Na barra superior, aparecerá este banner | "Devido ao número de conexões na porta 5000, você precisa de autorização para executar." |
| 2 | Clique no botão **"Solicitar Autorização"** | O sistema registra sua solicitação. |
| 3 | Digite seu **nome** quando solicitado | Seu nome é enviado ao administrador. |
| 4 | Aguarde o administrador autorizar seu acesso | O botão "Executar" é habilitado. |

> Enquanto não for autorizado, todos os botões ficam desativados (cinza). Você pode digitar código, mas **não pode executar**.

---

## 4. Como Digitar e Executar um Código

### Passo a passo

| Passo | Ação | Botão | Resultado |
|---|---|---|---|
| 1 | Digite ou cole comandos no editor | — | Código aparece na área de texto |
| 2 | Clique em **"Executar"** | Botão verde com ícone de play | Comandos são enviados ao robô |
| 3 | Observe o terminal | — | Mostra cada comando sendo executado |
| 4 | Se precisar parar (emergência) | Botão vermelho **"Parar"** | Interrompe a execução imediatamente |

**Exemplo de código:**

```
velocidade 200 200
mover 200 0 60 0
garra off
mover 200 0 20 0
garra on
esperar 500
mover 200 0 60 0
mover 250 0 60 0
mover 250 0 20 0
garra off
mover 250 0 60 0
home
```

**Saída esperada no terminal:**

```
[1] velocidade 200 200
  -> velocidade=200 aceleração=200

[2] mover 200 0 60 0
  -> mover para x=200.0 y=0.0 z=60.0 r=0.0

...
```

---

## 5. Comandos Disponíveis

| Comando | Sintaxe | Descrição |
|---|---|---|
| `mover` | `mover x y z [r]` | Move para posição absoluta (mm). |
| `desenhar` | `desenhar x y [z] [r]` | Move mantendo a altura (para desenhar). |
| `garra` | `garra on\|off` | Fecha / abre a garra. |
| `ventosa` | `ventosa on\|off` | Liga / desliga a ventosa. |
| `esperar` | `esperar ms` | Pausa em milissegundos. |
| `velocidade` | `velocidade v [a]` | Velocidade / aceleração. |
| `home` | `home` | Volta para posição (200, 0, 100, 0). |
| `posicao` | `posicao` | Mostra posição atual no log. |

---

## 6. Exemplos Prontos

Na barra de ferramentas do editor, há um `<select>` com exemplos. Selecione e clique em **"Carregar"**:

| Exemplo | Ação | Resultado |
|---|---|---|
| Exemplo: Pegar com Ventosa | Carregar | Pega e solta usando a ventosa. |
| Exemplo: Pegar com Garra | Carregar | Pega e solta usando a garra. |
| Exemplo: Desenhar Quadrado | Carregar | Desenha um quadrado com a caneta. |

---

## 7. Funcionalidades que **não** estão disponíveis para você

| Funcionalidade | Motivo |
|---|---|
| Conectar ao robô | Só admin conecta. |
| Controle manual Jog (X+/X-/Y+/Y-/Z+/Z-, passo) | Só admin ou usuário **autorizado** move o braço. |
| Capturar Ponto A / Ponto B | Botões ocultos para não-admin. |
| Gerar Código Ponto A → B | Botão oculto para não-admin. |
| Gerar Escrita | Botão oculto para não-admin. |
| Aba "Autorizações & Monitoramento" | Só admin vê essa aba. |

---

## 8. Dicas Finais

| Ação | Permissão | Observação |
|---|---|---|
| Digitar e editar código | Sim | Pode digitar livremente |
| Executar código | Sim (com autorização) | Aguarde aprovação do admin |
| Parar uma execução | Sim | Pode parar a qualquer momento |
| Conectar ao robô | Não | Só admin |
| Mover manualmente (Jog) | Não | Só admin ou usuário autorizado |
| Capturar pontos | Não | Botões ocultos |
| Autorizar outros usuários | Não | Só admin |

> Pergunte ao administrador para **autorizar sua solicitação** se o banner ainda mostrar "Aguardando aprovação".

---

> **Dúvidas?** Consulte o administrador do sistema (quem controla o notebook conectado ao robô).
