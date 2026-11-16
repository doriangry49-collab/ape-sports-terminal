import duckdb
con = duckdb.connect()
cols = con.execute("DESCRIBE SELECT * FROM 'sports-engine/data/gold/ground_truth_matches_42k.parquet'").df()
print(cols[['column_name', 'column_type']].to_string())

