"""Quick test: connect to Azure Postgres and list tables."""
import subprocess, sys, psycopg2

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
token = subprocess.check_output(
    [AZ, "account", "get-access-token",
     "--resource-type", "oss-rdbms",
     "--query", "accessToken", "-o", "tsv"],
    text=True,
).strip()

print(f"Token OK ({len(token)} chars)")

conn = psycopg2.connect(
    host="billy-ai-postgresql.postgres.database.azure.com",
    dbname="ai-agent-db",
    user="Ong.KhoiNguyen@evergreengarden.com",
    password=token,
    sslmode="require",
)
print("CONNECTED!")

cur = conn.cursor()
cur.execute("""
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog','information_schema')
    ORDER BY 1, 2
""")
rows = cur.fetchall()
print(f"\n{len(rows)} tables/views found:")
for schema, name in rows:
    print(f"  {schema}.{name}")

conn.close()
