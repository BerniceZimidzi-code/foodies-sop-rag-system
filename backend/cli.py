import argparse
import getpass
import re
import sys

from backend.auth import hash_password
from backend.database import create_user, initialize_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Foodies SOP assistant users.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create-user", help="Create a staff or admin account.")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--department", required=True)
    create_parser.add_argument(
        "--role", choices=("staff", "manager", "admin"), required=True
    )
    args = parser.parse_args()

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", args.email):
        parser.error("--email must be a valid email address.")
    if not args.name.strip() or not args.department.strip():
        parser.error("--name and --department must not be blank.")
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12 or len(password) > 256:
        parser.error("Password must be between 12 and 256 characters.")
    if password != confirmation:
        parser.error("Passwords do not match.")

    initialize_database()
    try:
        user_id = create_user(
            email=args.email,
            name=args.name.strip(),
            department=args.department.strip(),
            role=args.role,
            password_hash=hash_password(password),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Created {args.role} user {args.email} (id: {user_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
