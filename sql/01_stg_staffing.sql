CREATE OR REPLACE TABLE stg_staffing AS
WITH src AS (
    SELECT *
    FROM read_csv('data/pbj_daily_nursing_staffing.csv', types={'PROVNUM': 'VARCHAR', 'COUNTY_FIPS': 
    'VARCHAR', 'WorkDate': 'VARCHAR'})
),
