"""Full warehouse schema dump: columns, types, row counts, PK/FK, sample rows.
Writes a markdown report to sql/SCHEMA_DUMP.md. Costs zero Anthropic credit.
"""
import subprocess, psycopg2, datetime

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
OUT = r"C:\Users\Brett\agents-playground\sql\SCHEMA_DUMP.md"
SCHEMA = "warehouse"

token = subprocess.check_output(
    [AZ, "account", "get-access-token", "--resource-type", "oss-rdbms",
     "--query", "accessToken", "-o", "tsv"], text=True).strip()

conn = psycopg2.connect(
    host="billy-ai-postgresql.postgres.database.azure.com",
    dbname="ai-agent-db",
    user="Ong.KhoiNguyen@evergreengarden.com",
    password=token, sslmode="require")
cur = conn.cursor()

out = [f"# Warehouse schema dump\n\n> Generated {datetime.datetime.now():%Y-%m-%d %H:%M} "
       f"against `billy-ai-postgresql` / `ai-agent-db` / `{SCHEMA}`\n"]

# list warehouse tables
cur.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = %s ORDER BY table_name
""", (SCHEMA,))
tables = [r[0] for r in cur.fetchall()]
out.append(f"**{len(tables)} tables in `{SCHEMA}`:** " + ", ".join(f"`{t}`" for t in tables) + "\n")

for t in tables:
    fq = f"{SCHEMA}.{t}"
    out.append(f"\n---\n\n## `{fq}`\n")

    # row count
    try:
        cur.execute(f'SELECT count(*) FROM "{SCHEMA}"."{t}"')
        n = cur.fetchone()[0]
    except Exception as e:
        n = f"ERR: {e}"
        conn.rollback()
    out.append(f"**Rows:** {n}\n")

    # columns
    cur.execute("""
        SELECT column_name, data_type, is_nullable, character_maximum_length, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (SCHEMA, t))
    cols = cur.fetchall()
    out.append("\n| # | column | type | null | detail |")
    out.append("|---|---|---|---|---|")
    for i, (name, typ, nullable, clen, nprec, nscale) in enumerate(cols, 1):
        detail = ""
        if clen: detail = f"len {clen}"
        elif nprec: detail = f"({nprec},{nscale})"
        out.append(f"| {i} | `{name}` | {typ} | {nullable} | {detail} |")

    # primary key
    cur.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema=%s AND tc.table_name=%s
        ORDER BY kcu.ordinal_position
    """, (SCHEMA, t))
    pk = [r[0] for r in cur.fetchall()]
    if pk:
        out.append(f"\n**PK:** ({', '.join(pk)})")

    # foreign keys
    cur.execute("""
        SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=%s AND tc.table_name=%s
    """, (SCHEMA, t))
    fks = cur.fetchall()
    if fks:
        out.append("\n**FKs:**")
        for col, fs, ft, fc in fks:
            out.append(f"- `{col}` → `{fs}.{ft}.{fc}`")

    # sample rows (3)
    try:
        cur.execute(f'SELECT * FROM "{SCHEMA}"."{t}" LIMIT 3')
        sample = cur.fetchall()
        colnames = [d[0] for d in cur.description]
        if sample:
            out.append("\n**Sample rows:**\n")
            out.append("| " + " | ".join(colnames) + " |")
            out.append("|" + "|".join("---" for _ in colnames) + "|")
            for row in sample:
                cells = [str(v).replace("\n", " ")[:40] if v is not None else "" for v in row]
                out.append("| " + " | ".join(cells) + " |")
    except Exception as e:
        out.append(f"\n_sample failed: {e}_")
        conn.rollback()

report = "\n".join(out) + "\n"
with open(OUT, "w", encoding="utf-8") as f:
    f.write(report)

conn.close()
print(f"Wrote {OUT}")
print(f"{len(tables)} tables dumped.")
