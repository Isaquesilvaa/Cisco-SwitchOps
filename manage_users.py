import argparse
import getpass
import os
import sqlite3

from services.security import SecurityStore


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

security = SecurityStore(
    os.path.join(
        BASE_DIR,
        "switchops.db"
    )
)


def cmd_list(_args):
    rows = security.list_users()

    if not rows:
        print("Nenhum usuário cadastrado.")
        return

    print(
        f"{'USUARIO':<22} "
        f"{'PERFIL':<15} "
        f"{'ATIVO':<7} "
        "CRIADO"
    )

    print("-" * 72)

    for row in rows:
        print(
            f"{row['username']:<22} "
            f"{row['role']:<15} "
            f"{'sim' if row['active'] else 'não':<7} "
            f"{row['created_at']}"
        )


def cmd_roles(_args):
    for role in security.list_roles():
        print(
            f"\n[{role['name']}] "
            f"{role['description']}"
        )

        print(
            "  Permissões: "
            + (
                ", ".join(role["permissions"])
                or "-"
            )
        )

        print(
            "  Switches: "
            + (
                ", ".join(role["switches"])
                or "-"
            )
        )


def read_password(prompt="Senha: "):
    password = getpass.getpass(prompt)
    confirm = getpass.getpass(
        "Confirme: "
    )

    if password != confirm:
        raise SystemExit(
            "As senhas não conferem."
        )

    if len(password) < 8:
        raise SystemExit(
            "Use pelo menos 8 caracteres."
        )

    return password


def cmd_create(args):
    security.create_user(
        args.username,
        read_password(),
        args.role
    )

    print(
        "Usuário criado. "
        "A senha foi armazenada apenas como hash."
    )


def cmd_password(args):
    security.set_password(
        args.username,
        read_password("Nova senha: ")
    )

    print("Senha atualizada.")


def cmd_role(args):
    security.set_role(
        args.username,
        args.role
    )

    print("Perfil atualizado.")


def cmd_state(args):
    security.set_active(
        args.username,
        args.state == "enable"
    )

    print("Estado do usuário atualizado.")


parser = argparse.ArgumentParser(
    description=(
        "Administração de usuários e RBAC "
        "do SwitchOps."
    )
)

sub = parser.add_subparsers(
    required=True
)

p = sub.add_parser(
    "list",
    help="Lista usuários."
)
p.set_defaults(
    func=cmd_list
)

p = sub.add_parser(
    "roles",
    help="Lista roles e permissões."
)
p.set_defaults(
    func=cmd_roles
)

p = sub.add_parser(
    "create",
    help="Cria usuário."
)
p.add_argument("username")
p.add_argument("role")
p.set_defaults(
    func=cmd_create
)

p = sub.add_parser(
    "password",
    help="Troca senha."
)
p.add_argument("username")
p.set_defaults(
    func=cmd_password
)

p = sub.add_parser(
    "role",
    help="Troca perfil."
)
p.add_argument("username")
p.add_argument("role")
p.set_defaults(
    func=cmd_role
)

p = sub.add_parser(
    "state",
    help="Ativa/desativa usuário."
)
p.add_argument("username")
p.add_argument(
    "state",
    choices=[
        "enable",
        "disable"
    ]
)
p.set_defaults(
    func=cmd_state
)

args = parser.parse_args()

try:
    args.func(args)
except (
    ValueError,
    sqlite3.IntegrityError
) as exc:
    raise SystemExit(str(exc))
