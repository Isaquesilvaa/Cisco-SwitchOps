from flask import (

    Flask,

    render_template,

    request,

    session,

    redirect,

    url_for,

    jsonify,

    Response,

    stream_with_context

)

from netmiko import ConnectHandler, redispatch

from concurrent.futures import ThreadPoolExecutor, as_completed

import os

import re

import threading
import logging
from logging.handlers import RotatingFileHandler
from services.security import SecurityStore
import time
import json

app = Flask(__name__)

app.secret_key = (
    os.environ.get("SWITCHOPS_SECRET_KEY")
    or os.urandom(32)
)

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

SECURITY_DB = os.path.join(
    BASE_DIR,
    "switchops.db"
)

security = SecurityStore(
    SECURITY_DB
)

class FiltroLogHTTP(logging.Filter):
    def filter(self, record):
        texto = record.getMessage()

        rotas_repetitivas = (
            "/api/live-ports/",
            "/api/live/",
            "/static/css/",
            "/static/js/",
        )

        return not any(
            rota in texto
            for rota in rotas_repetitivas
        )


logging.getLogger("werkzeug").addFilter(
    FiltroLogHTTP()
)


# auditoria
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

AUDIT_LOG = os.path.join(LOG_DIR, "switchops_audit.log")

APP_LOG = os.path.join(LOG_DIR, "switchops_app.log")

app_logger = logging.getLogger("switchops.app")
app_logger.setLevel(logging.INFO)

if not app_logger.handlers:
    app_handler = RotatingFileHandler(
        APP_LOG,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8"
    )
    app_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    app_logger.addHandler(app_handler)
    app_logger.propagate = False


audit_logger = logging.getLogger("switchops.audit")
audit_logger.setLevel(logging.INFO)

if not audit_logger.handlers:
    audit_handler = RotatingFileHandler(
        AUDIT_LOG,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8"
    )
    audit_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s")
    )
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = False

def registrar_auditoria(
    acao,
    resultado,
    nome_switch="-",
    porta="-",
    detalhe="-",
    usuario=None,
    perfil=None
):
    if usuario is None:
        usuario = session.get("usuario", "-")

    if perfil is None:
        perfil = session.get("perfil", "-")

    detalhe = str(detalhe).replace("\n", " ")

    audit_logger.info(
        "usuario=%s | perfil=%s | acao=%s | "
        "switch=%s | porta=%s | resultado=%s | detalhe=%s",
        usuario,
        perfil,
        acao,
        nome_switch,
        porta,
        resultado,
        detalhe
    )

# autenticação / rbac
#
# Usuários, hashes, roles, permissões, switches e escopos
# de portas são armazenados em switchops.db.
#


# credenciais ssh dos switches


#

# atenção:

# remova a senha antes de subir esse projeto no GitHub

# ou compartilhar o código.

#


SSH_USUARIO = os.environ.get(
    "SWITCHOPS_SSH_USER",
    ""
)

SSH_SENHA = os.environ.get(
    "SWITCHOPS_SSH_PASSWORD",
    ""
)


# cache de modelo dos switches


#

# O modelo muda raramente. O status das portas NÃO é

# cacheado: ele é consultado novamente a cada renderização

# autenticada para manter o painel visual atualizado.

#


MODELOS_SWITCH_CACHE = {}


# switches


CONFIG_SWITCHES = os.path.join(
    BASE_DIR,
    "config",
    "switches.json"
)

with open(CONFIG_SWITCHES, "r", encoding="utf-8") as arquivo:
    configuracao_switches = json.load(arquivo)

switches = configuracao_switches["switches"]
JUMP_HOST = configuracao_switches["jump_host"]


# vlans


CONFIG_VLANS = os.path.join(
    BASE_DIR,
    "config",
    "vlans.json"
)

with open(CONFIG_VLANS, "r", encoding="utf-8") as arquivo:
    vlans_configuradas = json.load(arquivo)

VLANS = {
    int(numero): nome
    for numero, nome in vlans_configuradas.items()
}


# todas as portas


todas_portas = []

for numero in range(1, 49):

    todas_portas.append(

        f"Gi1/0/{numero}"

    )

for numero in range(1, 51):

    todas_portas.append(

        f"Gi2/0/{numero}"

    )

todas_portas.extend([

    "Te1/0/1",

    "Te1/0/2",

    "Po1",

    "Po2",

    "Po3",

    "Po4",

    "Fa0"

])


# portas do perfil suporte


portas_suporte = [

    f"Gi2/0/{numero}"

    for numero in range(

        1,

        27

    )

]


# usuário atual


def usuario_atual():

    usuario = session.get(

        "usuario"

    )

    perfil = session.get(

        "perfil"

    )

    if not usuario or not perfil:

        return None

    return {

        "usuario": usuario,

        "perfil": perfil

    }


# portas disponíveis por perfil


def portas_para_usuario(
    perfil,
    nome_switch
):
    if security.has_all_ports(
        perfil,
        nome_switch
    ):
        return list(todas_portas)

    return security.allowed_ports(
        perfil,
        nome_switch
    )


# validar operação

def validar_operacao(
    perfil,
    nome_switch,
    porta,
    operacao
):
    security.validate_operation(
        perfil,
        nome_switch,
        porta,
        operacao
    )


# conexão direta


def conectar_direto(

    ip,

    usuario=None,

    senha=None

):

    if usuario is None:

        usuario = SSH_USUARIO

    if senha is None:

        senha = SSH_SENHA

    if not usuario or not senha:

        raise RuntimeError(
            "Credenciais SSH não configuradas. "
            "Execute setup_env.ps1 ou defina "
            "SWITCHOPS_SSH_USER e "
            "SWITCHOPS_SSH_PASSWORD."
        )

    equipamento = {

        "device_type":

            "cisco_ios",

        "host":

            ip,

        "username":

            usuario,

        "password":

            senha,

        "conn_timeout":

            10,

        "banner_timeout":

            15,

        "auth_timeout":

            15

    }

    return ConnectHandler(

        **equipamento

    )


# conexão via jump host - pool persistente


#

# Objetivo:

#

# - evitar abrir uma conexão nova com o jump host para cada

#   consulta;

# - manter até 2 sessões-base com o jump host prontas;

# - permitir até 2 acessos simultâneos aos switches remotos;

# - continuar compatível com todo o restante do código.

#

# As funções já existentes continuam chamando:

#

#     conexao = conectar_switch(...)

#     ...

#     conexao.disconnect()

#

# Quando a conexão é de um switch remoto, disconnect()

# NÃO derruba o SSH do jump host. Ele apenas sai do switch

# remoto e devolve a sessão-base ao pool.

#


JUMP_POOL_TAMANHO = 2

class JumpHostPool:

    def __init__(

        self,

        tamanho=2

    ):

        self.tamanho = tamanho

        self.ociosas = []

        self.criadas = 0

        self.condicao = threading.Condition()


    # testar se uma conexão ainda está viva


    def conexao_viva(

        self,

        conexao

    ):

        try:

            return bool(

                conexao.is_alive()

            )

        except Exception:

            return False


    # criar nova sessão-base com o jump host


    def criar_conexao(

        self,

        usuario,

        senha

    ):

        jump_ip = switches[

            JUMP_HOST

        ]["ip"]

        print(

            "[JUMP POOL] Abrindo nova sessão "

            f"com {JUMP_HOST}..."

        )

        conexao = conectar_direto(

            jump_ip,

            usuario,

            senha

        )

        conexao.find_prompt()

        return conexao


    # pegar uma sessão do pool


    def adquirir(

        self,

        usuario,

        senha

    ):

        criar_nova = False

        while True:

            with self.condicao:


                # primeiro tenta reutilizar uma ociosa


                while self.ociosas:

                    conexao = self.ociosas.pop()

                    if self.conexao_viva(

                        conexao

                    ):

                        print(

                            "[JUMP POOL] Reutilizando "

                            "sessão existente."

                        )

                        return conexao

                    try:

                        conexao.disconnect()

                    except Exception:

                        pass

                    self.criadas = max(

                        0,

                        self.criadas - 1

                    )


                # ainda há espaço para criar outra?


                if self.criadas < self.tamanho:

                    self.criadas += 1

                    criar_nova = True

                    break


                # as duas estão em uso.

                # espera uma voltar.


                self.condicao.wait(

                    timeout=15

                )

        if criar_nova:

            try:

                return self.criar_conexao(

                    usuario,

                    senha

                )

            except Exception:

                with self.condicao:

                    self.criadas = max(

                        0,

                        self.criadas - 1

                    )

                    self.condicao.notify()

                raise


    # devolver sessão ao pool


    def devolver(

        self,

        conexao,

        reutilizavel=True

    ):

        with self.condicao:

            if (

                reutilizavel

                and

                self.conexao_viva(

                    conexao

                )

            ):

                self.ociosas.append(

                    conexao

                )

            else:

                try:

                    conexao.disconnect()

                except Exception:

                    pass

                self.criadas = max(

                    0,

                    self.criadas - 1

                )

            self.condicao.notify()


    # fechar todas as sessões ociosas


    def fechar_ociosas(self):

        with self.condicao:

            while self.ociosas:

                conexao = self.ociosas.pop()

                try:

                    conexao.disconnect()

                except Exception:

                    pass

                self.criadas = max(

                    0,

                    self.criadas - 1

                )

            self.condicao.notify_all()

