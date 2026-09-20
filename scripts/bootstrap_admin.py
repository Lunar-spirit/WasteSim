"""One-off bootstrap: promote a self-registered user to ADMIN or PLANNER.

Drop 1 has no user-management endpoint (that needs an authenticated ADMIN,
which is a chicken-and-egg problem for the very first account). This script
talks to the database directly, bypassing the API, purely to seed that first
elevated account for local development and the demo script.

    python scripts/bootstrap_admin.py planner.shirva@example.com PLANNER
"""

import asyncio
import sys

from sqlalchemy import select

from app.auth.models import User, UserRole
from app.core.db import AsyncSessionLocal


async def main(email: str, role: str) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No user with email {email}. Register via POST /api/v1/auth/register first.")
            sys.exit(1)
        user.role = UserRole(role)
        await db.commit()
        print(f"{email} is now {role}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("ADMIN", "PLANNER"):
        print("Usage: python scripts/bootstrap_admin.py <email> <ADMIN|PLANNER>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
