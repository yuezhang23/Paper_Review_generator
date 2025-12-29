import psycopg
from dotenv import dotenv_values

config = dotenv_values(".env")
year = 2023
conference = 'NeurIPS'
# with psycopg.connect("dbname=iclr_reviews user=postgres password=pass host=db port=5432") as conn:
with psycopg.connect(config["DB_CONFIG"]) as conn:
    with conn.cursor() as cur:
        # Drop tables if they exist (in correct order due to foreign key constraint)
        cur.execute(f"DROP TABLE IF EXISTS reviews_{year}_{conference} CASCADE;")
        cur.execute(f"DROP TABLE IF EXISTS metareviews_{year}_{conference} CASCADE;")
        
        cur.execute(f"""
                CREATE TABLE metareviews_{year}_{conference} (
                id VARCHAR(25) PRIMARY KEY,
                decision TEXT,
                comment TEXT NULL
            );""")
        cur.execute(f"""
                CREATE TABLE reviews_{year}_{conference} (
                s_id VARCHAR(25) REFERENCES metareviews_{year}_{conference}(id),
                id VARCHAR(25) PRIMARY KEY,
                summary TEXT NULL, 
                soundness TEXT NULL, 
                presentation TEXT NULL,
                contribution TEXT NULL,
                strengths TEXT NULL,
                weaknesses TEXT NULL,
                questions TEXT NULL,
                limitations TEXT NULL, 
                rating TEXT NULL,
                confidence TEXT NULL,
                rebuttal TEXT NULL,
                decision TEXT NULL
                );""")
        conn.commit()