JUMP_POOL = JumpHostPool(

    tamanho=JUMP_POOL_TAMANHO

)


# wrapper da sessão remota


#

# Ele se comporta como a conexão normal do Netmiko.

#

# A única diferença é disconnect():

#

# - manda "exit" no switch remoto;

# - volta para o jump host;

# - devolve a conexão-base para o pool.

#


class ConexaoViaJump:

    def __init__(

        self,

        conexao,

        pool

    ):

        self._conexao = conexao

        self._pool = pool

        self._finalizada = False

    def __getattr__(

        self,

        nome

    ):

        return getattr(

            self._conexao,

            nome

        )

    def disconnect(self):

        if self._finalizada:

            return

        self._finalizada = True

        reutilizavel = True

        try:


            # sai do switch remoto e volta ao jump host


            self._conexao.send_command_timing(

                "exit",

                strip_prompt=False,

                strip_command=False,

                cmd_verify=False

            )


            # confirma que voltou a um prompt válido


            self._conexao.find_prompt()


            # atualiza o base prompt do netmiko.

            #

            # Não fazemos novo handshake SSH.


            self._conexao.set_base_prompt()

        except Exception as erro:

            reutilizavel = False

            print(

                "[JUMP POOL] Sessão não pôde "

                "ser reutilizada:"

            )

            print(

                erro

            )

        finally:

            self._pool.devolver(

                self._conexao,

                reutilizavel=

                    reutilizavel

            )


# conexão via jump host


def conectar_via_jump(

    ip_destino,

    usuario=None,

    senha=None

):

    if usuario is None:

        usuario = SSH_USUARIO

    if senha is None:

        senha = SSH_SENHA


    # pega uma sessão já aberta com o jump host


    conexao = JUMP_POOL.adquirir(

        usuario,

        senha

    )

    conectado_remoto = False

    try:


        # garante que estamos no prompt do jump host


        conexao.find_prompt()

        comando = (

            f"ssh -l "

            f"{usuario} "

            f"{ip_destino}"

        )

        saida = (

            conexao.send_command_timing(

                comando,

                strip_prompt=False,

                strip_command=False

            )

        )


        # login ssh interno


        for _ in range(4):

            texto = saida.lower()

            if (

                "yes/no" in texto

                or

                "continue connecting" in texto

            ):

                saida += (

                    conexao.send_command_timing(

                        "yes",

                        strip_prompt=False,

                        strip_command=False

                    )

                )

                continue

            if (

                "password" in texto

                or

                "senha" in texto

            ):

                saida += (

                    conexao.send_command_timing(

                        senha,

                        strip_prompt=False,

                        strip_command=False,

                        cmd_verify=False

                    )

                )

                continue

            break

        texto = saida.lower()

        erros = [

            "permission denied",

            "authentication failed",

            "connection refused",

            "connection timed out",

            "no route to host",

            "host unreachable",

            "unknown host"

        ]

        for erro in erros:

            if erro in texto:

                raise Exception(

                    f"Falha no SSH interno: "

                    f"{erro}"

                )


        # o netmiko passa a tratar a sessão como o

        # switch remoto.


        redispatch(

            conexao,

            device_type="cisco_ios"

        )

        conexao.find_prompt()

        conectado_remoto = True


        # retorna wrapper compatível com o resto do app


        return ConexaoViaJump(

            conexao,

            JUMP_POOL

        )

    except Exception:


        # se o ssh interno falhou, não deixa uma sessão

        # com estado incerto voltar para o pool.


        if not conectado_remoto:

            JUMP_POOL.devolver(

                conexao,

                reutilizavel=False

            )

        raise


# conectar switch


def conectar_switch(

    nome_switch,

    usuario=None,

    senha=None

):

    if nome_switch not in switches:

        raise Exception(

            "Switch não cadastrado."

        )

    dados = switches[

        nome_switch

    ]

    if dados[

        "acesso"

    ] == "direto":

        return conectar_direto(

            dados["ip"],

            usuario,

            senha

        )

    if dados[

        "acesso"

    ] == "jump":

        return conectar_via_jump(

            dados["ip"],

            usuario,

            senha

        )

    if dados[

        "acesso"

    ] == "direto_fallback_jump":

        try:

            return conectar_direto(

                dados["ip"],

                usuario,

                senha

            )

        except Exception as erro_direto:

            print(

                f"[ACESSO] Falha direta em {nome_switch}: "

                f"{erro_direto}"

            )

            print(

                f"[ACESSO] Tentando {nome_switch} via {JUMP_HOST}..."

            )

            return conectar_via_jump(

                dados["ip"],

                usuario,

                senha

            )

    raise Exception(

        "Tipo de acesso inválido."

    )


# interpretar status


def interpretar_status(

    resposta,

    porta

):

    estados = [

        "connected",

        "notconnect",

        "disabled",

        "err-disabled",

        "inactive"

    ]

    for linha in resposta.splitlines():

        linha = linha.strip()

        if not linha.startswith(

            porta

        ):

            continue

        partes = linha.split()

        indice_estado = None

        for indice, valor in enumerate(

            partes

        ):

            if valor in estados:

                indice_estado = indice

                break

        if indice_estado is None:

            continue

        nome = " ".join(

            partes[

                1:indice_estado

            ]

        )

        vlan = "-"

        duplex = "-"

        velocidade = "-"

        if len(

            partes

        ) > indice_estado + 1:

            vlan = partes[

                indice_estado + 1

            ]

        if len(

            partes

        ) > indice_estado + 2:

            duplex = partes[

                indice_estado + 2

            ]

        if len(

            partes

        ) > indice_estado + 3:

            velocidade = partes[

                indice_estado + 3

            ]

        return {

            "porta":

                partes[0],

            "nome":

                nome or "-",

            "estado":

                partes[

                    indice_estado

                ],

            "vlan":

                vlan,

            "duplex":

                duplex,

            "velocidade":

                velocidade

        }

    return None


# interpretar todas as portas do switch


def interpretar_status_todos(

    resposta,

    portas_permitidas=None

):

    estados = [

        "connected",

        "notconnect",

        "disabled",

        "err-disabled",

        "inactive"

    ]

    if portas_permitidas is not None:

        portas_permitidas = set(

            portas_permitidas

        )

    portas_encontradas = []

    for linha in resposta.splitlines():

        linha = linha.strip()

        if not linha:

            continue

        partes = linha.split()

        if len(partes) < 2:

            continue

        porta = partes[0]

        # Ignora cabeçalhos e linhas que não parecem interfaces.

        if not re.match(

            r"^(Gi|Te|Fa|Po)\S+$",

            porta,

            re.IGNORECASE

        ):

            continue

        if (

            portas_permitidas is not None

            and

            porta not in portas_permitidas

        ):

            continue

        indice_estado = None

        for indice, valor in enumerate(

            partes

        ):

            if valor.lower() in estados:

                indice_estado = indice

                break

        if indice_estado is None:

            continue

        nome = " ".join(

            partes[

                1:indice_estado

            ]

        )

        vlan = "-"

        duplex = "-"

        velocidade = "-"

        if len(partes) > indice_estado + 1:

            vlan = partes[

                indice_estado + 1

            ]

        if len(partes) > indice_estado + 2:

            duplex = partes[

                indice_estado + 2

            ]

        if len(partes) > indice_estado + 3:

            velocidade = partes[

                indice_estado + 3

            ]

        membro = None

        numero = 999

        prefixo = "OUTRA"

        resultado_porta = re.match(

            r"^(Gi|Te)(\d+)/(\d+)/(\d+)$",

            porta,

            re.IGNORECASE

        )

        if resultado_porta:

            prefixo = (

                resultado_porta

                .group(1)

                .upper()

            )

            membro = int(

                resultado_porta.group(2)

            )

            numero = int(

                resultado_porta.group(4)

            )

        else:

            resultado_simples = re.match(

                r"^(Fa|Po)(\d+)(?:/(\d+))?$",

                porta,

                re.IGNORECASE

            )

            if resultado_simples:

                prefixo = (

                    resultado_simples

                    .group(1)

                    .upper()

                )

                if resultado_simples.group(3):

                    numero = int(

                        resultado_simples.group(3)

                    )

                else:

                    numero = int(

                        resultado_simples.group(2)

                    )

        estado = partes[

            indice_estado

        ].lower()

        portas_encontradas.append({

            "porta":

                porta,

            "nome":

                nome or "-",

            "estado":

                estado,

            "vlan":

                vlan,

            "duplex":

                duplex,

            "velocidade":

                velocidade,

            "trunk":

                vlan.lower() == "trunk",

            "membro":

                membro,

            "numero":

                numero,

            "prefixo":

                prefixo

        })

    ordem_prefixo = {

        "GI": 1,

        "TE": 2,

        "FA": 3,

        "PO": 4,

        "OUTRA": 9

    }

    portas_encontradas.sort(

        key=lambda item: (

            item["membro"]

            if item["membro"] is not None

            else 999,

            ordem_prefixo.get(

                item["prefixo"],

                9

            ),

            item["numero"],

            item["porta"]

        )

    )

    return portas_encontradas


