import os
import shutil
import subprocess
import sys


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

CONFIG_DIR = os.path.join(
    BASE_DIR,
    "config"
)


def copiar_se_nao_existe(nome):
    destino = os.path.join(
        CONFIG_DIR,
        nome
    )

    origem = os.path.join(
        CONFIG_DIR,
        nome.replace(
            ".json",
            ".example.json"
        )
    )

    if os.path.exists(destino):
        print(nome, "já existe.")
        return

    shutil.copyfile(
        origem,
        destino
    )

    print(
        nome,
        "criado a partir do exemplo."
    )


os.makedirs(
    CONFIG_DIR,
    exist_ok=True
)

copiar_se_nao_existe(
    "switches.json"
)

copiar_se_nao_existe(
    "vlans.json"
)

db_path = os.path.join(
    BASE_DIR,
    "switchops.db"
)

if not os.path.exists(db_path):
    subprocess.run(
        [
            sys.executable,
            os.path.join(
                BASE_DIR,
                "init_db.py"
            )
        ],
        check=True
    )
else:
    print(
        "switchops.db já existe."
    )

print()
print("Configuração inicial pronta.")
print(
    "Agora edite config/switches.json "
    "e config/vlans.json."
)
