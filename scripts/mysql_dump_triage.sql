-- MySQL 30-minute dump/high CPU triage.
-- This script is read-only. Run it with an account that can read
-- information_schema, performance_schema, and optionally mysql.slow_log.
--
-- Example:
--   mysql -h <host> -P <port> -u <user> -p < scripts/mysql_dump_triage.sql

SELECT '01_current_time' AS section;
SELECT NOW() AS captured_at, @@hostname AS mysql_host, @@version AS mysql_version;

SELECT '02_processlist_sql_no_cache_dump_log_billing' AS section;
SELECT
  ID,
  USER,
  HOST,
  DB,
  COMMAND,
  TIME,
  STATE,
  LEFT(INFO, 2000) AS INFO
FROM information_schema.PROCESSLIST
WHERE INFO IS NOT NULL
  AND (
    INFO LIKE '%SQL_NO_CACHE%'
    OR INFO LIKE '%dump%'
    OR INFO LIKE '%mysqldump%'
    OR INFO LIKE '%log%'
    OR INFO LIKE '%bill%'
    OR INFO LIKE '%billing%'
  )
ORDER BY TIME DESC;

SELECT '03_long_running_queries' AS section;
SELECT
  ID,
  USER,
  HOST,
  DB,
  COMMAND,
  TIME,
  STATE,
  LEFT(INFO, 2000) AS INFO
FROM information_schema.PROCESSLIST
WHERE COMMAND <> 'Sleep'
ORDER BY TIME DESC
LIMIT 20;

SELECT '04_performance_schema_current_statements' AS section;
SELECT
  t.PROCESSLIST_ID,
  t.PROCESSLIST_USER,
  t.PROCESSLIST_HOST,
  t.PROCESSLIST_DB,
  ROUND(es.TIMER_WAIT / 1000000000000, 3) AS timer_wait_sec,
  es.ROWS_EXAMINED,
  es.ROWS_SENT,
  es.CREATED_TMP_TABLES,
  es.CREATED_TMP_DISK_TABLES,
  LEFT(es.SQL_TEXT, 2000) AS SQL_TEXT
FROM performance_schema.events_statements_current es
JOIN performance_schema.threads t ON t.THREAD_ID = es.THREAD_ID
WHERE es.SQL_TEXT IS NOT NULL
ORDER BY es.TIMER_WAIT DESC
LIMIT 20;

SELECT '05_performance_schema_history_sql_no_cache' AS section;
SELECT
  t.PROCESSLIST_ID,
  t.PROCESSLIST_USER,
  t.PROCESSLIST_HOST,
  t.PROCESSLIST_DB,
  ROUND(es.TIMER_WAIT / 1000000000000, 3) AS timer_wait_sec,
  es.ROWS_EXAMINED,
  es.ROWS_SENT,
  es.CREATED_TMP_TABLES,
  es.CREATED_TMP_DISK_TABLES,
  LEFT(es.SQL_TEXT, 2000) AS SQL_TEXT
FROM performance_schema.events_statements_history_long es
LEFT JOIN performance_schema.threads t ON t.THREAD_ID = es.THREAD_ID
WHERE es.SQL_TEXT LIKE '%SQL_NO_CACHE%'
   OR es.SQL_TEXT LIKE '%dump%'
   OR es.SQL_TEXT LIKE '%mysqldump%'
   OR es.SQL_TEXT LIKE '%bill%'
   OR es.SQL_TEXT LIKE '%billing%'
ORDER BY es.TIMER_WAIT DESC
LIMIT 50;

SELECT '06_enabled_mysql_events' AS section;
SELECT
  EVENT_SCHEMA,
  EVENT_NAME,
  DEFINER,
  STATUS,
  EVENT_TYPE,
  INTERVAL_VALUE,
  INTERVAL_FIELD,
  STARTS,
  ENDS,
  LAST_EXECUTED,
  ON_COMPLETION,
  LEFT(EVENT_DEFINITION, 3000) AS EVENT_DEFINITION
FROM information_schema.EVENTS
WHERE STATUS = 'ENABLED'
  AND (
    INTERVAL_VALUE = 30
    OR EVENT_DEFINITION LIKE '%SQL_NO_CACHE%'
    OR EVENT_DEFINITION LIKE '%dump%'
    OR EVENT_DEFINITION LIKE '%mysqldump%'
    OR EVENT_DEFINITION LIKE '%log%'
    OR EVENT_DEFINITION LIKE '%bill%'
    OR EVENT_DEFINITION LIKE '%billing%'
  )
ORDER BY LAST_EXECUTED DESC, EVENT_SCHEMA, EVENT_NAME;

SELECT '07_event_scheduler_status' AS section;
SHOW VARIABLES LIKE 'event_scheduler';

SELECT '08_slow_log_settings' AS section;
SHOW VARIABLES LIKE 'slow_query_log%';
SHOW VARIABLES LIKE 'long_query_time';
SHOW VARIABLES LIKE 'log_output';

SELECT '09_table_slow_log_recent_if_enabled' AS section;
SELECT
  start_time,
  user_host,
  query_time,
  lock_time,
  rows_sent,
  rows_examined,
  db,
  LEFT(sql_text, 2000) AS sql_text
FROM mysql.slow_log
WHERE start_time >= NOW() - INTERVAL 2 HOUR
  AND (
    sql_text LIKE '%SQL_NO_CACHE%'
    OR sql_text LIKE '%dump%'
    OR sql_text LIKE '%mysqldump%'
    OR sql_text LIKE '%bill%'
    OR sql_text LIKE '%billing%'
  )
ORDER BY start_time DESC
LIMIT 100;

SELECT '10_innodb_buffer_pool_counters' AS section;
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';
SHOW GLOBAL STATUS LIKE 'Innodb_pages_read';
SHOW GLOBAL STATUS LIKE 'Innodb_data_reads';
SHOW GLOBAL STATUS LIKE 'Innodb_data_read';

SELECT '11_recent_high_rows_examined_digest' AS section;
SELECT
  SCHEMA_NAME,
  COUNT_STAR,
  SUM_ROWS_EXAMINED,
  SUM_ROWS_SENT,
  ROUND(SUM_TIMER_WAIT / 1000000000000, 3) AS sum_timer_wait_sec,
  ROUND(AVG_TIMER_WAIT / 1000000000000, 3) AS avg_timer_wait_sec,
  LEFT(DIGEST_TEXT, 2000) AS DIGEST_TEXT
FROM performance_schema.events_statements_summary_by_digest
WHERE DIGEST_TEXT IS NOT NULL
ORDER BY SUM_ROWS_EXAMINED DESC
LIMIT 20;