# identificar modelo do switch


def obter_modelo_switch(

    conexao,

    nome_switch

):

    if nome_switch in MODELOS_SWITCH_CACHE:

        return MODELOS_SWITCH_CACHE[

            nome_switch

        ]

    modelo = "Cisco Catalyst"

    try:

        resposta = conexao.send_command(

            "show version",

            read_timeout=8

        )

        padroes = [

            r"Model [Nn]umber\s*:\s*(\S+)",

            r"[Cc]isco\s+"

            r"(WS-[A-Za-z0-9_-]+)"

            r"\s+****\\\**(**",

            r"[Cc]isco\s+"

            r"(C[0-9][A-Za-z0-9_-]+)"

            r"\s+****\\\**(**"

        ]

        for padrao in padroes:

            resultado = re.search(

                padrao,

                resposta

            )

            if resultado:

                modelo = resultado.group(1)

                break

    except Exception:

        pass

    MODELOS_SWITCH_CACHE[

        nome_switch

    ] = modelo

    return modelo


# painel visual do switch


def montar_painel_switch(

    conexao,

    nome_switch,

    portas_permitidas=None,

    resposta_status=None

):

    """Monta o painel usando uma conexão que já está aberta."""

    painel = {

        "switch": nome_switch,

        "modelo": "Cisco Catalyst",

        "portas": [],

        "grupos": [],

        "erro": None

    }

    try:

        if resposta_status is None:

            resposta_status = conexao.send_command(

                "show interfaces status",

                read_timeout=10

            )

        painel["modelo"] = obter_modelo_switch(

            conexao,

            nome_switch

        )

        painel["portas"] = interpretar_status_todos(

            resposta_status,

            portas_permitidas

        )

        membros = sorted({

            porta["membro"]

            for porta in painel["portas"]

            if porta["membro"] is not None

        })

        grupos = []

        for membro in membros:

            grupos.append({

                "titulo": f"Membro {membro}",

                "portas": [

                    porta

                    for porta in painel["portas"]

                    if porta["membro"] == membro

                ]

            })

        outras_portas = [

            porta

            for porta in painel["portas"]

            if porta["membro"] is None

        ]

        if outras_portas:

            grupos.append({

                "titulo": "Outras interfaces",

                "portas": outras_portas

            })

        painel["grupos"] = grupos

    except Exception as erro:

        painel["erro"] = str(erro)

    return painel

def obter_painel_switch(

    nome_switch,

    portas_permitidas=None

):

    """Abre conexão somente quando ainda não existe uma sessão utilizável."""

    conexao = None

    try:

        conexao = conectar_switch(nome_switch)

        return montar_painel_switch(

            conexao,

            nome_switch,

            portas_permitidas

        )

    except Exception as erro:

        return {

            "switch": nome_switch,

            "modelo": "Cisco Catalyst",

            "portas": [],

            "grupos": [],

            "erro": str(erro)

        }

    finally:

        if conexao:

            try:

                conexao.disconnect()

            except Exception:

                pass


# normalizar mac


def normalizar_mac(mac):

    mac_limpo = re.sub(

        r"[^0-9A-Fa-f]",

        "",

        mac

    )

    if len(mac_limpo) != 12:

        raise ValueError(

            "MAC inválido."

        )

    return mac_limpo.lower()


# formato cisco


def mac_cisco(mac):

    mac = normalizar_mac(mac)

    return (

        f"{mac[0:4]}."

        f"{mac[4:8]}."

        f"{mac[8:12]}"

    )

# auxiliares - localização real do mac

def normalizar_nome_interface(porta):
    porta = str(porta).strip()

    substituicoes = (
        ("TenGigabitEthernet", "Te"),
        ("GigabitEthernet", "Gi"),
        ("FastEthernet", "Fa"),
        ("Port-channel", "Po"),
        ("Port-Channel", "Po"),
    )

    for completo, curto in substituicoes:
        if porta.lower().startswith(
            completo.lower()
        ):
            porta = curto + porta[len(completo):]
            break

    return porta.lower()


def obter_uplinks_cdp(conexao):
    """
    Retorna as interfaces locais que possuem um vizinho CDP
    com capacidade de switch/bridge.

    Isso identifica o que realmente é caminho entre switches,
    sem assumir que toda porta em modo trunk é um uplink.
    """
    uplinks = set()

    try:
        resposta = conexao.send_command(
            "show cdp neighbors detail",
            read_timeout=8
        )

        texto = resposta.lower()

        if (
            "invalid input" in texto
            or "cdp is not enabled" in texto
            or "cdp is not running" in texto
        ):
            return uplinks

        # Cada entrada detalhada do CDP é analisada separadamente.
        blocos = re.split(
            r"-{5,}",
            resposta
        )

        for bloco in blocos:
            if not bloco.strip():
                continue

            interface = re.search(
                r"Interface:\s*([^,\r\n]+)",
                bloco,
                re.IGNORECASE
            )

            capacidades = re.search(
                r"Capabilities:\s*([^\r\n]+)",
                bloco,
                re.IGNORECASE
            )

            plataforma = re.search(
                r"Platform:\s*([^,\r\n]+)",
                bloco,
                re.IGNORECASE
            )

            device_id = re.search(
                r"Device ID:\s*([^\r\n]+)",
                bloco,
                re.IGNORECASE
            )

            if not interface:
                continue

            capacidade_texto = (
                capacidades.group(1).lower()
                if capacidades
                else ""
            )

            plataforma_texto = (
                plataforma.group(1).lower()
                if plataforma
                else ""
            )

            device_texto = (
                device_id.group(1).lower()
                if device_id
                else ""
            )

            # Switches Cisco normalmente anunciam "Switch" nas
            # capabilities. Mantemos alguns fallbacks para IOS antigos.
            vizinho_de_rede = (
                "switch" in capacidade_texto
                or "bridge" in capacidade_texto
                or "trans-bridge" in capacidade_texto
                or "source-route-bridge" in capacidade_texto
                or any(
                    nome.lower() in device_texto
                    for nome in switches
                )
                or (
                    "cisco" in plataforma_texto
                    and (
                        "ws-c" in plataforma_texto
                        or "catalyst" in plataforma_texto
                        or "c9" in plataforma_texto
                    )
                )
            )

            if vizinho_de_rede:
                uplinks.add(
                    normalizar_nome_interface(
                        interface.group(1)
                    )
                )

    except Exception:
        pass

    return uplinks


def obter_uplinks_por_descricao(conexao):
    """
    Fallback caso CDP não esteja habilitado.
    Só considera descrições que parecem explicitamente apontar
    para outro switch cadastrado.
    """
    uplinks = set()

    try:
        resposta = conexao.send_command(
            "show interfaces description",
            read_timeout=7
        )

        for linha in resposta.splitlines():
            partes = linha.split(
                None,
                3
            )

            if len(partes) < 4:
                continue

            porta = partes[0]
            descricao = partes[3].lower()

            if any(
                nome.lower() in descricao
                for nome in switches
            ):
                uplinks.add(
                    normalizar_nome_interface(
                        porta
                    )
                )

    except Exception:
        pass

    return uplinks


def obter_uplinks_switch(conexao):
    uplinks = obter_uplinks_cdp(
        conexao
    )

    # Complementa CDP, mas não substitui um resultado válido.
    uplinks.update(
        obter_uplinks_por_descricao(
            conexao
        )
    )

    return uplinks


# buscar mac em um switch


