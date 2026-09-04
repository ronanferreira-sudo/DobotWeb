import logging
import struct
import threading
import time

from flask import Flask, jsonify, render_template, request
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
        except Exception:
            pass

        # Configurar parâmetros de Home no microcontrolador Dobot (ID 30)
        try:
            msg = Message()
            msg.id = CommunicationProtocolIDs.SET_GET_HOME_PARAMS
            msg.ctrl = ControlValues.THREE
            msg.params = bytearray(struct.pack('ffff', 200.0, 0.0, 100.0, 0.0))
            self._robot._send_command(msg)
        except Exception:
            pass

        # Disparar o comando SET_HOME_CMD (ID 31)
        try:
            msg2 = Message()
            msg2.id = CommunicationProtocolIDs.SET_HOME_CMD
            msg2.ctrl = ControlValues.THREE
            msg2.params = bytearray(struct.pack('I', 0))
            self._robot._send_command(msg2)
        except Exception:
            pass

        # Enviar comando de movimento para (200, 0, 100, 0)
        try:
            self.mover(200.0, 0.0, 100.0, 0.0, wait=wait)
        except Exception:
            pass
        self._ultima = (200.0, 0.0, 100.0, 0.0)

    def mover(self, x, y, z, r=0.0, wait=True):
        self._garantir_conexao()
        try:
            self._robot._set_queued_cmd_start_exec()
        except Exception:
            pass
        # Usar movimento articular PTP (MOVJ_XYZ) com wait=True para movimento físico real garantido
        self._robot._set_ptp_cmd(x, y, z, r, mode=PTPMode.MOVJ_XYZ, wait=wait)
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

