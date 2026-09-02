import threading
import time

from flask import Flask, jsonify, render_template, request
import serial.tools.list_ports
from pydobot import Dobot
from pydobot.enums import PTPMode

app = Flask(__name__)


# Lock e dicionário global de conexões ativas (porta 5000)
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
            self.desconectar()
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
            except Exception:
                pass
            return porta

    def desconectar(self):
        if self._robot is not None:
            try:
                self._robot.close()
            except Exception:
                pass
            self._robot = None
            self._porta = None

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
job = {"executando": False, "log": [], "erro": None}


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
        robot.mover(200, 0, 0, 0)
        _log("  -> voltar para home (200, 0, 0, 0)")

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

def _registrar_ou_atualizar_cliente(client_id, ip):
    if not client_id:
        return None
    agora = time.time()
    is_admin = ip in ("127.0.0.1", "::1", "localhost")
    with clientes_lock:
        # Remover inativos (sem heartbeat por mais de 6 segundos)
        inativos = [cid for cid, info in clientes_conectados.items() if agora - info["last_seen"] > 6.0]
        for cid in inativos:
            del clientes_conectados[cid]

        if client_id not in clientes_conectados:
            clientes_conectados[client_id] = {
                "ip": ip,
                "last_seen": agora,
                "autorizado": is_admin,  # Host local entra pré-autorizado
                "solicitou": False,
                "is_admin": is_admin
            }
        else:
            c = clientes_conectados[client_id]
            c["last_seen"] = agora
            c["ip"] = ip
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
        "clientes": lista_clientes,
        "seu_status": {
            "autorizado": autorizado_atual,
            "solicitou": solicitou_atual,
            "is_admin": is_admin_atual
        }
    })


@app.route("/solicitar_autorizacao", methods=["POST"])
def solicitar_autorizacao():
    dados = request.get_json(silent=True) or {}
    client_id = dados.get("client_id")
    if not client_id:
        return jsonify({"ok": False, "erro": "client_id não fornecido"}), 400
    with clientes_lock:
        if client_id in clientes_conectados:
            clientes_conectados[client_id]["solicitou"] = True
            ip = clientes_conectados[client_id]["ip"]
            _log(f"  -> Usuário IP {ip} ({client_id[:8]}) solicitou autorização de execução.")
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

    with job_lock:
        job["executando"] = True
        job["log"] = []
        job["erro"] = None
    stop_flag.clear()

    _log(f"Iniciando execução por IP {ip} ({client_id[:8] if client_id else 'anon'})...")

    def run():
        try:
            _executar_script(codigo)
        except Exception as exc:
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
    return jsonify({"ok": True})



if __name__ == "__main__":
    if robot.auto_conectar():
        print(f"[OK] Dobot conectado na porta {robot.porta}")
    else:
        print("[AVISO] Dobot Magician Lite não encontrado. Use o botão 'Conectar' da interface.")

    print("Acesse a interface em:")
    print("  - Neste notebook:   http://127.0.0.1:5000")
    print("  - Outros aparelhos: http://<IP_DO_NOTEBOOK>:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)