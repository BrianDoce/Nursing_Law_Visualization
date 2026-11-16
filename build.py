from pathlib import Path
import duckdb

con = duckdb.connect('nursing.duckdb')
for path in sorted(Path('sql').glob('*.sql')):
    print(f'Running {path}...')
    con.execute(path.read_text())
con.close()
print('Done!')