FONTE_5X7 = {
    " ": [
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
    ],
    "A": [
        "  #  ",
        " # # ",
        "#   #",
        "#####",
        "#   #",
        "#   #",
        "#   #",
    ],
    "B": [
        "#### ",
        "#   #",
        "#   #",
        "#### ",
        "#   #",
        "#   #",
        "#### ",
    ],
    "C": [
        " ####",
        "#    ",
        "#    ",
        "#    ",
        "#    ",
        "#    ",
        " ####",
    ],
    "D": [
        "#### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#### ",
    ],
    "E": [
        "#####",
        "#    ",
        "#    ",
        "#### ",
        "#    ",
        "#    ",
        "#####",
    ],
    "F": [
        "#####",
        "#    ",
        "#    ",
        "#### ",
        "#    ",
        "#    ",
        "#    ",
    ],
    "G": [
        " ####",
        "#    ",
        "#    ",
        "#  ##",
        "#   #",
        "#   #",
        " ### ",
    ],
    "H": [
        "#   #",
        "#   #",
        "#   #",
        "#####",
        "#   #",
        "#   #",
        "#   #",
    ],
    "I": [
        "#####",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "#####",
    ],
    "J": [
        "    #",
        "    #",
        "    #",
        "    #",
        "#   #",
        "#   #",
        " ### ",
    ],
    "K": [
        "#   #",
        "#  # ",
        "# #  ",
        "##   ",
        "# #  ",
        "#  # ",
        "#   #",
    ],
    "L": [
        "#    ",
        "#    ",
        "#    ",
        "#    ",
        "#    ",
        "#    ",
        "#####",
    ],
    "M": [
        "#   #",
        "## ##",
        "# # #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
    ],
    "N": [
        "#   #",
        "##  #",
        "# # #",
        "#  ##",
        "#   #",
        "#   #",
        "#   #",
    ],
    "O": [
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ],
    "P": [
        "#### ",
        "#   #",
        "#   #",
        "#### ",
        "#    ",
        "#    ",
        "#    ",
    ],
    "Q": [
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "# # #",
        "#  # ",
        " ## #",
    ],
    "R": [
        "#### ",
        "#   #",
        "#   #",
        "#### ",
        "# #  ",
        "#  # ",
        "#   #",
    ],
    "S": [
        " ####",
        "#    ",
        "#    ",
        " ### ",
        "    #",
        "    #",
        "#### ",
    ],
    "T": [
        "#####",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
    ],
    "U": [
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ],
    "V": [
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " # # ",
        " # # ",
        "  #  ",
    ],
    "W": [
        "#   #",
        "#   #",
        "#   #",
        "# # #",
        "# # #",
        " # # ",
        " # # ",
    ],
    "X": [
        "#   #",
        "#   #",
        " # # ",
        "  #  ",
        " # # ",
        "#   #",
        "#   #",
    ],
    "Y": [
        "#   #",
        "#   #",
        " # # ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
    ],
    "Z": [
        "#####",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "#####",
    ],
    "0": [
        " ### ",
        "#   #",
        "#  ##",
        "# # #",
        "##  #",
        "#   #",
        " ### ",
    ],
    "1": [
        "  #  ",
        " ##  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        " ### ",
    ],
    "2": [
        " ### ",
        "#   #",
        "    #",
        "  ## ",
        " #   ",
        "#    ",
        "#####",
    ],
    "3": [
        " ### ",
        "#   #",
        "    #",
        "  ## ",
        "    #",
        "#   #",
        " ### ",
    ],
    "4": [
        "#   #",
        "#   #",
        "#   #",
        "#####",
        "    #",
        "    #",
        "    #",
    ],
    "5": [
        "#####",
        "#    ",
        "#    ",
        "#### ",
        "    #",
        "    #",
        "#### ",
    ],
    "6": [
        " ### ",
        "#    ",
        "#    ",
        "#### ",
        "#   #",
        "#   #",
        " ### ",
    ],
    "7": [
        "#####",
        "    #",
        "   # ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
    ],
    "8": [
        " ### ",
        "#   #",
        "#   #",
        " ### ",
        "#   #",
        "#   #",
        " ### ",
    ],
    "9": [
        " ### ",
        "#   #",
        "#   #",
        " ####",
        "    #",
        "    #",
        " ### ",
    ],
    ".": [
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "  #  ",
        "  #  ",
    ],
    ",": [
        "     ",
        "     ",
        "     ",
        "     ",
        "  #  ",
        "  #  ",
        " #   ",
    ],
    "!": [
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "     ",
        "  #  ",
    ],
    "?": [
        " ### ",
        "#   #",
        "    #",
        "  ## ",
        "  #  ",
        "     ",
        "  #  ",
    ],
    "-": [
        "     ",
        "     ",
        "#####",
        "     ",
        "#####",
        "     ",
        "     ",
    ],
    "_": [
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "     ",
        "#####",
    ],
    "+": [
        "     ",
        "  #  ",
        "  #  ",
        "#####",
        "  #  ",
        "  #  ",
        "     ",
    ],
    "/": [
        "    #",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "#    ",
    ],
    "(": [
        "  #  ",
        " #   ",
        "#    ",
        "#    ",
        "#    ",
        " #   ",
        "  #  ",
    ],
    ")": [
        "  #  ",
        "   # ",
        "    #",
        "    #",
        "    #",
        "   # ",
        "  #  ",
    ],
    ":": [
        "     ",
        "  #  ",
        "  #  ",
        "     ",
        "  #  ",
        "  #  ",
        "     ",
    ],
    ";": [
        "     ",
        "  #  ",
        "  #  ",
        "     ",
        "  #  ",
        "  #  ",
        " #   ",
    ],
    "*": [
        "     ",
        "# # #",
        " ### ",
        "#####",
        " ### ",
        "# # #",
        "     ",
    ],
    "=": [
        "     ",
        "#####",
        "     ",
        "#####",
        "     ",
        "#####",
        "     ",
    ],
    "@": [
        " ### ",
        "#   #",
        "# ###",
        "# # #",
        "# ###",
        "#    ",
        " ### ",
    ],
    "#": [
        " # # ",
        " # # ",
        "#####",
        " # # ",
        "#####",
        " # # ",
        " # # ",
    ],
    "$": [
        "  #  ",
        " ####",
        "#    ",
        " ### ",
        "    #",
        "#### ",
        "  #  ",
    ],
    "%": [
        "#    ",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "    #",
    ],
    "&": [
        " ### ",
        "#   #",
        "#    ",
        " ##  ",
        "#  # ",
        "#  # ",
        " ## #",
    ],
}