def buscar_mac_no_switch(

    nome_switch,

    mac

):

    conexao = None

    resultados = []

    try:

        print(

            f"[MAC] Consultando {nome_switch}..."

        )

        conexao = conectar_switch(

            nome_switch

        )

        # Descobre quais portas realmente levam a outro
        # switch. Não descartamos uma porta só por ela operar
        # em trunk, pois ela pode ser a porta final do host.
        uplinks_switch = obter_uplinks_switch(
            conexao
        )

        mac_formatado = mac_cisco(

            mac

        )

        resposta = (

            conexao.send_command(

                "show mac address-table "

                f"address {mac_formatado}",

                read_timeout=5

            )

        )


        # fallback ios antigo


        if (

            "invalid input"

            in resposta.lower()

            or

            "incomplete command"

            in resposta.lower()

        ):

            resposta = (

                conexao.send_command(

                    "show mac-address-table "

                    f"address {mac_formatado}",

                    read_timeout=5

                )

            )

        mac_normalizado = normalizar_mac(

            mac

        )

        for linha in resposta.splitlines():

            partes = linha.split()

            if len(partes) < 4:

                continue

            indice_mac = None

            for indice, parte in enumerate(

                partes

            ):

                try:

                    if (

                        normalizar_mac(parte)

                        ==

                        mac_normalizado

                    ):

                        indice_mac = indice

                        break

                except ValueError:

                    continue

            if indice_mac is None:

                continue

            if indice_mac == 0:

                continue

            vlan = partes[

                indice_mac - 1

            ]

            tipo = "-"

            porta = "-"

            if len(

                partes

            ) > indice_mac + 1:

                tipo = partes[

                    indice_mac + 1

                ]

            if len(

                partes

            ) > indice_mac + 2:

                porta = partes[-1]

            descricao = "-"

            trunk = False
            uplink = False

            if porta != "-":

                try:

                    resposta_status = (

                        conexao.send_command(

                            "show interfaces "

                            f"{porta} status",

                            read_timeout=5

                        )

                    )

                    status = (

                        interpretar_status(

                            resposta_status,

                            porta

                        )

                    )

                    if status:

                        descricao = status[

                            "nome"

                        ]

                        trunk = (

                            status[

                                "vlan"

                            ].lower()

                            ==

                            "trunk"

                        )

                except Exception:

                    pass

                uplink = (
                    normalizar_nome_interface(
                        porta
                    )
                    in uplinks_switch
                )

            resultados.append({

                "switch":

                    nome_switch,

                "ip":

                    switches[

                        nome_switch

                    ]["ip"],

                "vlan":

                    vlan,

                "tipo":

                    tipo,

                "porta":

                    porta,

                "descricao":

                    descricao,

                # Informativo apenas. Não usamos mais "trunk"
                # para decidir se esta é a porta final.
                "trunk":

                    trunk,

                # Uplink significa que há outro equipamento de
                # rede do outro lado da porta.
                "uplink":

                    uplink

            })

        print(

            f"[MAC] {nome_switch} concluído."

        )

    finally:

        if conexao:

            try:

                conexao.disconnect()

            except Exception:

                pass

    return resultados


# busca mac paralela


def buscar_mac_todos(mac):

    resultados = []

    erros = []

    print(

        "[MAC] Iniciando busca paralela..."

    )

    with ThreadPoolExecutor(

        max_workers=3

    ) as executor:

        tarefas = {

            executor.submit(

                buscar_mac_no_switch,

                nome_switch,

                mac

            ): nome_switch

            for nome_switch in switches

        }

        for tarefa in as_completed(

            tarefas

        ):

            nome_switch = tarefas[

                tarefa

            ]

            try:

                encontrados = tarefa.result()

                resultados.extend(

                    encontrados

                )

            except Exception as erro:

                print(

                    f"[MAC] ERRO "

                    f"{nome_switch}: "

                    f"{erro}"

                )

                erros.append(

                    f"{nome_switch}: {erro}"

                )

    print(

        "[MAC] Busca paralela concluída."

    )

    # A porta final é a ocorrência que NÃO aponta para outro
    # switch. Uma interface pode ser trunk e ainda assim ser
    # a porta real de um host com VLAN tagging.
    portas_finais = [

        resultado

        for resultado

        in resultados

        if not resultado.get(

            "uplink",

            False

        )

    ]

    return (

        portas_finais,

        erros

    )


# vlans disponíveis no switch


def obter_vlans_switch(

    conexao

):

    resposta = conexao.send_command(

        "show vlan brief",

        read_timeout=8

    )

    vlans_encontradas = {}

    for linha in resposta.splitlines():

        linha = linha.strip()

        resultado = re.match(

            r"^(\d+)\s+(\S+)\s+(active|act/unsup)",

            linha,

            re.IGNORECASE

        )

        if not resultado:

            continue

        vlan_id = int(

            resultado.group(1)

        )

        nome = resultado.group(2)

        if vlan_id in {

            1002,

            1003,

            1004,

            1005

        }:

            continue

        vlans_encontradas[

            vlan_id

        ] = nome

    return vlans_encontradas


# vlan atual da porta


def obter_vlan_atual(

    conexao,

    porta

):

    resposta = conexao.send_command(

        f"show interfaces {porta} switchport",

        read_timeout=8

    )

    modo_operacional = None

    vlan_atual = None

    for linha in resposta.splitlines():

        linha_limpa = linha.strip()

        if linha_limpa.lower().startswith(

            "operational mode:"

        ):

            modo_operacional = (

                linha_limpa

                .split(":", 1)[1]

                .strip()

                .lower()

            )

        if linha_limpa.lower().startswith(

            "access mode vlan:"

        ):

            texto_vlan = (

                linha_limpa

                .split(":", 1)[1]

                .strip()

            )

            resultado = re.match(

                r"(\d+)",

                texto_vlan

            )

            if resultado:

                vlan_atual = int(

                    resultado.group(1)

                )

    return {

        "modo":

            modo_operacional,

        "vlan":

            vlan_atual

    }


# alterar vlan


def alterar_vlan_porta(

    nome_switch,

    porta,

    nova_vlan,

    conexao=None

):

    """Altera a VLAN; pode usar uma conexão já aberta."""

    conexao_propria = conexao is None

    try:

        if conexao is None:

            conexao = conectar_switch(nome_switch)

        informacoes = obter_vlan_atual(

            conexao,

            porta

        )

        modo = informacoes["modo"]

        vlan_antiga = informacoes["vlan"]

        if modo is None:

            raise Exception(

                "Não foi possível identificar o modo da interface."

            )

        if "trunk" in modo:

            raise Exception(

                "Alteração bloqueada: "

                "a interface está operando como trunk."

            )

        vlans_existentes = obter_vlans_switch(

            conexao

        )

        if nova_vlan not in vlans_existentes:

            raise Exception(

                f"A VLAN {nova_vlan} "

                "não existe neste switch."

            )

        conexao.send_config_set([

            f"interface {porta}",

            f"switchport access vlan {nova_vlan}"

        ])

        verificacao = obter_vlan_atual(

            conexao,

            porta

        )

        vlan_confirmada = verificacao["vlan"]

        if vlan_confirmada != nova_vlan:

            raise Exception(

                "O comando foi enviado, "

                "mas a nova VLAN não foi confirmada."

            )

        return {

            "vlan_antiga": vlan_antiga,

            "vlan_nova": vlan_confirmada,

            "nome_vlan": vlans_existentes.get(

                nova_vlan,

                str(nova_vlan)

            )

        }

    finally:

        if conexao_propria and conexao:

            try:

                conexao.disconnect()

            except Exception:

                pass


# saúde / dashboard do switch

def _extrair_percentual_cpu(saida):
    """
    Tenta extrair o uso de CPU de diferentes versões do IOS.
    Retorna inteiro ou None.
    """
    padroes = [
        r"five seconds:\s*(\d+)%",
        r"5 seconds:\s*(\d+)%",
        r"CPU utilization.*?(\d+)%",
    ]

    for padrao in padroes:
        resultado = re.search(
            padrao,
            saida,
            re.IGNORECASE
        )

        if resultado:
            return int(
                resultado.group(1)
            )

    return None


