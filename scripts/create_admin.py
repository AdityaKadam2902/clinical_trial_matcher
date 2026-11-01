"""Bootstrap or promote an administrator account.

Usage:
    python scripts/create_admin.py --email admin@example.com
    python scripts/create_admin.py --email admin@example.com --promote
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from clinical_trial_matcher.core.database import AsyncSessionLocal
from clinical_trial_matcher.core.security import hash_password
from clinical_trial_matcher.db.enums import UserRole
from clinical_trial_matcher.db.models.user import User


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--full-name", default="Administrator")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote an existing user instead of failing",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    email = args.email.strip().lower()

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is not None:
            if not args.promote:
                print(f"User {email} already exists. Re-run with --promote to promote.")
                return 1
            existing.role = UserRole.ADMIN.value
            existing.is_active = True
            existing.is_verified = True
            await db.commit()
            print(f"Promoted {email} to admin.")
            return 0

        password = getpass.getpass("Admin password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        if len(password) < 12:
            print("Password must be at least 12 characters.", file=sys.stderr)
            return 1

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=args.full_name,
            role=UserRole.ADMIN.value,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        await db.commit()
        print(f"Created admin {email}.")
        return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
