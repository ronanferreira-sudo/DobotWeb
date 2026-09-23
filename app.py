import logging
import socket
import struct
import threading
import time

from flask import Flask, jsonify, render_template, request, send_from_directory
import serial.tools.list_ports
from pydobot import Dobot
from pydobot.enums import PTPMode
from pydobot.message import Message
from pydobot.enums.CommunicationProtocolIDs import CommunicationProtocolIDs
from pydobot.enums.ControlValues import ControlValues

# ---------------------------------------------------------------------------
# Logging estruturado com timestamp
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Tamanho máximo permitido para um script enviado via /executar (50 KB)
MAX_CODIGO_BYTES = 50 * 1024

# Timeout de inatividade de cliente (segundos sem heartbeat)
CLIENTE_TIMEOUT_S = 20.0

# Lock e dicionário global de conexões ativas
clientes_lock = threading.Lock()
clientes_conectados = {}


# ---------------------------------------------------------------------------
# Conexão com o Dobot Magician Lite (cabo USB / porta serial)
# ---------------------------------------------------------------------------


class RobotController:
    def __init__(self):
        self._robot = None
        self._porta = None
        self._lock = threading.Lock()
        # Última posição "comandada" (usada pelo comando `desenhar`).
        self._ultima = (200.0, 0.0, 0.0, 0.0)

    def listar_portas(self):
        """Portas seriais (COM) disponíveis no notebook."""
        try:
            return [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            return []

    @property
    def conectado(self):
        return self._robot is not None

    @property
    def porta(self):
        return self._porta

    @property
    def ultima_posicao(self):
        return self._ultima

    def conectar(self, porta=None):
        """Conecta na porta informada ou, se None, na primeira porta livre."""
        with self._lock:
            self._desconectar_interno()
            if porta is None:
                portas = self.listar_portas()
                if not portas:
                    raise ConnectionError(
                        "Nenhuma porta USB encontrada. Verifique se o Magician Lite "
                        "está ligado e conectado ao notebook."
                    )
                porta = portas[0]
            self._robot = Dobot(port=porta, verbose=False)
            self._porta = porta
            try:
                self._robot._set_queued_cmd_start_exec()
                pose = self._robot.pose()
                self._ultima = (pose[0], pose[1], pose[2], pose[3])
            except Exception:
                pass
            logger.info("Dobot conectado na porta %s", porta)
            return porta

    def _desconectar_interno(self):
        """Desconecta sem adquirir o lock (deve ser chamado de dentro do lock)."""
        if self._robot is not None:
            try:
                self._robot.close()
            except Exception:
                pass
            self._robot = None
            self._porta = None

    def desconectar(self):
        """Desconecta com segurança de thread."""
        with self._lock:
            self._desconectar_interno()

    def auto_conectar(self):
        try:
            self.conectar()
            return True
        except Exception:
            return False

    def _garantir_conexao(self):
        if self._robot is None:
            self.conectar()

    def posicao(self):
        """Posição real do robô: (x, y, z, r, j1, j2, j3, j4)."""
        self._garantir_conexao()
        return self._robot.pose()

    def parar(self):
        """Para o movimento e limpa a fila de comandos do robô."""
        with self._lock:
            if self._robot is None:
                return
            for metodo in ("_set_queued_cmd_stop_exec", "_set_queued_cmd_clear"):
                try:
                    getattr(self._robot, metodo)()
                except Exception:
                    pass

    def limpar_alarmes(self):
        """Limpa alarmes de limite de junta e destrava o robô."""
        with self._lock:
            if self._robot is None:
                return
            try:
                msg = Message()
                msg.id = CommunicationProtocolIDs.CLEAR_ALL_ALARMS_STATE
                msg.ctrl = ControlValues.ONE
                self._robot._send_command(msg)
                self._robot._set_queued_cmd_start_exec()
            except Exception:
                pass

    def home(self, wait=True):
        """Executa procedimento de Home para (200.0, 0.0, 100.0, 0.0)."""
        self._garantir_conexao()
        self.limpar_alarmes()
        try:
            self._robot._set_queued_cmd_start_exec()
        except Exception as exc:
            logger.warning("Falha ao iniciar fila antes do home: %s", exc)
        try:
            self._robot._set_ptp_cmd(200.0, 0.0, 100.0, 0.0, mode=PTPMode.MOVJ_XYZ, wait=wait)
        except Exception as exc:
            logger.error("Falha no movimento de home: %s", exc)
        self.limpar_alarmes()
        self._ultima = (200.0, 0.0, 100.0, 0.0)

    def mover(self, x, y, z, r=0.0, wait=True):
        self._garantir_conexao()
        self.limpar_alarmes()
        try:
            self._robot._set_queued_cmd_start_exec()
        except Exception:
            pass
        # Usar movimento articular PTP (MOVJ_XYZ) com wait=True para movimento físico real garantido
        self._robot._set_ptp_cmd(x, y, z, r, mode=PTPMode.MOVJ_XYZ, wait=wait)
        self._ultima = (x, y, z, r)

    def mover_linear(self, x, y, z, r=0.0, wait=True):
        self._garantir_conexao()
        self.limpar_alarmes()
        try:
            self._robot._set_queued_cmd_start_exec()
        except Exception:
            pass
        # Movimento linear (MOVL_XYZ) para escrita/desenho - mantém a caneta no papel em linha reta
        self._robot._set_ptp_cmd(x, y, z, r, mode=PTPMode.MOVL_XYZ, wait=wait)
        self._ultima = (x, y, z, r)

    def garra(self, ativar):
        self._garantir_conexao()
        self._robot.grip(ativar)
        time.sleep(0.3)

    def ventosa(self, ativar):
        self._garantir_conexao()
        self._robot.suck(ativar)
        time.sleep(0.3)

    def velocidade(self, v, a=None):
        self._garantir_conexao()
        self._robot.speed(v, v if a is None else a)

    def esperar(self, ms):
        self._garantir_conexao()
        self._robot.wait(ms)
        time.sleep(ms / 1000.0)


robot = RobotController()

# ---------------------------------------------------------------------------
# Estado da execução (apenas um script por vez)
# ---------------------------------------------------------------------------

exec_lock = threading.Lock()
stop_flag = threading.Event()
job_lock = threading.Lock()
job = {
    "executando": False,
    "log": [],
    "erro": None,
    "codigo": None,
    "solicitante_ip": None,
    "client_id": None
}


def _log(mensagem):
    with job_lock:
        job["log"].append(mensagem)


def _parse_booleano(texto):
    t = texto.strip().lower()
    if t in ("on", "ligar", "ligado", "fechar", "pegar", "ativar", "1", "true"):
        return True
    if t in ("off", "desligar", "desligado", "abrir", "soltar", "desativar", "0", "false"):
        return False
    raise ValueError(f"valor inválido: {texto!r} (use on/off, ligar/desligar, abrir/fechar ou 1/0)")

# ---------------------------------------------------------------------------
# Fonte vetorial: cada letra é uma lista de "traços".
# Cada traço é uma lista de pontos (col, linha) normalizados em grade 0..8 x 0..12.
# O braço desce ao PRIMEIRO ponto de cada traço e sobe ao ÚLTIMO.
# Coordenadas: col cresce para a direita (+X), linha cresce para cima (+Y).
# ---------------------------------------------------------------------------

FONTE_VETORIAL = {
    " ": [],  # espaço – sem traços
    "A": [
        [(4, 12), (0, 0)],                  # perna esquerda (descendo)
        [(4, 12), (8, 0)],                  # perna direita (descendo)
        [(2, 6), (6, 6)],                   # barra central
    ],
    "B": [
        [(0, 0), (0, 12), (6, 12), (8, 10), (8, 7.5), (6, 6), (0, 6)],
        [(6, 6), (8, 4.5), (8, 2), (6, 0), (0, 0)],
    ],
    "C": [
        [(8, 10), (6, 12), (2, 12), (0, 10), (0, 2), (2, 0), (6, 0), (8, 2)],
    ],
    "D": [
        [(0, 0), (0, 12), (5, 12), (8, 9), (8, 3), (5, 0), (0, 0)],
    ],
    "E": [
        [(8, 12), (0, 12), (0, 0), (8, 0)],
        [(0, 6), (6, 6)],
    ],
    "F": [
        [(0, 0), (0, 12), (8, 12)],
        [(0, 6), (6, 6)],
    ],
    "G": [
        [(8, 10), (6, 12), (2, 12), (0, 10), (0, 2), (2, 0), (8, 0), (8, 6), (4, 6)],
    ],
    "H": [
        [(0, 0), (0, 12)],
        [(8, 0), (8, 12)],
        [(0, 6), (8, 6)],
    ],
    "I": [
        [(2, 12), (6, 12)],
        [(4, 12), (4, 0)],
        [(2, 0), (6, 0)],
    ],
    "J": [
        [(1, 12), (7, 12)],
        [(5, 12), (5, 2), (3, 0), (1, 1)],
    ],
    "K": [
        [(0, 0), (0, 12)],
        [(0, 6), (8, 12)],
        [(0, 6), (8, 0)],
    ],
    "L": [
        [(0, 12), (0, 0), (8, 0)],
    ],
    "M": [
        [(0, 0), (0, 12), (4, 6), (8, 12), (8, 0)],
    ],
    "N": [
        [(0, 0), (0, 12), (8, 0), (8, 12)],
    ],
    "O": [
        [(0, 2), (2, 0), (6, 0), (8, 2), (8, 10), (6, 12), (2, 12), (0, 10), (0, 2)],
    ],
    "P": [
        [(0, 0), (0, 12), (6, 12), (8, 10), (8, 7), (6, 5), (0, 5)],
    ],
    "Q": [
        [(0, 2), (2, 0), (6, 0), (8, 2), (8, 10), (6, 12), (2, 12), (0, 10), (0, 2)],
        [(5, 3), (8, 0)],
    ],
    "R": [
        [(0, 0), (0, 12), (6, 12), (8, 10), (8, 7), (6, 5), (0, 5)],
        [(4, 5), (8, 0)],
    ],
    "S": [
        [(8, 12), (2, 12), (0, 10), (0, 8), (2, 6), (6, 6), (8, 4), (8, 2), (6, 0), (0, 0)],
    ],
    "T": [
        [(0, 12), (8, 12)],
        [(4, 12), (4, 0)],
    ],
    "U": [
        [(0, 12), (0, 2), (2, 0), (6, 0), (8, 2), (8, 12)],
    ],
    "V": [
        [(0, 12), (4, 0), (8, 12)],
    ],
    "W": [
        [(0, 12), (2, 0), (4, 6), (6, 0), (8, 12)],
    ],
    "X": [
        [(0, 12), (8, 0)],
        [(8, 12), (0, 0)],
    ],
    "Y": [
        [(0, 12), (4, 6)],
        [(8, 12), (4, 6), (4, 0)],
    ],
    "Z": [
        [(0, 12), (8, 12), (0, 0), (8, 0)],
    ],
    "0": [
        [(0, 2), (2, 0), (6, 0), (8, 2), (8, 10), (6, 12), (2, 12), (0, 10), (0, 2)],
        [(2, 2), (6, 10)],  # barra diagonal interna
    ],
    "1": [
        [(2, 10), (4, 12), (4, 0)],
        [(2, 0), (6, 0)],
    ],
    "2": [
        [(0, 10), (2, 12), (6, 12), (8, 10), (8, 7), (0, 0), (8, 0)],
    ],
    "3": [
        [(0, 10), (2, 12), (6, 12), (8, 10), (8, 7), (4, 6)],
        [(4, 6), (8, 5), (8, 2), (6, 0), (2, 0), (0, 2)],
    ],
    "4": [
        [(6, 0), (6, 12), (0, 5), (8, 5)],
    ],
    "5": [
        [(8, 12), (0, 12), (0, 7), (6, 7), (8, 5), (8, 2), (6, 0), (0, 0)],
    ],
    "6": [
        [(8, 10), (6, 12), (2, 12), (0, 10), (0, 2), (2, 0), (6, 0), (8, 2), (8, 6), (0, 6)],
    ],
    "7": [
        [(0, 12), (8, 12), (2, 0)],
    ],
    "8": [
        [(4, 6), (2, 12), (6, 12), (8, 10), (8, 8), (4, 6), (0, 4), (0, 2), (2, 0), (6, 0), (8, 2), (8, 4), (4, 6)],
    ],
    "9": [
        [(8, 2), (6, 0), (2, 0), (0, 2), (0, 6), (8, 6), (8, 10), (6, 12), (2, 12), (0, 10)],
    ],
    ".": [
        [(3, 0), (5, 0)],
        [(3, 1), (5, 1)],
    ],
    ",": [
        [(3, 1), (5, 1), (3, -1)],
    ],
    "!": [
        [(4, 4), (4, 12)],
        [(4, 0), (4, 2)],
    ],
    "?": [
        [(0, 9), (2, 12), (6, 12), (8, 9), (8, 7), (4, 5), (4, 3)],
        [(4, 0), (4, 1)],
    ],
    "-": [
        [(1, 6), (7, 6)],
    ],
    "_": [
        [(0, 0), (8, 0)],
    ],
    "+": [
        [(0, 6), (8, 6)],
        [(4, 2), (4, 10)],
    ],
    "/": [
        [(8, 0), (0, 12)],
    ],
    ":": [
        [(4, 8), (4, 9)],
        [(4, 3), (4, 4)],
    ],
    ";": [
        [(4, 8), (4, 9)],
        [(4, 3), (4, 2), (3, 0)],
    ],
    "(": [
        [(6, 12), (2, 8), (2, 4), (6, 0)],
    ],
    ")": [
        [(2, 12), (6, 8), (6, 4), (2, 0)],
    ],
    "@": [
        [(8, 5), (5, 5), (5, 8), (7, 8), (8, 7), (8, 2), (6, 0), (2, 0), (0, 2), (0, 10), (2, 12), (6, 12), (8, 10)],
    ],
    "#": [
        [(2, 0), (2, 12)],
        [(6, 0), (6, 12)],
        [(0, 4), (8, 4)],
        [(0, 8), (8, 8)],
    ],
    "*": [
        [(4, 4), (4, 10)],
        [(1, 5), (7, 9)],
        [(7, 5), (1, 9)],
    ],
    "=": [
        [(0, 4), (8, 4)],
        [(0, 8), (8, 8)],
    ],
    "&": [
        [(7, 2), (0, 7), (2, 10), (6, 10), (8, 7), (0, 0), (8, 0)],
    ],
    "$": [
        [(4, 13), (4, -1)],
        [(7, 10), (5, 12), (1, 12), (0, 10), (0, 8), (8, 4), (8, 2), (7, 0), (3, 0), (1, 2)],
    ],
    "%": [
        [(0, 12), (8, 0)],
        [(1, 11), (3, 11), (3, 9), (1, 9), (1, 11)],
        [(5, 3), (7, 3), (7, 1), (5, 1), (5, 3)],
    ],
}

CARACTERES_SUPORTADOS = "".join(sorted(FONTE_VETORIAL.keys()))


def _escrever_texto_em_comandos(texto, x_inicio, y_inicio, z_desenho, espacamento=1.5, altura_ponto=1.0, z_inicio=30.0, r=0.0):
    """
    Gera comandos de movimento para escrever 'texto' usando a fonte vetorial.

    Para cada traço de cada letra:
      1. Levanta a caneta (Z seguro) e move para o 1º ponto do traço
      2. Desce a caneta (Z papel) no 1º ponto
      3. Move linearmente (com caneta no papel) para cada ponto seguinte do traço
      4. Levanta a caneta ao final do traço

    Assim o braço NUNCA arrasta a caneta entre pontos não relacionados.

    Parâmetros
    ----------
    texto      : string a escrever
    x_inicio   : posição X inicial no robô (mm)
    y_inicio   : posição Y inicial no robô (mm) — base inferior das letras
    z_desenho  : Z quando a caneta toca o papel
    espacamento: escala (mm por unidade de grade). Grade: 12 u de altura, 8 u de largura.
    z_inicio   : Z seguro para deslocamentos sem desenho
    r          : rotação (graus)
    """
    comandos = []
    x_cursor = x_inicio
    z_aprox = z_inicio if z_inicio is not None else z_desenho + 15.0

    # Estabiliza o robô na posição inicial antes de começar a escrever
    comandos.append(f"# Mover para area de escrita e estabilizar")
    comandos.append(f"mover {x_inicio:.2f} {y_inicio:.2f} {z_aprox:.2f} {r:.2f}")
    comandos.append(f"esperar 500")

    for caractere in str(texto):
        ch = caractere.upper()
        tracos = FONTE_VETORIAL.get(ch)

        if tracos is None:
            # Caractere não suportado: avança como espaço
            x_cursor += espacamento * 6
            continue

        if not tracos:
            # Espaço: avança apenas
            x_cursor += espacamento * 5
            continue

        for traco in tracos:
            if len(traco) < 1:
                continue

            # 1. Levanta caneta e posiciona no 1º ponto do traço
            p0 = traco[0]
            px0 = x_cursor + p0[0] * espacamento
            py0 = y_inicio + p0[1] * espacamento
            comandos.append(f"mover {px0:.2f} {py0:.2f} {z_aprox:.2f} {r:.2f}")

            # 2. Desce a caneta no 1º ponto
            comandos.append(f"desenhar {px0:.2f} {py0:.2f} {z_desenho:.2f} {r:.2f}")
            comandos.append(f"esperar 200")

            # 3. Traça todos os pontos seguintes sem levantar
            for p in traco[1:]:
                px = x_cursor + p[0] * espacamento
                py = y_inicio + p[1] * espacamento
                comandos.append(f"desenhar {px:.2f} {py:.2f} {z_desenho:.2f} {r:.2f}")

            # 4. Levanta caneta no último ponto
            p_last = traco[-1]
            px_last = x_cursor + p_last[0] * espacamento
            py_last = y_inicio + p_last[1] * espacamento
            comandos.append(f"mover {px_last:.2f} {py_last:.2f} {z_aprox:.2f} {r:.2f}")

        # Avança o cursor para a próxima letra (largura 8 unidades + 2 de espaço entre letras)
        x_cursor += espacamento * 10

    return comandos



def _aplicar_comando(comando, args):
    if comando == "mover":
        if len(args) < 3:
            raise ValueError("uso: mover <x> <y> <z> [r]")
        x, y, z = float(args[0]), float(args[1]), float(args[2])
        r = float(args[3]) if len(args) >= 4 else 0.0
        robot.mover(x, y, z, r)
        _log(f"  -> mover para x={x} y={y} z={z} r={r}")

    elif comando == "desenhar":
        if len(args) < 2:
            raise ValueError("uso: desenhar <x> <y> [z] [r]")
        x, y = float(args[0]), float(args[1])
        z = float(args[2]) if len(args) >= 3 else robot.ultima_posicao[2]
        r = float(args[3]) if len(args) >= 4 else 0.0
        robot.mover_linear(x, y, z, r)
        _log(f"  -> desenhar até x={x} y={y} z={z} r={r}")

    elif comando == "escrever":
        if not args:
            raise ValueError("uso: escrever <texto> [x] [y] [z] [espaçamento] [z_inicio] [r]")
        texto = " ".join(args[:1]) if len(args) >= 1 else ""
        x = float(args[1]) if len(args) >= 2 else 160.0
        y = float(args[2]) if len(args) >= 3 else -40.0
        z = float(args[3]) if len(args) >= 4 else -43.5
        esp = float(args[4]) if len(args) >= 5 else 1.5
        z_inicio = float(args[5]) if len(args) >= 6 else None
        r = float(args[6]) if len(args) >= 7 else 0.0

        cmds = _escrever_texto_em_comandos(texto, x, y, z, espacamento=esp, z_inicio=z_inicio, r=r)
        if not cmds:
            raise ValueError("Nenhum comando gerado para o texto informado.")
        for cmd in cmds:
            partes = cmd.split()
            _aplicar_comando(partes[0], partes[1:])
        return

    elif comando == "garra":
        if not args:
            raise ValueError("uso: garra <on|off>")
        estado = _parse_booleano(args[0])
        robot.garra(estado)
        _log(f"  -> garra {'fechada' if estado else 'aberta'}")

    elif comando == "ventosa":
        if not args:
            raise ValueError("uso: ventosa <on|off>")
        estado = _parse_booleano(args[0])
        robot.ventosa(estado)
        _log(f"  -> ventosa {'ligada' if estado else 'desligada'}")

    elif comando == "velocidade":
        if not args:
            raise ValueError("uso: velocidade <v> [a]")
        v = float(args[0])
        a = float(args[1]) if len(args) >= 2 else v
        robot.velocidade(v, a)
        _log(f"  -> velocidade={v} aceleração={a}")

    elif comando == "esperar":
        if not args:
            raise ValueError("uso: esperar <milissegundos>")
        ms = int(float(args[0]))
        robot.esperar(ms)
        _log(f"  -> esperar {ms} ms")

    elif comando == "posicao":
        pose = robot.posicao()
        _log(f"  -> posição atual: x={pose[0]:.1f} y={pose[1]:.1f} z={pose[2]:.1f} r={pose[3]:.1f}")

    elif comando == "home":
        robot.home(wait=True)
        _log("  -> voltar para home (200, 0, 100, 0)")

    else:
        raise ValueError(f"comando desconhecido: {comando!r}")


def _executar_script(codigo):
    if robot.conectado:
        try:
            robot._robot._set_queued_cmd_start_exec()
        except Exception:
            pass
    linhas = codigo.splitlines()

    for numero, linha in enumerate(linhas, 1):
        if stop_flag.is_set():
            raise RuntimeError("Execução interrompida pelo usuário.")

        linha_limpa = linha.strip()
        if not linha_limpa or linha_limpa.startswith("#"):
            continue

        partes = linha_limpa.split()
        comando = partes[0].lower()
        args = partes[1:]

        _log(f"[{numero}] {linha_limpa}")
        try:
            _aplicar_comando(comando, args)
        except Exception as exc:
            raise RuntimeError(f"Erro na linha {numero} ({comando}): {exc}")

    if stop_flag.is_set():
        raise RuntimeError("Execução interrompida pelo usuário.")
    _log("Concluído. Comandos enviados para a fila do robô.")


# ---------------------------------------------------------------------------
# Funções de auxílio para conexões de clientes
# ---------------------------------------------------------------------------

def _is_admin_ip(ip):
    if not ip:
        return False
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        if ip == socket.gethostbyname(socket.gethostname()):
            return True
    except Exception:
        pass
    return False


def _registrar_ou_atualizar_cliente(client_id, ip, nome=None):
    if not client_id:
        return None
    agora = time.time()
    is_admin = _is_admin_ip(ip)
    with clientes_lock:
        # Remover inativos (sem heartbeat por mais de CLIENTE_TIMEOUT_S segundos)
        inativos = [
            cid for cid, info in clientes_conectados.items()
            if agora - info["last_seen"] > CLIENTE_TIMEOUT_S
        ]
        for cid in inativos:
            logger.info("Cliente inativo removido: %s", cid[:8])
            del clientes_conectados[cid]

        if client_id not in clientes_conectados:
            clientes_conectados[client_id] = {
                "ip": ip,
                "last_seen": agora,
                "autorizado": is_admin,  # Host local entra pré-autorizado
                "solicitou": False,
                "is_admin": is_admin,
                "nome": nome or ""
            }
        else:
            c = clientes_conectados[client_id]
            c["last_seen"] = agora
            c["ip"] = ip
            if nome:
                c["nome"] = nome
            if is_admin:
                c["is_admin"] = True
                c["autorizado"] = True
        return dict(clientes_conectados[client_id])


# ---------------------------------------------------------------------------
# Rotas HTTP
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manual")
def manual():
    return send_from_directory(".", "MANUAL_USUARIO.pdf", as_attachment=True)


def _get_local_ip():
    """Obtém o IP local da máquina na rede."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route("/server_ip")
def server_ip():
    return jsonify({"ip": _get_local_ip()})


@app.route("/status")
def status():
    client_id = request.args.get("client_id") or request.headers.get("X-Client-ID")
    ip = request.remote_addr
    cliente_atual = _registrar_ou_atualizar_cliente(client_id, ip)

    conectado = robot.conectado
    with job_lock:
        executando = job["executando"]
        log = list(job["log"])
        erro = job["erro"]
        job_atual = {
            "codigo": job["codigo"],
            "ip": job["solicitante_ip"],
            "client_id": job["client_id"]
        } if executando else None

    posicao = None
    if conectado and not executando:
        try:
            posicao = [round(v, 1) for v in robot.posicao()[:4]]
        except Exception:
            posicao = None

    with clientes_lock:
        lista_clientes = [
            {
                "id": cid,
                "ip": info["ip"],
                "nome": info.get("nome", ""),
                "autorizado": info["autorizado"],
                "solicitou": info["solicitou"],
                "is_admin": info["is_admin"],
                "is_you": (cid == client_id)
            }
            for cid, info in clientes_conectados.items()
        ]

    autorizado_atual = cliente_atual["autorizado"] if cliente_atual else False
    solicitou_atual = cliente_atual["solicitou"] if cliente_atual else False
    is_admin_atual = cliente_atual["is_admin"] if cliente_atual else False

    return jsonify({
        "conectado": conectado,
        "porta": robot.porta,
        "executando": executando,
        "erro": erro,
        "posicao": posicao,
        "log": log,
        "job_atual": job_atual,
        "clientes": lista_clientes,
        "seu_status": {
            "autorizado": autorizado_atual,
            "solicitou": solicitou_atual,
            "is_admin": is_admin_atual
        }
    })


@app.route("/posicao")
def obter_posicao():
    if not robot.conectado:
        return jsonify({"ok": False, "erro": "Dobot não conectado."}), 400
    try:
        pose = [round(v, 1) for v in robot.posicao()[:4]]
        return jsonify({"ok": True, "posicao": pose})
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/jog", methods=["POST"])
def jog():
    if not robot.conectado:
        return jsonify({"ok": False, "erro": "Dobot não conectado."}), 400

    # Bloquear jog manual enquanto um script estiver em execução
    with job_lock:
        if job["executando"]:
            return jsonify({"ok": False, "erro": "Não é possível usar o jog enquanto um script está em execução."}), 409

    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = _is_admin_ip(ip)

    with clientes_lock:
        cliente = clientes_conectados.get(client_id)
        autorizado = (cliente and cliente.get("autorizado")) or is_admin

    if not autorizado:
        return jsonify({"ok": False, "erro": "Movimentação não autorizada pelo administrador."}), 403

    eixo = (dados.get("eixo") or "").lower().strip()
    passo = float(dados.get("passo", 10.0))

    try:
        # Obter a posição física real para garantir sincronia absoluta com os motores
        try:
            pose = robot.posicao()[:4]
            x, y, z, r = pose[0], pose[1], pose[2], pose[3]
        except Exception:
            atual = robot.ultima_posicao
            x, y, z, r = atual[0], atual[1], atual[2], atual[3]

        if eixo == "x+":   x += passo
        elif eixo == "x-": x -= passo
        elif eixo == "y+": y += passo
        elif eixo == "y-": y -= passo
        elif eixo == "z+": z += passo
        elif eixo == "z-": z -= passo
        elif eixo == "r+": r += passo
        elif eixo == "r-": r -= passo
        elif eixo == "home":
            robot.home(wait=False)
            return jsonify({"ok": True, "posicao": [200.0, 0.0, 100.0, 0.0]})
        else:
            return jsonify({"ok": False, "erro": f"Eixo inválido: {eixo}"}), 400

        robot.mover(x, y, z, r, wait=False)
        nova_pos = [round(x, 1), round(y, 1), round(z, 1), round(r, 1)]
        return jsonify({"ok": True, "posicao": nova_pos})

    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/limpar_alarmes", methods=["POST"])
def limpar_alarmes():
    if not robot.conectado:
        return jsonify({"ok": False, "erro": "Dobot não conectado."}), 400

    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = _is_admin_ip(ip)

    with clientes_lock:
        cliente = clientes_conectados.get(client_id)
        autorizado = (cliente and cliente.get("autorizado")) or is_admin

    if not autorizado:
        return jsonify({"ok": False, "erro": "Ação não autorizada pelo administrador."}), 403

    try:
        robot.limpar_alarmes()
        _log("  -> Alarmes do robô limpos e motores destravados.")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/atuador", methods=["POST"])
def atuador():

    if not robot.conectado:
        return jsonify({"ok": False, "erro": "Dobot não conectado."}), 400

    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = _is_admin_ip(ip)

    with clientes_lock:
        cliente = clientes_conectados.get(client_id)
        autorizado = (cliente and cliente.get("autorizado")) or is_admin

    if not autorizado:
        return jsonify({"ok": False, "erro": "Ação não autorizada."}), 403

    tipo = dados.get("tipo")
    estado = bool(dados.get("estado"))

    try:
        if tipo == "ventosa":
            robot.ventosa(estado)
        elif tipo == "garra":
            robot.garra(estado)
        else:
            return jsonify({"ok": False, "erro": "Tipo de atuador inválido"}), 400
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/solicitar_autorizacao", methods=["POST"])
def solicitar_autorizacao():
    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    nome = (dados.get("nome") or "").strip()
    if not client_id:
        return jsonify({"ok": False, "erro": "client_id não fornecido"}), 400
    with clientes_lock:
        if client_id in clientes_conectados:
            clientes_conectados[client_id]["solicitou"] = True
            if nome:
                clientes_conectados[client_id]["nome"] = nome
            ip = clientes_conectados[client_id]["ip"]
            nome_exibido = clientes_conectados[client_id].get("nome") or "Sem nome"
            _log(f"  -> Usuário {nome_exibido} IP {ip} ({client_id[:8]}) solicitou autorização de execução.")
            return jsonify({"ok": True})
        return jsonify({"ok": False, "erro": "Cliente não encontrado"}), 404


@app.route("/autorizar", methods=["POST"])
def autorizar():
    dados = request.get_json(silent=True) or {}
    admin_id = dados.get("admin_id")
    target_id = dados.get("target_id")
    autorizar_flag = bool(dados.get("autorizado", True))
    ip = request.remote_addr

    is_admin = _is_admin_ip(ip)
    with clientes_lock:
        if admin_id in clientes_conectados and clientes_conectados[admin_id].get("is_admin"):
            is_admin = True

        if not is_admin:
            return jsonify({"ok": False, "erro": "Apenas o administrador do notebook pode autorizar ou revogar."}), 403

        if target_id in clientes_conectados:
            clientes_conectados[target_id]["autorizado"] = autorizar_flag
            clientes_conectados[target_id]["solicitou"] = False
            estado_txt = "autorizado" if autorizar_flag else "revogado"
            _log(f"  -> Conexão IP {clientes_conectados[target_id]['ip']} ({target_id[:8]}) foi {estado_txt}.")
            return jsonify({"ok": True})
        return jsonify({"ok": False, "erro": "Cliente alvo não encontrado"}), 404


@app.route("/portas")
def portas():
    return jsonify({"portas": robot.listar_portas(), "atual": robot.porta})


@app.route("/conectar", methods=["POST"])
def conectar():
    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = _is_admin_ip(ip)

    with clientes_lock:
        if client_id in clientes_conectados and clientes_conectados[client_id].get("is_admin"):
            is_admin = True

    if not is_admin:
        return jsonify({"ok": False, "erro": "Apenas o administrador do notebook pode conectar ou trocar a porta serial."}), 403

    porta = dados.get("porta") or None
    try:
        escolhida = robot.conectar(porta)
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500
    return jsonify({"ok": True, "porta": escolhida})


@app.route("/escrever", methods=["POST"])
def escrever():
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    x = float(dados.get("x", 160.0))
    y = float(dados.get("y", -40.0))
    z = float(dados.get("z", 0.0))
    esp = float(dados.get("espacamento", 1.5))
    z_inicio = dados.get("z_inicio")
    z_inicio = float(z_inicio) if z_inicio is not None else 30.0
    r = float(dados.get("r", 0.0))

    if not texto:
        return jsonify({"ok": False, "erro": "Texto vazio."}), 400

    try:
        cmds = _escrever_texto_em_comandos(texto, x, y, z, espacamento=esp, z_inicio=z_inicio, r=r)
        codigo = "\n".join(cmds)
        return jsonify({"ok": True, "codigo": codigo})
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/executar", methods=["POST"])
def executar():
    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = _is_admin_ip(ip)

    with clientes_lock:
        cliente = clientes_conectados.get(client_id)
        if not cliente and client_id:
            cliente = _registrar_ou_atualizar_cliente(client_id, ip)

        autorizado = (cliente and cliente.get("autorizado")) or is_admin

    if not autorizado:
        return jsonify({
            "ok": False,
            "erro": "Execução não autorizada! Solicite autorização ao administrador no painel."
        }), 403

    if not exec_lock.acquire(blocking=False):
        return jsonify({"ok": False, "erro": "Já existe uma execução em andamento."}), 409

    codigo = (dados.get("codigo") or "").strip()
    if not codigo:
        exec_lock.release()
        return jsonify({"ok": False, "erro": "O código está vazio."}), 400

    # Limitar tamanho do código para evitar abuso
    if len(codigo.encode("utf-8")) > MAX_CODIGO_BYTES:
        exec_lock.release()
        return jsonify({"ok": False, "erro": f"Código muito grande (máximo {MAX_CODIGO_BYTES // 1024} KB)."}), 413

    with job_lock:
        job["executando"] = True
        job["log"] = []
        job["erro"] = None
        job["codigo"] = codigo
        job["solicitante_ip"] = ip
        job["client_id"] = client_id
    stop_flag.clear()

    _log(f"Iniciando execução por IP {ip} ({client_id[:8] if client_id else 'anon'})...")
    logger.info("Execução iniciada por IP %s client=%s", ip, client_id[:8] if client_id else "anon")

    def run():
        try:
            _executar_script(codigo)
        except Exception as exc:
            logger.error("Erro na execução: %s", exc)
            with job_lock:
                job["erro"] = str(exc)
        finally:
            with job_lock:
                job["executando"] = False
            exec_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "status": "iniciado"})


@app.route("/parar", methods=["POST"])
def parar():
    stop_flag.set()
    try:
        robot.parar()
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500
    _log("Parada de emergência acionada.")
    logger.warning("Parada de emergência acionada.")
    return jsonify({"ok": True})


if __name__ == "__main__":
    if robot.auto_conectar():
        logger.info("Dobot conectado na porta %s", robot.porta)
    else:
        logger.warning("Dobot Magician Lite não encontrado. Use o botão 'Conectar' da interface.")

    print("Acesse a interface em:")
    print("  - Neste notebook:   http://127.0.0.1:5000")
    print("  - Outros aparelhos: http://<IP_DO_NOTEBOOK>:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