def _extrair_memoria(saida):
    """
    Tenta extrair memória total/usada de saídas comuns do IOS.
    Retorna (percentual, usado, total) ou (None, None, None).
    """
    # Formato comum:
    # Processor Pool Total:  12345678 Used: 4567890 Free: ...
    resultado = re.search(
        r"Processor\s+Pool\s+Total:\s*(\d+)"
        r"\s+Used:\s*(\d+)",
        saida,
        re.IGNORECASE
    )

    if resultado:
        total = int(
            resultado.group(1)
        )
        usado = int(
            resultado.group(2)
        )

        percentual = (
            round(
                usado * 100 / total
            )
            if total
            else None
        )

        return (
            percentual,
            usado,
            total
        )

    # Alguns IOS exibem uma linha "Processor" em formato tabular.
    for linha in saida.splitlines():
        if not linha.strip().lower().startswith(
            "processor"
        ):
            continue

        numeros = [
            int(valor)
            for valor in re.findall(
                r"\b\d+\b",
                linha
            )
        ]

        if len(numeros) >= 2:
            total = numeros[0]
            usado = numeros[1]

            if total > 0:
                return (
                    round(
                        usado * 100 / total
                    ),
                    usado,
                    total
                )

    return (
        None,
        None,
        None
    )


def _extrair_temperatura(saida):
    """
    Procura temperatura numérica em saídas comuns de Catalyst.

    Exemplos aceitos:
    - System Temperature Value: 31 Degree Celsius
    - Temperature: 42 Celsius
    - Temperature 42 C
    - Inlet Temperature Value: 28 Degree Celsius
    """
    padroes = [
        r"(?:system\s+)?temperature\s+value\s*:\s*(\d{1,3})\s*(?:degree\s+)?celsius",
        r"(?:inlet|outlet|hotspot)?\s*temperature\s+value\s*:\s*(\d{1,3})\s*(?:degree\s+)?celsius",
        r"(?:temperature|temp)[^0-9]{0,45}(\d{1,3})\s*(?:degree\s+)?(?:c|celsius|°c)",
        r"(\d{1,3})\s*(?:degree\s+)?celsius",
        r"(\d{1,3})\s*°c",
    ]

    temperaturas = []

    for padrao in padroes:
        for valor in re.findall(
            padrao,
            saida,
            re.IGNORECASE
        ):
            try:
                temperatura = int(valor)

                if 0 < temperatura < 130:
                    temperaturas.append(
                        temperatura
                    )

            except ValueError:
                pass

        if temperaturas:
            break

    if temperaturas:
        return max(
            temperaturas
        )

    return None


def _extrair_estado_temperatura(saida):
    """
    Alguns Catalyst antigos não mostram graus, apenas o estado
    térmico. Nesse caso o Dashboard exibe o estado em vez de
    inventar uma temperatura numérica.
    """
    texto = saida.lower()

    if any(
        termo in texto
        for termo in [
            "temperature state: red",
            "temperature is critical",
            "temperature critical",
            "over temperature",
            "overtemperature"
        ]
    ):
        return "CRITICAL"

    if any(
        termo in texto
        for termo in [
            "temperature state: yellow",
            "temperature warning",
            "temperature is warning",
            "temperature is high"
        ]
    ):
        return "WARNING"

    if any(
        termo in texto
        for termo in [
            "temperature state: green",
            "system temperature is ok",
            "temperature is ok",
            "temperature status: ok"
        ]
    ):
        return "OK"

    return None


def _extrair_uptime(saida):
    """
    Extrai a descrição de uptime do show version.
    """
    for linha in saida.splitlines():
        if " uptime is " in linha.lower():
            return linha.split(
                " uptime is ",
                1
            )[1].strip()

    return None


def coletar_saude_switch(
    nome_switch
):
    """
    Coleta informações leves para o Dashboard.
    Falhas em comandos opcionais não derrubam o painel:
    o campo correspondente simplesmente retorna None/N/A.
    """
    conexao = None

    dados = {
        "switch": nome_switch,
        "ip": switches[
            nome_switch
        ]["ip"],
        "cpu": None,
        "memoria": None,
        "memoria_usada": None,
        "memoria_total": None,
        "temperatura": None,
        "temperatura_estado": None,
        "uptime": None,
        "modelo": MODELOS_SWITCH_CACHE.get(
            nome_switch,
            "Cisco Catalyst"
        ),
        "erro": None
    }

    try:
        conexao = conectar_switch(
            nome_switch
        )

        # cpu
        try:
            saida_cpu = conexao.send_command(
                "show processes cpu | include CPU utilization",
                read_timeout=7
            )
            dados["cpu"] = (
                _extrair_percentual_cpu(
                    saida_cpu
                )
            )
        except Exception:
            pass

        # Memória
        try:
            saida_memoria = conexao.send_command(
                "show processes memory",
                read_timeout=7
            )

            (
                dados["memoria"],
                dados["memoria_usada"],
                dados["memoria_total"]
            ) = _extrair_memoria(
                saida_memoria
            )
        except Exception:
            pass

        # Versão / uptime / modelo
        try:
            saida_version = conexao.send_command(
                "show version",
                read_timeout=8
            )

            dados["uptime"] = (
                _extrair_uptime(
                    saida_version
                )
            )

            if nome_switch not in MODELOS_SWITCH_CACHE:
                dados["modelo"] = obter_modelo_switch(
                    conexao,
                    nome_switch
                )
            else:
                dados["modelo"] = MODELOS_SWITCH_CACHE[
                    nome_switch
                ]

        except Exception:
            pass

        # Temperatura/environment.
        # Catalyst antigos variam bastante: alguns retornam graus,
        # outros apenas GREEN/OK/WARNING/RED.
        comandos_temperatura = [
            "show environment temperature status",
            "show environment temperature",
            "show environment all",
            "show env all",
            "show env",
            "show platform temperature"
        ]

        for comando in comandos_temperatura:
            try:
                saida_temp = conexao.send_command(
                    comando,
                    read_timeout=6
                )

                texto_temp = saida_temp.lower()

                if (
                    "invalid input" in texto_temp
                    or
                    "incomplete command" in texto_temp
                    or
                    "ambiguous command" in texto_temp
                ):
                    continue

                temperatura = _extrair_temperatura(
                    saida_temp
                )

                estado_temperatura = _extrair_estado_temperatura(
                    saida_temp
                )

                if temperatura is not None:
                    dados["temperatura"] = temperatura

                if estado_temperatura is not None:
                    dados["temperatura_estado"] = estado_temperatura

                if (
                    dados["temperatura"] is not None
                    or
                    dados["temperatura_estado"] is not None
                ):
                    break

            except Exception:
                continue

    except Exception as erro:
        dados["erro"] = str(
            erro
        )

    finally:
        if conexao:
            try:
                conexao.disconnect()
            except Exception:
                pass

    return dados


# rota principal


@app.route(

    "/",

    methods=[

        "GET",

        "POST"

    ]

)

