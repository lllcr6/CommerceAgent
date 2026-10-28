"""conda run -n CommerceAgent python -m scripts.create_account support1 --role support"""
import argparse
import asyncio
import getpass
from app.auth import password_hash
from app.bootstrap import initialize_service_tables
from app.db.service_models import Account
from app.business_store import seed_orders
import app.db.base as db

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--role", choices=["user", "support", "admin"], default="user")
    args = parser.parse_args()
    if not args.username or len(args.username) > 64:
        parser.error("Username must contain 1–64 characters")
    password = getpass.getpass("Password (at least 8 characters): ")
    if len(password) < 8:
        parser.error("Password must contain at least 8 characters")
    await initialize_service_tables()
    async with db.async_session() as s:
        if await s.get(Account, args.username):
            parser.error("Username already exists")
        s.add(Account(id=args.username, password_hash=password_hash(password), role=args.role))
        await s.flush()
        if args.role == "user":
            await seed_orders(s, args.username)
        await s.commit()
    await db.engine.dispose()
    print(f"Created {args.username} ({args.role})")

if __name__ == "__main__":
    asyncio.run(main())
