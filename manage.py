#!/usr/bin/env python3
import sys
import argparse

from backend.app import app
from backend.extensions import db
from backend.auth_models import User


def cmd_set_admin(email: str, make_admin: bool) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email.lower().strip()).first()
        if not user:
            print(f"User not found: {email}")
            return 1
        user.is_admin = bool(make_admin)
        db.session.commit()
        print(f"Updated is_admin={user.is_admin} for {user.email}")
        return 0


def cmd_create_user(email: str, password: str, is_admin: bool) -> int:
    with app.app_context():
        existing = User.query.filter_by(email=email.lower().strip()).first()
        if existing:
            print(f"User already exists: {email}")
            return 1
        user = User(email=email.lower().strip())
        user.set_password(password)
        user.is_admin = bool(is_admin)
        db.session.add(user)
        db.session.commit()
        print(f"Created user {user.email} (admin={user.is_admin})")
        return 0


def cmd_list_users() -> int:
    with app.app_context():
        users = User.query.order_by(User.id.asc()).all()
        if not users:
            print("No users found.")
            return 0
        for u in users:
            role = "admin" if u.is_admin else "user"
            print(f"{u.id}\t{u.email}\t{role}")
        return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set_admin = sub.add_parser("set-admin", help="Set or unset admin flag for a user")
    p_set_admin.add_argument("--email", required=True, help="User email")
    group = p_set_admin.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", action="store_true", help="Grant admin")
    group.add_argument("--off", action="store_true", help="Revoke admin")

    p_create = sub.add_parser("create-user", help="Create a user")
    p_create.add_argument("--email", required=True, help="User email")
    p_create.add_argument("--password", required=True, help="User password")
    p_create.add_argument("--admin", action="store_true", help="Create as admin")

    sub.add_parser("list-users", help="List all users")

    args = parser.parse_args(argv)

    if args.command == "set-admin":
        return cmd_set_admin(args.email, args.on)
    if args.command == "create-user":
        return cmd_create_user(args.email, args.password, args.admin)
    if args.command == "list-users":
        return cmd_list_users()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