def inicio():

    mensagem = ""

    status_porta = None

    resultados_mac = []

    mac_pesquisado = ""

    painel_switch = None


    # login switchops


    if (

        request.method == "POST"

        and

        request.form.get(

            "acao"

        ) == "login"

    ):

        usuario = request.form.get(

            "usuario",

            ""

        ).strip()

        senha = request.form.get(

            "senha",

            ""

        )

        cadastro = security.authenticate(
            usuario,
            senha
        )

        if cadastro:
            session.clear()

            session["usuario"] = cadastro[
                "usuario"
            ]

            session["perfil"] = cadastro[
                "perfil"
            ]

            registrar_auditoria(
                "login",
                "sucesso",
                usuario=cadastro["usuario"],
                perfil=cadastro["perfil"]
            )

            return redirect(
                url_for(
                    "inicio"
                )
            )

        mensagem = (

            "Usuário ou senha inválidos."

        )

    atual = usuario_atual()


    # não autenticado


    if atual is None:

        return render_template(

            "index.html",

            autenticado=False,

            usuario=None,

            perfil=None,
            pode_buscar_mac=False,
            pode_alterar_vlan=False,
            pode_administrar_usuarios=False,

            switches={},

            portas=[],

            vlans={},

            painel_switch=None,

            mensagem=mensagem,

            status_porta=None,

            resultados_mac=[],

            mac_pesquisado="",

            switch_selecionado="",

            porta_selecionada=""

        )

    perfil = atual[

        "perfil"

    ]


    # switches permitidos


    nomes_switches = security.allowed_switches(
        perfil,
        list(switches.keys())
    )

    switches_visiveis = {

        nome:

            switches[

                nome

            ]

        for nome

        in nomes_switches

    }


    # switch padrão


    switch_padrao = (
        nomes_switches[0]
        if nomes_switches
        else ""
    )

    switch_selecionado = (

        request.values.get(

            "switch",

            session.get(

                "switch_selecionado",

                switch_padrao

            )

        )

    )

    if (

        switch_selecionado

        not in

        nomes_switches

    ):

        switch_selecionado = switch_padrao


    # portas visíveis


    portas_visiveis = (

        portas_para_usuario(

            perfil,

            switch_selecionado

        )

    )

    porta_padrao = (
        portas_visiveis[0]
        if portas_visiveis
        else ""
    )

    porta_selecionada = (

        request.form.get(

            "porta",

            session.get(

                "porta_selecionada",

                porta_padrao

            )

        )

    )

    if (

        porta_selecionada

        not in

        portas_visiveis

    ):

        porta_selecionada = porta_padrao


    # post autenticado


    if request.method == "POST":

        acao = request.form.get(

            "acao"

        )


        # operações de porta


        if acao == "executar_porta":

            operacao = request.form.get(

                "operacao"

            )

            try:

                validar_operacao(

                    perfil,

                    switch_selecionado,

                    porta_selecionada,

                    operacao

                )

                session[

                    "switch_selecionado"

                ] = switch_selecionado

                session[

                    "porta_selecionada"

                ] = porta_selecionada


                # consultar


                if operacao == "status":

                    conexao = None

                    try:

                        conexao = conectar_switch(

                            switch_selecionado

                        )

                        resposta = conexao.send_command(

                            "show interfaces status",

                            read_timeout=10

                        )

                        status_porta = interpretar_status(

                            resposta,

                            porta_selecionada

                        )

                        painel_switch = montar_painel_switch(

                            conexao,

                            switch_selecionado,

                            portas_visiveis,

                            resposta

                        )

                        registrar_auditoria(
                            "consultar_porta",
                            "sucesso",
                            switch_selecionado,
                            porta_selecionada
                        )

                        if status_porta is None:

                            mensagem = (

                                "Não foi possível interpretar "

                                "o status da interface."

                            )

                        else:

                            # A consulta bem-sucedida já é exibida no
                            # painel de status abaixo. Evita duplicar
                            # a mesma informação no alerta superior.
                            mensagem = ""

                    finally:

                        if conexao:

                            try:

                                conexao.disconnect()

                            except Exception:

                                pass


                # limpar sticky


                elif operacao == "sticky":

                    conexao = None

                    try:
                        conexao = conectar_switch(
                            switch_selecionado
                        )

                        limpar_sticky_porta(
                            conexao,
                            porta_selecionada
                        )

                        resposta = conexao.send_command(
                            "show interfaces status",
                            read_timeout=10
                        )

                        status_porta = interpretar_status(
                            resposta,
                            porta_selecionada
                        )

                        painel_switch = montar_painel_switch(
                            conexao,
                            switch_selecionado,
                            portas_visiveis,
                            resposta
                        )

                        registrar_auditoria(
                            "limpar_sticky",
                            "sucesso",
                            switch_selecionado,
                            porta_selecionada
                        )

                        mensagem = (
                            "Sticky MAC limpo.\n\n"
                            f"Switch: {switch_selecionado}\n"
                            f"Porta: {porta_selecionada}"
                        )

                    except Exception as erro:
                        registrar_auditoria(
                            "limpar_sticky",
                            "erro",
                            switch_selecionado,
                            porta_selecionada,
                            str(erro)
                        )
                        raise

                    finally:
                        if conexao:
                            try:
                                conexao.disconnect()
                            except Exception:
                                pass


                # desligar


                elif operacao == "desligar":

                    conexao = None

                    try:

                        conexao = conectar_switch(

                            switch_selecionado

                        )

                        conexao.send_config_set([

                            f"interface {porta_selecionada}",

                            "shutdown"

                        ])

                        resposta = conexao.send_command(

                            "show interfaces status",

                            read_timeout=10

                        )

                        status_porta = interpretar_status(

                            resposta,

                            porta_selecionada

                        )

                        painel_switch = montar_painel_switch(

                            conexao,

                            switch_selecionado,

                            portas_visiveis,

                            resposta

                        )


                        # O comando já retornou o estado novo.
                        # Publica imediatamente no cache do monitoramento
                        # para o 3D mudar de cor sem aguardar o próximo ciclo.
                        try:
                            _live_publish(
                                switch_selecionado,
                                online=True,
                                portas=interpretar_status_todos(
                                    resposta
                                ),
                                erro=None
                            )
                        except Exception:
                            pass

                        registrar_auditoria(
                            "desligar_porta",
                            "sucesso",
                            switch_selecionado,
                            porta_selecionada
                        )

                        mensagem = (

                            "Interface desligada.\n\n"

                            f"Switch: {switch_selecionado}\n"

                            f"Porta: {porta_selecionada}"

                        )

                    finally:

                        if conexao:

                            try:

                                conexao.disconnect()

                            except Exception:

                                pass


                # ligar


                elif operacao == "ligar":

                    conexao = None

                    try:

                        conexao = conectar_switch(

                            switch_selecionado

                        )

                        conexao.send_config_set([

                            f"interface {porta_selecionada}",

                            "no shutdown"

                        ])

                        resposta = conexao.send_command(

                            "show interfaces status",

                            read_timeout=10

                        )

                        status_porta = interpretar_status(

                            resposta,

                            porta_selecionada

                        )

                        painel_switch = montar_painel_switch(

                            conexao,

                            switch_selecionado,

                            portas_visiveis,

                            resposta

                        )


                        # O comando já retornou o estado novo.
                        # Publica imediatamente no cache do monitoramento
                        # para o 3D mudar de cor sem aguardar o próximo ciclo.
                        try:
                            _live_publish(
                                switch_selecionado,
                                online=True,
                                portas=interpretar_status_todos(
                                    resposta
                                ),
                                erro=None
                            )
                        except Exception:
                            pass

                        registrar_auditoria(
                            "ligar_porta",
                            "sucesso",
                            switch_selecionado,
                            porta_selecionada
                        )

                        mensagem = (

                            "Interface ativada.\n\n"

                            f"Switch: {switch_selecionado}\n"

                            f"Porta: {porta_selecionada}"

                        )

                    finally:

                        if conexao:

                            try:

                                conexao.disconnect()

                            except Exception:

                                pass


                # alterar vlan


                elif operacao == "vlan":

                    if not security.role_has_permission(perfil, "vlan.change"):

                        raise PermissionError(

                            "Seu perfil não possui "

                            "permissão para alterar VLAN."

                        )

                    nova_vlan_texto = request.form.get(

                        "nova_vlan",

                        ""

                    )

                    try:

                        nova_vlan = int(nova_vlan_texto)

                    except ValueError:

                        raise ValueError("VLAN inválida.")

                    if nova_vlan not in VLANS:

                        raise ValueError(

                            "Esta VLAN não está "

                            "liberada no SwitchOps."

                        )

                    conexao = None

                    try:

                        conexao = conectar_switch(

                            switch_selecionado

                        )

                        resultado_vlan = alterar_vlan_porta(

                            switch_selecionado,

                            porta_selecionada,

                            nova_vlan,

                            conexao=conexao

                        )

                        resposta = conexao.send_command(

                            "show interfaces status",

                            read_timeout=10

                        )

                        status_porta = interpretar_status(

                            resposta,

                            porta_selecionada

                        )

                        painel_switch = montar_painel_switch(

                            conexao,

                            switch_selecionado,

                            portas_visiveis,

                            resposta

                        )

                        registrar_auditoria(
                            "alterar_vlan",
                            "sucesso",
                            switch_selecionado,
                            porta_selecionada,
                            f"{resultado_vlan['vlan_antiga']} -> "
                            f"{resultado_vlan['vlan_nova']}"
                        )

                        mensagem = (

                            "VLAN alterada.\n\n"

                            f"Switch: {switch_selecionado}\n"

                            f"Porta: {porta_selecionada}\n"

                            f"VLAN anterior: "

                            f"{resultado_vlan['vlan_antiga']}\n"

                            f"Nova VLAN: "

                            f"{resultado_vlan['vlan_nova']} - "

                            f"{resultado_vlan['nome_vlan']}"

                        )

                    finally:

                        if conexao:

                            try:

                                conexao.disconnect()

                            except Exception:

                                pass

            except PermissionError as erro:

                mensagem = (

                    f"Erro: {erro}"

                )

            except Exception as erro:
                app_logger.exception(
                    "Erro ao executar ação de porta."
                )

                mensagem = (
                    "Erro: não foi possível concluir a ação. "
                    "Veja o log técnico do servidor."
                )


        # buscar mac


        elif acao == "buscar_mac":

            if not security.role_has_permission(perfil, "mac.search"):

                mensagem = (

                    "Seu perfil não possui "

                    "permissão para localizar dispositivos."

                )

            else:

                mac_pesquisado = (

                    request.form.get(

                        "mac",

                        ""

                    ).strip()

                )

                try:

                    mac_pesquisado = (

                        mac_cisco(

                            mac_pesquisado

                        )

                    )

                    (

                        resultados_mac,

                        erros

                    ) = buscar_mac_todos(

                        mac_pesquisado

                    )

                    if len(

                        resultados_mac

                    ) == 1:

                        encontrado = (

                            resultados_mac[0]

                        )

                        mensagem = ""

                    elif len(

                        resultados_mac

                    ) > 1:

                        mensagem = ""

                    else:

                        mensagem = ""

                    if erros:

                        print(

                            "[MAC] Erros:",

                            erros

                        )

                except ValueError:

                    mensagem = (

                        "Erro: digite um endereço MAC válido."

                    )

                except Exception:
                    app_logger.exception(
                        "Erro durante a busca de MAC."
                    )

                    mensagem = (
                        "Erro: não foi possível concluir a busca de MAC."
                    )


    # painel visual do switch


    #

    # É consultado DEPOIS das ações. Portanto shutdown,

    # no shutdown e alteração de VLAN já aparecem no painel

    # atualizado na mesma resposta da página.

    #


    if painel_switch is None:

        painel_switch = obter_painel_switch(

            switch_selecionado,

            portas_visiveis

        )


    # render


    pode_buscar_mac = security.role_has_permission(
        perfil,
        "mac.search"
    )

    pode_alterar_vlan = security.role_has_permission(
        perfil,
        "vlan.change"
    )

    pode_administrar_usuarios = security.role_has_permission(
        perfil,
        "system.users"
    )

    return render_template(

        "index.html",

        autenticado=True,

        usuario=atual[

            "usuario"

        ],

        perfil=perfil,
        pode_buscar_mac=pode_buscar_mac,
        pode_alterar_vlan=pode_alterar_vlan,
        pode_administrar_usuarios=pode_administrar_usuarios,

        switches=

            switches_visiveis,

        portas=

            portas_visiveis,

        vlans=

            VLANS,

        painel_switch=

            painel_switch,

        mensagem=

            mensagem,

        status_porta=

            status_porta,

        resultados_mac=

            resultados_mac,

        mac_pesquisado=

            mac_pesquisado,

        switch_selecionado=

            switch_selecionado,

        porta_selecionada=

            porta_selecionada

    )


