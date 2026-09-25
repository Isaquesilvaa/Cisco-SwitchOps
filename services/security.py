import base64
import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path


PBKDF2_ITERATIONS = 390_000


def hash_password(password):
    salt = secrets.token_bytes(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS
    )

    return (
        "pbkdf2_sha256"
        f"${PBKDF2_ITERATIONS}"
        f"${base64.b64encode(salt).decode('ascii')}"
        f"${base64.b64encode(digest).decode('ascii')}"
    )


def check_password(password_hash, password):
    try:
        algorithm, iterations, salt_b64, digest_b64 = (
            password_hash.split("$", 3)
        )

        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations)
        )

        return hmac.compare_digest(
            actual,
            expected
        )

    except Exception:
        return False


PERMISSION_BY_OPERATION = {
    "status": "port.status",
    "sticky": "port.sticky",
    "desligar": "port.shutdown",
    "ligar": "port.enable",
    "vlan": "vlan.change",
}


class SecurityStore:
    def __init__(self, db_path):
        self.db_path = str(Path(db_path))

    def _connect(self):
        conn = sqlite3.connect(
            self.db_path,
            timeout=10
        )

        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        return conn

    def authenticate(self, username, password):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    username,
                    password_hash,
                    role,
                    active
                FROM users
                WHERE username = ?
                """,
                (username,)
            ).fetchone()

        if not row or not row["active"]:
            return None

        if not check_password(
            row["password_hash"],
            password
        ):
            return None

        return {
            "usuario": row["username"],
            "perfil": row["role"],
        }

    def role_exists(self, role):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM roles
                WHERE name = ?
                """,
                (role,)
            ).fetchone()

        return row is not None

    def role_has_permission(
        self,
        role,
        permission
    ):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM role_permissions
                WHERE
                    role = ?
                    AND permission = ?
                """,
                (
                    role,
                    permission
                )
            ).fetchone()

        return row is not None

    def allowed_switches(
        self,
        role,
        available_switches=None
    ):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT switch_name
                FROM role_switches
                WHERE role = ?
                ORDER BY switch_name
                """,
                (role,)
            ).fetchall()

        names = [
            row["switch_name"]
            for row in rows
        ]

        if (
            "*" in names
            and available_switches is not None
        ):
            return list(available_switches)

        return [
            name
            for name in names
            if name != "*"
        ]

    def can_access_switch(
        self,
        role,
        switch_name
    ):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM role_switches
                WHERE
                    role = ?
                    AND (
                        switch_name = ?
                        OR switch_name = '*'
                    )
                """,
                (
                    role,
                    switch_name
                )
            ).fetchone()

        return row is not None

    def has_all_ports(
        self,
        role,
        switch_name
    ):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM role_ports
                WHERE
                    role = ?
                    AND (
                        switch_name = ?
                        OR switch_name = '*'
                    )
                    AND port = '*'
                """,
                (
                    role,
                    switch_name
                )
            ).fetchone()

        return row is not None

    def allowed_ports(
        self,
        role,
        switch_name
    ):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT port
                FROM role_ports
                WHERE
                    role = ?
                    AND (
                        switch_name = ?
                        OR switch_name = '*'
                    )
                    AND port <> '*'
                ORDER BY sort_order, port
                """,
                (
                    role,
                    switch_name
                )
            ).fetchall()

        return [
            row["port"]
            for row in rows
        ]

    def validate_operation(
        self,
        role,
        switch_name,
        port,
        operation
    ):
        if not self.role_exists(role):
            raise PermissionError(
                "Perfil inválido."
            )

        if not self.can_access_switch(
            role,
            switch_name
        ):
            raise PermissionError(
                "Seu perfil não possui acesso a este switch."
            )

        permission = PERMISSION_BY_OPERATION.get(
            operation
        )

        if permission is None:
            raise PermissionError(
                "Operação inválida."
            )

        if not self.role_has_permission(
            role,
            permission
        ):
            raise PermissionError(
                "Seu perfil não possui permissão para esta operação."
            )

        if not self.has_all_ports(
            role,
            switch_name
        ):
            if port not in self.allowed_ports(
                role,
                switch_name
            ):
                raise PermissionError(
                    "Seu perfil não possui acesso a esta interface."
                )

    # --------------------------------------------------------
    # Administração usada pelo manage_users.py
    # --------------------------------------------------------
    def list_users(self):
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT
                    username,
                    role,
                    active,
                    created_at
                FROM users
                ORDER BY username
                """
            ).fetchall()

    def create_user(
        self,
        username,
        password,
        role,
        active=True
    ):
        if not self.role_exists(role):
            raise ValueError(
                f"Perfil inexistente: {role}"
            )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users(
                    username,
                    password_hash,
                    role,
                    active
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    hash_password(password),
                    role,
                    1 if active else 0
                )
            )

    def set_password(
        self,
        username,
        password
    ):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE username = ?
                """,
                (
                    hash_password(password),
                    username
                )
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Usuário não encontrado."
                )

    def set_role(
        self,
        username,
        role
    ):
        if not self.role_exists(role):
            raise ValueError(
                f"Perfil inexistente: {role}"
            )

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET role = ?
                WHERE username = ?
                """,
                (
                    role,
                    username
                )
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Usuário não encontrado."
                )

    def set_active(
        self,
        username,
        active
    ):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET active = ?
                WHERE username = ?
                """,
                (
                    1 if active else 0,
                    username
                )
            )

            if cursor.rowcount == 0:
                raise ValueError(
                    "Usuário não encontrado."
                )

    def list_roles(self):
        with self._connect() as conn:
            roles = conn.execute(
                """
                SELECT
                    name,
                    description
                FROM roles
                ORDER BY name
                """
            ).fetchall()

            output = []

            for role in roles:
                permissions = conn.execute(
                    """
                    SELECT permission
                    FROM role_permissions
                    WHERE role = ?
                    ORDER BY permission
                    """,
                    (role["name"],)
                ).fetchall()

                switches = conn.execute(
                    """
                    SELECT switch_name
                    FROM role_switches
                    WHERE role = ?
                    ORDER BY switch_name
                    """,
                    (role["name"],)
                ).fetchall()

                output.append({
                    "name": role["name"],
                    "description": role["description"],
                    "permissions": [
                        item["permission"]
                        for item in permissions
                    ],
                    "switches": [
                        item["switch_name"]
                        for item in switches
                    ]
                })

        return output
