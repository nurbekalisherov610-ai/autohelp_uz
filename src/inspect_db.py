import asyncio
from sqlalchemy import text
from src.db.session import engine

async def inspect_db():
    async with engine.connect() as conn:
        # Check users table columns
        res = await conn.execute(text("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'users';
        """))
        print("\n--- USERS TABLE ---")
        for row in res:
            print(f"Column: {row[0]}, Type: {row[1]}, UDT: {row[2]}")
            
        # Check orders table columns
        res = await conn.execute(text("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'orders';
        """))
        print("\n--- ORDERS TABLE ---")
        for row in res:
            print(f"Column: {row[0]}, Type: {row[1]}, UDT: {row[2]}")

if __name__ == "__main__":
    asyncio.run(inspect_db())
