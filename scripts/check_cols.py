import duckdb
con = duckdb.connect()
df = con.execute("DESCRIBE SELECT * FROM 'sports-engine/data/gold/odds_pattern_dataset_42k.parquet'").df()
print(df[["column_name", "column_type"]].to_string())
