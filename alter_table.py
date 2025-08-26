import psycopg2

DB_CONFIG = {
    'host': '177.8.200.12',
    'database': 'Olt',
    'user': 'olt_user132',
    'password': 'yQAZgvodsWSDm25671&&&',
    'port': '5432'
}

sql = "ALTER TABLE ont_data ADD COLUMN IF NOT EXISTS connection_code VARCHAR(50);"

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    print("✅ Coluna criada/verificada com sucesso.")
    cur.close()
    conn.close()
except Exception as e:
    print("❌ Erro:", e)