# monitoramento em tempo quase real
#
# Arquitetura:
#
#   Cisco -> coletor em background -> cache em memória -> SSE -> navegador
#
# A CLI/SSH continua sendo usada para configuração. O monitoramento
# não abre uma conexão nova a cada atualização do navegador.
#
# Cada switch passa a ter, sob demanda, um coletor próprio. O coletor
# fica ativo enquanto houver acesso recente ao stream daquele switch.

LIVE_CACHE = {}
LIVE_LOCK = threading.Lock()
LIVE_THREADS = {}
LIVE_THREAD_LOCK = threading.Lock()

LIVE_PORT_INTERVAL = 1
LIVE_HEALTH_INTERVAL = 9
LIVE_TEMP_INTERVAL = 18
LIVE_IDLE_TIMEOUT = 75


def _live_cache_padrao(nome_switch):
    return {
        "switch": nome_switch,
        "ip": switches[nome_switch]["ip"],
        "online": False,
        "modelo": MODELOS_SWITCH_CACHE.get(
            nome_switch,
            "Cisco Catalyst"
        ),
        "cpu": None,
        "memoria": None,
        "temperatura": None,
        "temperatura_estado": None,
        "uptime": None,
        "portas": [],
        "erro": None,
        "version": 0,
        "updated_at": 0,
        "last_client": time.time()
    }


def _live_touch(nome_switch):
    with LIVE_LOCK:
        if nome_switch not in LIVE_CACHE:
            LIVE_CACHE[nome_switch] = _live_cache_padrao(
                nome_switch
            )

        LIVE_CACHE[nome_switch]["last_client"] = time.time()


def _live_snapshot(nome_switch):
    with LIVE_LOCK:
        dados = LIVE_CACHE.get(
            nome_switch
        )

        if dados is None:
            dados = _live_cache_padrao(
                nome_switch
            )
            LIVE_CACHE[nome_switch] = dados

        # cópia segura para serialização
        return json.loads(
            json.dumps(
                dados,
                ensure_ascii=False
            )
        )


def _live_publish(nome_switch, **campos):
    with LIVE_LOCK:
        if nome_switch not in LIVE_CACHE:
            LIVE_CACHE[nome_switch] = _live_cache_padrao(
                nome_switch
            )

        dados = LIVE_CACHE[nome_switch]
        dados.update(campos)
        dados["updated_at"] = time.time()
        dados["version"] = int(
            dados.get(
                "version",
                0
            )
        ) + 1


def _coletar_portas_live(conexao):
    resposta = conexao.send_command(
        "show interfaces status",
        read_timeout=10
    )

    return interpretar_status_todos(
        resposta
    )


def _coletar_cpu_live(conexao):
    try:
        saida = conexao.send_command(
            "show processes cpu | include CPU utilization",
            read_timeout=7
        )

        return _extrair_percentual_cpu(
            saida
        )

    except Exception:
        return None


def _coletar_memoria_live(conexao):
    try:
        saida = conexao.send_command(
            "show processes memory",
            read_timeout=7
        )

        percentual, _, _ = _extrair_memoria(
            saida
        )

        return percentual

    except Exception:
        return None


def _coletar_uptime_modelo_live(
    conexao,
    nome_switch
):
    uptime = None
    modelo = MODELOS_SWITCH_CACHE.get(
        nome_switch
    )

    try:
        saida = conexao.send_command(
            "show version",
            read_timeout=8
        )

        uptime = _extrair_uptime(
            saida
        )

        if not modelo:
            modelo = obter_modelo_switch(
                conexao,
                nome_switch
            )

    except Exception:
        pass

    return (
        uptime,
        modelo or "Cisco Catalyst"
    )


def _coletar_temperatura_live(conexao):
    comandos = [
        "show environment temperature status",
        "show environment temperature",
        "show environment all",
        "show env all",
        "show env",
        "show platform temperature"
    ]

    for comando in comandos:
        try:
            saida = conexao.send_command(
                comando,
                read_timeout=6
            )

            texto = saida.lower()

            if (
                "invalid input" in texto
                or
                "incomplete command" in texto
                or
                "ambiguous command" in texto
            ):
                continue

            temperatura = _extrair_temperatura(
                saida
            )

            estado = _extrair_estado_temperatura(
                saida
            )

            if (
                temperatura is not None
                or
                estado is not None
            ):
                return (
                    temperatura,
                    estado
                )

        except Exception:
            continue

    return (
        None,
        None
    )


def _live_collector(nome_switch):
    """
    Uma sessão SSH persistente por switch monitorado.

    O coletor executa grupos de comandos em frequências diferentes:
    - portas: ~3 s
    - CPU/memória: ~9 s
    - temperatura: ~18 s

    Se o Dashboard deixar de consumir o stream, a thread se encerra
    e a sessão SSH é fechada.
    """
    conexao = None

    proxima_porta = 0
    proxima_saude = 0
    proxima_temp = 0
    proximo_uptime = 0

    try:
        while True:
            snapshot = _live_snapshot(
                nome_switch
            )

            if (
                time.time()
                - snapshot.get(
                    "last_client",
                    0
                )
                > LIVE_IDLE_TIMEOUT
            ):
                break

            try:
                if (
                    conexao is None
                    or
                    not conexao.is_alive()
                ):
                    if conexao is not None:
                        try:
                            conexao.disconnect()
                        except Exception:
                            pass

                    conexao = conectar_switch(
                        nome_switch
                    )

                    proxima_porta = 0
                    proxima_saude = 0
                    proxima_temp = 0
                    proximo_uptime = 0

                    _live_publish(
                        nome_switch,
                        online=True,
                        erro=None
                    )

                agora = time.time()

                if agora >= proxima_porta:
                    portas = _coletar_portas_live(
                        conexao
                    )

                    _live_publish(
                        nome_switch,
                        online=True,
                        portas=portas,
                        erro=None
                    )

                    proxima_porta = (
                        agora
                        + LIVE_PORT_INTERVAL
                    )

                if agora >= proxima_saude:
                    cpu = _coletar_cpu_live(
                        conexao
                    )

                    memoria = _coletar_memoria_live(
                        conexao
                    )

                    _live_publish(
                        nome_switch,
                        online=True,
                        cpu=cpu,
                        memoria=memoria,
                        erro=None
                    )

                    proxima_saude = (
                        agora
                        + LIVE_HEALTH_INTERVAL
                    )

                if agora >= proxima_temp:
                    (
                        temperatura,
                        temperatura_estado
                    ) = _coletar_temperatura_live(
                        conexao
                    )

                    _live_publish(
                        nome_switch,
                        online=True,
                        temperatura=temperatura,
                        temperatura_estado=
                            temperatura_estado,
                        erro=None
                    )

                    proxima_temp = (
                        agora
                        + LIVE_TEMP_INTERVAL
                    )

                if agora >= proximo_uptime:
                    (
                        uptime,
                        modelo
                    ) = _coletar_uptime_modelo_live(
                        conexao,
                        nome_switch
                    )

                    _live_publish(
                        nome_switch,
                        online=True,
                        uptime=uptime,
                        modelo=modelo,
                        erro=None
                    )

                    proximo_uptime = (
                        agora
                        + 60
                    )

                time.sleep(
                    0.35
                )

            except Exception as erro:
                _live_publish(
                    nome_switch,
                    online=False,
                    erro=str(
                        erro
                    )
                )

                if conexao is not None:
                    try:
                        conexao.disconnect()
                    except Exception:
                        pass

                conexao = None

                time.sleep(
                    3
                )

    finally:
        if conexao is not None:
            try:
                conexao.disconnect()
            except Exception:
                pass

        with LIVE_THREAD_LOCK:
            LIVE_THREADS.pop(
                nome_switch,
                None
            )


