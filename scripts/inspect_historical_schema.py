import duckdb
con = duckdb.connect()
df = con.execute("SELECT * FROM 'sports-engine/data/gold/ground_truth_matches_42k.parquet' LIMIT 2").df()
print("Columns count:", len(df.columns))
print("Columns list:", df.columns.tolist()[:30])
print("\nSample row:")
print(df.iloc[0].to_dict())

