"""Crea (o promociona) un usuario admin en TinyDB.

POST /users siempre registra usuarios con role `user`; este script es la vía para
tener el primer admin.

Uso (desde la raíz del repo):
    uv run python -m services.api.create_admin admin@trackflow.com 'una-contraseña-larga' [--name "Nombre"]
"""

import argparse
import sys

from pydantic import ValidationError

from services.api import user_service
from services.api.user_models import UserCreate, UserRole


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o promociona un usuario admin.")
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()

    existing = user_service.get_user_by_email(args.email)
    if existing is not None:
        user_service.update_user(existing["id"], {"role": UserRole.ADMIN, "is_active": True})
        print(f"Usuario {existing['email']} promocionado a admin (id {existing['id']}).")
        return

    try:
        body = UserCreate(email=args.email, password=args.password, name=args.name)
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    user, _ = user_service.create_user(
        email=body.email,
        password=body.password,
        role=UserRole.ADMIN,
        profile={"name": body.name},
    )
    print(f"Admin {user['email']} creado (id {user['id']}).")


if __name__ == "__main__":
    main()
