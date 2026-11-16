"""Data tests for the staging layer. Each query counts rows that break a rule; 0 means pass."""
import sys
import duckdb

RAW = "read_csv('data/pbj_daily_nurse_staffing.csv', types = {'PROVNUM': 'VARCHAR', 'COUNTY_FIPS': 'VARCHAR', 'WorkDate': 'VARCHAR'})"

TESTS = {
    # must pass: a failure means the pipeline or the join key is broken
    "no rows lost or added in staging":
        f"SELECT abs((SELECT count(*) FROM stg_staffing) - (SELECT count(*) FROM {RAW}))",
    "one row per facility per day":
        "SELECT count(*) FROM (SELECT ccn, work_date FROM stg_staffing GROUP BY 1, 2 HAVING count(*) > 1)",
    "provider number present and 6 characters":
        "SELECT count(*) FROM stg_staffing WHERE ccn IS NULL OR length(ccn) <> 6",
    "date present and inside a single quarter":
        "SELECT CASE WHEN count(*) FILTER (WHERE work_date IS NULL) > 0 "
        "OR count(DISTINCT date_trunc('quarter', work_date)) > 1 THEN 1 ELSE 0 END FROM stg_staffing",
    "census present and not negative":
        "SELECT count(*) FROM stg_staffing WHERE census IS NULL OR census < 0",
    "hours present and not negative":
        "SELECT count(*) FROM stg_staffing WHERE rn_hours IS NULL OR lpn_hours IS NULL OR aide_hours IS NULL "
        "OR rn_hours < 0 OR lpn_hours < 0 OR aide_hours < 0",
    "total equals RN + LPN + aide":
        "SELECT count(*) FROM stg_staffing WHERE abs(total_hours - (rn_hours + lpn_hours + aide_hours)) > 0.01",
    "employee + contract hours equal the reported total (source check)":
        f"SELECT count(*) FROM {RAW} WHERE abs(Hrs_RN - (Hrs_RN_emp + Hrs_RN_ctr)) > 0.01 "
        "OR abs(Hrs_LPN - (Hrs_LPN_emp + Hrs_LPN_ctr)) > 0.01 OR abs(Hrs_CNA - (Hrs_CNA_emp + Hrs_CNA_ctr)) > 0.01",
}

WARNINGS = {
    # expected to be non-zero: report the number, then decide how the marts treat these rows
    "days with zero census": "SELECT count(*) FROM stg_staffing WHERE flag_zero_census",
    "days with residents but zero nurse hours": "SELECT count(*) FROM stg_staffing WHERE flag_zero_hours",
    "days above 12 hours per resident": "SELECT count(*) FROM stg_staffing WHERE flag_implausible_hours",
    "facilities missing days in the quarter":
        "SELECT count(*) FROM (SELECT ccn FROM stg_staffing GROUP BY 1 "
        "HAVING count(*) < (SELECT count(DISTINCT work_date) FROM stg_staffing))",
}

con = duckdb.connect("nursing.duckdb", read_only=True)
failed = 0
for name, sql in TESTS.items():
    n = con.execute(sql).fetchone()[0]
    failed += n > 0
    print(f"{'PASS' if n == 0 else 'FAIL'}  {name}" + ("" if n == 0 else f"  ({n:,} rows)"))
for name, sql in WARNINGS.items():
    print(f"INFO  {name}: {con.execute(sql).fetchone()[0]:,}")
con.close()
sys.exit(1 if failed else 0)