CARACTERES_SUPORTADOS = "".join(sorted(FONTE_5X7.keys()))


def _escrever_texto_em_comandos(texto, x_inicio, y_inicio, z_desenho, espacamento=4.0, altura_ponto=1.0):
    comandos = []
    x = x_inicio
    for caractere in str(texto):
        ch = caractere.upper()
        padrao = FONTE_5X7.get(ch)
        if not padrao:
            comandos.append(f"desenhar {x:.1f} {y_inicio:.1f} {z_desenho:.1f}")
            x += espacamento * 0.6
            continue

        linhas_ativas = []
        for linha_idx, linha in enumerate(padrao):
            pontos_na_linha = []
            for col_idx, ch in enumerate(linha):
                if ch == "#":
                    pontos_na_linha.append((x + col_idx * espacamento, y_inicio - linha_idx * espacamento))
            if pontos_na_linha:
                linhas_ativas.append(pontos_na_linha)

        if linhas_ativas:
            comandos.append(f"mover {linhas_ativas[0][0][0]:.1f} {linhas_ativas[0][0][1]:.1f} {z_desenho + altura_ponto:.1f}")
            for pontos in linhas_ativas:
                for px, py in pontos:
                    comandos.append(f"desenhar {px:.1f} {py:.1f} {z_desenho:.1f}")

        x += espacamento * 5 + espacamento * 0.8
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
            raise ValueError("uso: desenhar <x> <y> [z]")
        x, y = float(args[0]), float(args[1])
        _, _, uz, ur = robot.ultima_posicao
        z = float(args[2]) if len(args) >= 3 else uz
        robot.mover(x, y, z, ur)
        _log(f"  -> desenhar até x={x} y={y} z={z}")

    elif comando == "escrever":
        if not args:
            raise ValueError("uso: escrever <texto> [x] [y] [z] [espaçamento]")
        texto = " ".join(args[:1]) if len(args) >= 1 else ""
        x = float(args[1]) if len(args) >= 2 else 180.0
        y = float(args[2]) if len(args) >= 3 else -40.0
        z = float(args[3]) if len(args) >= 4 else -10.0
        esp = float(args[4]) if len(args) >= 5 else 4.0

        cmds = _escrever_texto_em_comandos(texto, x, y, z, espacamento=esp)
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

def _registrar_ou_atualizar_cliente(client_id, ip, nome=None):
    if not client_id:
        return None
    agora = time.time()
    is_admin = ip in ("127.0.0.1", "::1", "localhost")
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
    is_admin = ip in ("127.0.0.1", "::1", "localhost")

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
    is_admin = ip in ("127.0.0.1", "::1", "localhost")

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

    is_admin = ip in ("127.0.0.1", "::1", "localhost")
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
    x = float(dados.get("x", 180.0))
    y = float(dados.get("y", -40.0))
    z = float(dados.get("z", -10.0))
    esp = float(dados.get("espacamento", 4.0))

    if not texto:
        return jsonify({"ok": False, "erro": "Texto vazio."}), 400

    try:
        cmds = _escrever_texto_em_comandos(texto, x, y, z, espacamento=esp)
        codigo = "\n".join(cmds)
        return jsonify({"ok": True, "codigo": codigo})
    except Exception as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 500


@app.route("/executar", methods=["POST"])
def executar():
    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    ip = request.remote_addr
    is_admin = ip in ("127.0.0.1", "::1", "localhost")

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