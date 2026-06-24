"""Apply sql/lily_views_pg.sql to the live warehouse and verify each view.
Creates an isolated, reversible `lily` schema. Zero Anthropic credit."""
import subprocess, psycopg2

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
SQL = r"C:\Users\Brett\agents-playground\sql\lily_views_pg.sql"

token = subprocess.check_output(
    [AZ, "account", "get-access-token", "--resource-type", "oss-rdbms",
     "--query", "accessToken", "-o", "tsv"], text=True).strip()
conn = psycopg2.connect(
    host="billy-ai-postgresql.postgres.database.azure.com",
    dbname="ai-agent-db", user="Ong.KhoiNguyen@evergreengarden.com",
    password=token, sslmode="require")
conn.autocommit = True
cur = conn.cursor()

with open(SQL, encoding="utf-8") as f:
    ddl = f.read()

print("Applying lily_views_pg.sql ...")
try:
    cur.execute(ddl)
    print("  DDL applied OK\n")
except Exception as e:
    print(f"  DDL FAILED: {e}")
    raise

# verify: count rows in every lily view
cur.execute("""
    SELECT table_name FROM information_schema.views
    WHERE table_schema = 'lily' ORDER BY table_name
""")
views = [r[0] for r in cur.fetchall()]
print(f"{len(views)} views in lily schema:\n")
for v in views:
    try:
        cur.execute(f'SELECT count(*) FROM lily."{v}"')
        n = cur.fetchone()[0]
        flag = "  (EMPTY!)" if n == 0 else ""
        print(f"  {v:34s} {n:>12,}{flag}")
    except Exception as e:
        print(f"  {v:34s} ERROR: {str(e)[:80]}")

conn.close()
print("\ndone.")
