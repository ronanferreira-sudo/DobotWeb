# DobotWeb — Controle remoto do Dobot Magician Lite pela rede

Este projeto transforma o seu notebook em um **servidor** do braço robótico
**Dobot Magician Lite**. O notebook fica ligado ao braço por **cabo USB** e,
através de um servidor web (Flask), qualquer outra pessoa na mesma rede pode
acessar uma página e **enviar um código completo** para o robô executar
(pegar com a garra, usar a ventosa ou desenhar).

## Arquitetura

```
[Dobot Magician Lite] --USB--> [Seu notebook (Flask + pydobot)] <--Wi-Fi/Rede--> [Outra pessoa]
```

## Requisitos

- Python 3
- Dobot Magician Lite ligado e conectado ao notebook via cabo USB

## Instalação

No Windows (PowerShell), dentro da pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Executando o servidor

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

O terminal mostra algo como:

```
[OK] Dobot conectado na porta COM3
Acesse a interface em:
  - Neste notebook:   http://127.0.0.1:5000
  - Outros aparelhos: http://<IP_DO_NOTEBOOK>:5000
```

## Como a outra pessoa acessa

1. Descubra o IP do notebook. No terminal do notebook, rode:

   ```powershell
   ipconfig
   ```

   Procure por **"Endereço IPv4"** (exemplo: `192.168.0.15`).

2. A outra pessoa (no mesmo Wi-Fi) abre no navegador:

   ```
   http://192.168.0.15:5000
   ```

3. Ela escreve (ou cola) o código e clica em **Executar**.

> **Importante:**
> - Os dois aparelhos precisam estar na **mesma rede**.
> - Na primeira vez, o **Firewall do Windows** pode perguntar se deseja liberar
>   o Python — marque **Permitir acesso** (redes privadas).

## Linguagem de código (uma instrução por linha)

| Comando | Descrição | Exemplo |
|---------|-----------|---------|
| `mover x y z [r]` | Move para posição absoluta em mm | `mover 200 0 50 0` |
| `desenhar x y [z]` | Move mantendo a altura atual (para desenhar) | `desenhar 220 60` |
| `garra on\|off` | Fecha/abre a garra | `garra on` |
| `ventosa on\|off` | Liga/desliga a ventosa | `ventosa off` |
| `esperar ms` | Pausa em milissegundos | `esperar 500` |
| `velocidade v [a]` | Velocidade/aceleração | `velocidade 200 200` |
| `home` | Volta para a posição (200, 0, 0, 0) | `home` |
| `posicao` | Mostra a posição atual no log | `posicao` |

- Linhas que começam com `#` são **comentários** e são ignoradas.
- `on`/`off` também aceitam: `ligar`/`desligar`, `abrir`/`fechar`, `pegar`/`soltar`, `1`/`0`.

### Exemplos

**Pegar e soltar com a ventosa:**

```
velocidade 200 200
mover 200 0 50 0
ventosa on
mover 200 0 0 0
esperar 500
mover 200 0 50 0
mover 240 0 50 0
mover 240 0 0 0
ventosa off
mover 240 0 50 0
```

**Pegar e soltar com a garra:**

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
```

**Desenhar um quadrado (com caneta):**

```
velocidade 100 100
mover 200 -40 30 0
mover 200 -40 0 0
desenhar 240 -40
desenhar 240 40
desenhar 200 40
desenhar 200 -40
mover 200 -40 30 0
```

> Ajuste as coordenadas conforme o objeto e a caneta. Os valores estão em
> **milímetros** a partir da base do robô.

## Observações de segurança

- O botão **"Parar (emergência)"** interrompe o movimento e limpa a fila.
- Apenas **um código por vez** é executado.
- O servidor usa `debug=False` (já configurado) para evitar reconexões
  duplicadas da porta serial.
