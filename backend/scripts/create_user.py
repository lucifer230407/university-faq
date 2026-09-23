"""Create/update a user in the `users` collection.

Usage (from backend/):
    python -m scripts.create_user --username alice --password 's3cret' [--name Alice] [--role user]

The env-defined ADMIN_USERNAME/ADMIN_PASSWORD admin is always available and
does not need to be created via this script.
"""
import argparse
import getpass

from app.services.auth import create_user, get_user, users


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an app login user.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", default=None, help="Omit to prompt safely.")
    parser.add_argument("--name", default="")
    parser.add_argument("--role", default="user", choices=["user", "admin"])
    parser.add_argument(
        "--update-password",
        action="store_true",
        help="If the user exists, replace the stored password hash.",
    )
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")

    existing = get_user(args.username)
    if existing:
        if not args.update_password or existing.get("env_admin"):
            raise SystemExit(
                f"User {args.username!r} already exists. Use --update-password to rotate "
                "its password (env admin passwords are managed in .env)."
            )
        users().update_one(
            {"username": args.username},
            {"$set": {"name": args.name or args.username, "role": args.role}},
        )
        from app.services.auth import hash_password

        users().update_one(
            {"username": args.username},
            {"$set": {"password_hash": hash_password(password)}},
        )
        print(f"Updated password for {args.username!r}.")
        return

    create_user(args.username, password, name=args.name, role=args.role)
    print(f"Created user {args.username!r} (role={args.role}).")


if __name__ == "__main__":
    main()