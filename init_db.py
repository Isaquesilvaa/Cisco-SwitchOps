import getpass
import os
import sqlite3

from services.security import hash_password


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DB_PATH = os.path.join(
    BASE_DIR,
    "switchops.db"
)


def criar_banco():
    if os.path.exists(DB_PATH):
        resposta = input(
            "switchops.db já existe. Recriar? [s/N]: "
        ).strip().lower()

        if resposta != "s":
            print("Nada alterado.")
            return

        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE roles (
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE permissions (
            code TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE role_permissions (
            role TEXT NOT NULL,
            permission TEXT NOT NULL,
            PRIMARY KEY(role, permission),
            FOREIGN KEY(role)
                REFERENCES roles(name)
                ON DELETE CASCADE,
            FOREIGN KEY(permission)
                REFERENCES permissions(code)
                ON DELETE CASCADE
        );

        CREATE TABLE role_switches (
            role TEXT NOT NULL,
            switch_name TEXT NOT NULL,
            PRIMARY KEY(role, switch_name),
            FOREIGN KEY(role)
                REFERENCES roles(name)
                ON DELETE CASCADE
        );

        CREATE TABLE role_ports (
            role TEXT NOT NULL,
            switch_name TEXT NOT NULL,
            port TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(role, switch_name, port),
            FOREIGN KEY(role)
                REFERENCES roles(name)
                ON DELETE CASCADE
        );

        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
                CHECK(active IN (0,1)),
            created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(role)
                REFERENCES roles(name)
        );
        """
    )

    roles = [
        (
            "operador",
            "Acesso operacional e administração de usuários."
        ),
        (
            "suporte",
            "Operações de porta sem alteração de VLAN."
        ),
        (
            "visualizador",
            "Somente consulta e busca de MAC."
        )
    ]

    permissions = [
        ("dashboard.view", "Visualizar dashboard."),
        ("port.status", "Consultar status de porta."),
        ("port.sticky", "Remover sticky MAC."),
        ("port.shutdown", "Desligar interface."),
        ("port.enable", "Ativar interface."),
        ("vlan.change", "Alterar VLAN de acesso."),
        ("mac.search", "Localizar MAC."),
        ("system.users", "Administrar usuários.")
    ]

    conn.executemany(
        "INSERT INTO roles(name, description) VALUES (?,?)",
        roles
    )

    conn.executemany(
        "INSERT INTO permissions(code, description) VALUES (?,?)",
        permissions
    )

    permission_map = {
        "operador": [
            "dashboard.view",
            "port.status",
            "port.sticky",
            "port.shutdown",
            "port.enable",
            "vlan.change",
            "mac.search",
            "system.users"
        ],
        "suporte": [
            "dashboard.view",
            "port.status",
            "port.sticky",
            "port.shutdown",
            "port.enable"
        ],
        "visualizador": [
            "dashboard.view",
            "port.status",
            "mac.search"
        ]
    }

    for role, codes in permission_map.items():
        conn.executemany(
            """
            INSERT INTO role_permissions(
                role,
                permission
            )
            VALUES (?,?)
            """,
            [
                (role, code)
                for code in codes
            ]
        )

        # "*" significa qualquer switch e qualquer porta.
        conn.execute(
            """
            INSERT INTO role_switches(
                role,
                switch_name
            )
            VALUES (?, '*')
            """,
            (role,)
        )

        conn.execute(
            """
            INSERT INTO role_ports(
                role,
                switch_name,
                port,
                sort_order
            )
            VALUES (?, '*', '*', 0)
            """,
            (role,)
        )

    print()
    print("Crie o primeiro usuário operador.")
    username = input(
        "Usuário [operador]: "
    ).strip() or "operador"

    password = getpass.getpass(
        "Senha: "
    )
    confirm = getpass.getpass(
        "Confirme a senha: "
    )

    if password != confirm:
        conn.close()
        os.remove(DB_PATH)
        raise SystemExit(
            "As senhas não conferem. Banco removido."
        )

    if len(password) < 8:
        conn.close()
        os.remove(DB_PATH)
        raise SystemExit(
            "Use uma senha com pelo menos 8 caracteres."
        )

    conn.execute(
        """
        INSERT INTO users(
            username,
            password_hash,
            role,
            active
        )
        VALUES (?, ?, 'operador', 1)
        """,
        (
            username,
            hash_password(password)
        )
    )

    conn.commit()
    conn.close()

    print()
    print("Banco criado:", DB_PATH)
    print("Primeiro usuário:", username)


if __name__ == "__main__":
    criar_banco()