def garantir_live_collector(
    nome_switch
):
    _live_touch(
        nome_switch
    )

    with LIVE_THREAD_LOCK:
        thread = LIVE_THREADS.get(
            nome_switch
        )

        if (
            thread is not None
            and
            thread.is_alive()
        ):
            return

        thread = threading.Thread(
            target=_live_collector,
            args=(
                nome_switch,
            ),
            daemon=True,
            name=f"switchops-live-{nome_switch}"
        )

        LIVE_THREADS[
            nome_switch
        ] = thread

        thread.start()


def _live_payload_usuario(
    nome_switch,
    perfil
):
    dados = _live_snapshot(
        nome_switch
    )

    portas_permitidas = set(
        portas_para_usuario(
            perfil,
            nome_switch
        )
    )

    if portas_permitidas:
        dados["portas"] = [
            porta
            for porta in dados.get(
                "portas",
                []
            )
            if porta.get(
                "porta"
            ) in portas_permitidas
        ]
    else:
        dados["portas"] = []

    return dados


@app.route(
    "/api/live-ports/<nome_switch>"
)
def api_live_ports(
    nome_switch
):
    atual = usuario_atual()

    if atual is None:
        return jsonify({
            "ok": False,
            "erro": "Sessão expirada."
        }), 401

    perfil = atual["perfil"]

    if (
        not security.can_access_switch(perfil, nome_switch)
        or nome_switch not in switches
    ):
        return jsonify({
            "ok": False,
            "erro": "Acesso não autorizado."
        }), 403

    garantir_live_collector(nome_switch)

    dados = _live_payload_usuario(
        nome_switch,
        perfil
    )

    return jsonify({
        "ok": True,
        "online": dados.get("online", False),
        "erro": dados.get("erro"),
        "portas": dados.get("portas", []),
        "updated_at": dados.get("updated_at", 0)
    })


@app.route(
    "/api/live/<nome_switch>"
)
def api_live_switch(
    nome_switch
):
    atual = usuario_atual()

    if atual is None:
        return jsonify({
            "ok": False,
            "erro": "Sessão expirada."
        }), 401

    perfil = atual[
        "perfil"
    ]

    if (
        not security.can_access_switch(perfil, nome_switch)
        or
        nome_switch not in switches
    ):
        return jsonify({
            "ok": False,
            "erro": "Acesso não autorizado."
        }), 403

    garantir_live_collector(
        nome_switch
    )

    return jsonify({
        "ok": True,
        **_live_payload_usuario(
            nome_switch,
            perfil
        )
    })


@app.route(
    "/api/live-stream/<nome_switch>"
)
def api_live_stream(
    nome_switch
):
    atual = usuario_atual()

    if atual is None:
        return Response(
            "Sessão expirada.",
            status=401
        )

    perfil = atual[
        "perfil"
    ]

    if (
        not security.can_access_switch(perfil, nome_switch)
        or
        nome_switch not in switches
    ):
        return Response(
            "Acesso não autorizado.",
            status=403
        )

    garantir_live_collector(
        nome_switch
    )

    @stream_with_context
    def gerar():
        ultima_versao = -1

        while True:
            _live_touch(
                nome_switch
            )

            dados = _live_payload_usuario(
                nome_switch,
                perfil
            )

            versao = dados.get(
                "version",
                0
            )

            if versao != ultima_versao:
                ultima_versao = versao

                yield (
                    "event: switch_update\n"
                    "data: "
                    + json.dumps(
                        dados,
                        ensure_ascii=False
                    )
                    + "\n\n"
                )

            else:
                # comentário SSE mantém a conexão viva sem
                # causar atualização visual desnecessária
                yield ": keepalive\n\n"

            time.sleep(
                1
            )

    resposta = Response(
        gerar(),
        mimetype="text/event-stream"
    )

    resposta.headers[
        "Cache-Control"
    ] = "no-cache"

    resposta.headers[
        "X-Accel-Buffering"
    ] = "no"

    return resposta


# api - dashboard / saúde

@app.route(
    "/api/dashboard/<nome_switch>"
)
def api_dashboard(
    nome_switch
):
    atual = usuario_atual()

    if atual is None:
        return jsonify({
            "ok": False,
            "erro": "Sessão expirada."
        }), 401

    perfil = atual[
        "perfil"
    ]

    if (
        not security.can_access_switch(perfil, nome_switch)
    ):
        return jsonify({
            "ok": False,
            "erro": "Acesso não autorizado a este switch."
        }), 403

    if nome_switch not in switches:
        return jsonify({
            "ok": False,
            "erro": "Switch não cadastrado."
        }), 404

    dados = coletar_saude_switch(
        nome_switch
    )

    return jsonify({
        "ok": dados[
            "erro"
        ] is None,
        **dados
    })


# logout


@app.route("/admin/users", methods=["GET", "POST"])
def admin_users():
    atual = usuario_atual()

    if atual is None:
        return redirect(url_for("inicio"))

    perfil = atual["perfil"]

    if not security.role_has_permission(
        perfil,
        "system.users"
    ):
        return redirect(url_for("inicio"))

    mensagem = ""

    if request.method == "POST":
        acao = request.form.get("acao", "")
        username = request.form.get(
            "username",
            ""
        ).strip()

        try:
            if acao == "criar":
                password = request.form.get(
                    "password",
                    ""
                )
                role = request.form.get(
                    "role",
                    ""
                )

                if len(password) < 8:
                    raise ValueError(
                        "A senha precisa ter pelo menos 8 caracteres."
                    )

                security.create_user(
                    username,
                    password,
                    role
                )
                mensagem = "Usuário criado."

            elif acao == "senha":
                password = request.form.get(
                    "password",
                    ""
                )

                if len(password) < 8:
                    raise ValueError(
                        "A senha precisa ter pelo menos 8 caracteres."
                    )

                security.set_password(
                    username,
                    password
                )
                mensagem = "Senha alterada."

            elif acao == "role":
                role = request.form.get(
                    "role",
                    ""
                )
                security.set_role(
                    username,
                    role
                )
                mensagem = "Perfil alterado."

            elif acao == "estado":
                active = (
                    request.form.get(
                        "active"
                    ) == "1"
                )

                if username == atual["usuario"] and not active:
                    raise ValueError(
                        "Você não pode desativar a própria conta enquanto está logado."
                    )

                security.set_active(
                    username,
                    active
                )
                mensagem = "Estado do usuário alterado."

            else:
                raise ValueError(
                    "Ação inválida."
                )

            registrar_auditoria(
                "administrar_usuario",
                "sucesso",
                detalhe=f"{acao}: {username}"
            )

        except Exception as erro:
            mensagem = str(erro)

            app_logger.warning(
                "Falha na administração de usuário: %s",
                erro
            )

    return render_template(
        "admin_users.html",
        users=security.list_users(),
        roles=security.list_roles(),
        mensagem=mensagem
    )

@app.route(

    "/logout"

)

def logout():

    registrar_auditoria(
        "logout",
        "sucesso"
    )

    JUMP_POOL.fechar_ociosas()

    session.clear()

    return redirect(

        url_for(

            "inicio"

        )

    )


# iniciar


if __name__ == "__main__":
    host = os.environ.get(
        "SWITCHOPS_HOST",
        "127.0.0.1"
    )

    port = int(
        os.environ.get(
            "SWITCHOPS_PORT",
            "5000"
        )
    )

    debug = (
        os.environ.get(
            "SWITCHOPS_DEBUG",
            "0"
        ) == "1"
    )

    app.run(
        host=host,
        port=port,
        debug=debug
    )
