-- MySQL dump/log cleanup mitigation templates.
-- Replace placeholders before use. Keep SHOW CREATE EVENT output in the
-- incident record before running ALTER EVENT.
--
-- These templates are intentionally not runnable as-is.

-- 1. Back up the current event definition.
SHOW CREATE EVENT `<db_name>`.`<event_name>`;

-- 2. Lower a 30-minute event to a low-traffic 6-hour cadence.
ALTER EVENT `<db_name>`.`<event_name>`
ON SCHEDULE EVERY 6 HOUR
STARTS '2026-06-02 02:00:00';

-- 3. Temporarily pause an event when it is actively harming production.
ALTER EVENT `<db_name>`.`<event_name>` DISABLE;

-- 4. Resume the event after SQL and scheduling changes are verified.
ALTER EVENT `<db_name>`.`<event_name>` ENABLE;

-- 5. Event-body pattern for preventing overlapping executions.
-- Put the original dump or cleanup SQL inside the locked block.
/*
CREATE EVENT `<db_name>`.`<event_name>`
ON SCHEDULE EVERY 6 HOUR
STARTS '2026-06-02 02:00:00'
DO
BEGIN
  SELECT GET_LOCK('dump_log_cleanup_lock', 0) INTO @got_lock;

  IF @got_lock = 1 THEN
    -- original dump or cleanup SQL here
    DO RELEASE_LOCK('dump_log_cleanup_lock');
  END IF;
END;
*/

-- 6. Read-only EXPLAIN template for SELECT-style dump SQL.
EXPLAIN FORMAT=JSON
SELECT <columns>
FROM `<db_name>`.`<table_name>`
WHERE <same_where_condition>
ORDER BY `<primary_key>`
LIMIT 1000;

-- 7. Small-batch cleanup template.
-- Repeat in controlled batches from an external job, with a short sleep
-- between batches and a hard max runtime.
DELETE FROM `<db_name>`.`<log_table>`
WHERE `<primary_key>` BETWEEN <start_id> AND <end_id>
  AND `created_at` < NOW() - INTERVAL 7 DAY
LIMIT 1000;
