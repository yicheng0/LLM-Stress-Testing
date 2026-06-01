# MySQL 30 分钟 Dump 高 CPU 排障 Runbook

这个 runbook 用于定位和处置周期性 `SQL_NO_CACHE` dump / 日志清理任务导致的 MySQL CPU 飙升、buffer pool 热数据被冲刷、账单链路被拖慢等问题。

核心判断：

- `SQL_NO_CACHE` 只是不使用 MySQL query cache，不会绕过 InnoDB buffer pool。
- 真正危险的是大表扫描、无索引过滤、一次性导出/删除过大、任务重叠执行，导致 CPU、I/O 和 buffer pool churn 同时升高。
- 默认处置策略是先降频限流，不直接删除任务；只有已经压垮核心链路时才先停止当前查询。
- MySQL 参考：`SQL_NO_CACHE` / query cache、Event Scheduler、`ALTER EVENT`。

## 1. 先止血和留证

如果 CPU 已经打满并影响账单链路：

1. 先保存当前进程和 SQL：

   ```sql
   SHOW FULL PROCESSLIST;
   ```

2. 记录包含 `SQL_NO_CACHE`、`dump`、日志表、账单表的连接：

   - `Id`
   - `User`
   - `Host`
   - `db`
   - `Time`
   - `State`
   - 完整 `Info`

3. 如果确认为当前 dump SQL 正在压垮主库，优先停止查询而不是断开连接：

   ```sql
   KILL QUERY <process_id>;
   ```

4. 不要第一时间删 cron 或 event。先确认任务来源、执行 SQL、业务用途和补偿方式。

## 2. MySQL 取证

使用仓库里的只读 SQL 模板：

```bash
mysql --force -h <host> -P <port> -u <user> -p < scripts/mysql_dump_triage.sql
```

`--force` 用于让取证继续执行：某些环境没有打开 table slow log，或者当前账号没有 `mysql.slow_log` / `performance_schema` 的完整读取权限。

重点看这些结果：

- `processlist`: 是否有长时间运行的 `SQL_NO_CACHE` / dump SQL。
- `performance_schema`: 哪些 SQL 的 `ROWS_EXAMINED`、耗时和发送行数最高。
- `information_schema.EVENTS`: 是否存在每 30 分钟执行一次的 MySQL Event。
- `mysql.slow_log`: 如果慢日志写表，是否每 30 分钟出现一次同类 SQL。
- InnoDB 指标：`buffer_pool_read_requests` 和 `buffer_pool_reads` 是否在 dump 时段异常升高。

拿到 SQL 原文后，对查询执行：

```sql
EXPLAIN FORMAT=JSON <original_select_sql>;
```

如果是清理类 SQL，也要先对它的筛选条件做只读验证：

```sql
EXPLAIN FORMAT=JSON
SELECT id
FROM <table>
WHERE <same_where_condition>
ORDER BY id
LIMIT 1000;
```

## 3. 定位任务来源

### MySQL Event

如果 `SHOW FULL PROCESSLIST` 里的用户类似 `event_scheduler`，优先检查 MySQL Event：

```sql
SELECT
  EVENT_SCHEMA,
  EVENT_NAME,
  STATUS,
  INTERVAL_VALUE,
  INTERVAL_FIELD,
  STARTS,
  LAST_EXECUTED,
  EVENT_DEFINITION
FROM information_schema.EVENTS
WHERE STATUS = 'ENABLED'
  AND (
    INTERVAL_VALUE = 30
    OR EVENT_DEFINITION LIKE '%SQL_NO_CACHE%'
    OR EVENT_DEFINITION LIKE '%dump%'
  )
ORDER BY LAST_EXECUTED DESC;
```

备份定义：

```sql
SHOW CREATE EVENT `<db_name>`.`<event_name>`;
```

### Linux cron / systemd / Kubernetes

在疑似任务机器上运行调度审计脚本：

```bash
bash scripts/mysql_dump_scheduler_audit.sh
```

这个脚本只读取常见调度位置：

- `/etc/crontab`
- `/etc/cron.d/*`
- 当前用户 `crontab -l`
- systemd timers
- Kubernetes CronJob
- 常见脚本目录中的 `mysql`、`mysqldump`、`SQL_NO_CACHE`、`dump`、`log` 关键字

如果连接来源是业务账号或备份账号，并且 `Host` 是固定机器，优先到那台机器查 cron、systemd timer、容器任务和调度平台。

## 4. 降频限流

默认不要直接删除任务，按下面顺序处置。

### MySQL Event 降频

可参考模板文件：

```bash
less scripts/mysql_dump_mitigation_templates.sql
```

先把 30 分钟改为低峰 6 小时执行一次：

```sql
SHOW CREATE EVENT `<db_name>`.`<event_name>`;

ALTER EVENT `<db_name>`.`<event_name>`
ON SCHEDULE EVERY 6 HOUR
STARTS '2026-06-02 02:00:00';
```

如果要临时暂停：

```sql
ALTER EVENT `<db_name>`.`<event_name>` DISABLE;
```

如果 Event 可能重叠执行，给事件体加单实例锁：

```sql
BEGIN
  SELECT GET_LOCK('dump_log_cleanup_lock', 0) INTO @got_lock;

  IF @got_lock = 1 THEN
    -- original dump or cleanup SQL here
    DO RELEASE_LOCK('dump_log_cleanup_lock');
  END IF;
END;
```

### Linux cron 降频

保留原命令注释，改成低峰执行，并加防重入和低优先级：

```cron
# Original: */30 * * * * /opt/jobs/mysql_dump_cleanup.sh
0 2,8,14,20 * * * flock -n /tmp/mysql_dump_cleanup.lock nice -n 10 ionice -c2 -n7 /opt/jobs/mysql_dump_cleanup.sh
```

如果是 systemd timer，设置低峰或更长周期，并确认：

```bash
systemctl cat <timer_name>
systemctl list-timers --all | grep -i '<timer_name>'
```

### SQL 批量化

清理类任务不要一次删除大范围数据。优先按主键或时间窗口小批量执行：

```sql
DELETE FROM <log_table>
WHERE id BETWEEN <start_id> AND <end_id>
  AND created_at < NOW() - INTERVAL 7 DAY
LIMIT 1000;
```

导出类任务优先迁到只读副本。如果必须在主库跑：

- 限制时间窗口。
- 按主键分页。
- 每批之间 sleep。
- 避开账单高峰。
- 为过滤条件补必要索引。

## 5. 验证

调整前记录：

- CPU 和 load average。
- QPS / TPS。
- 慢 SQL 数量和最慢 SQL。
- `Rows_examined`。
- `Innodb_buffer_pool_read_requests`。
- `Innodb_buffer_pool_reads`。
- 账单接口延迟和错误率。

调整后至少观察两个原周期，例如原来 30 分钟一次，就观察 60 分钟以上：

- CPU 不再每 30 分钟尖峰。
- 没有多个 dump SQL 重叠执行。
- 慢日志不再集中出现同类 SQL。
- buffer pool physical reads 不再在任务时段异常抬升。
- dump / 日志清理产物数量、时间范围和业务预期一致。

## 6. 最终建议

- `SQL_NO_CACHE` 不是根因，根因通常是扫描范围和调度策略。
- 主库不适合长期跑全量 dump；导出任务应迁到只读副本或离线链路。
- 日志清理优先使用分区表的 `DROP PARTITION` / `TRUNCATE PARTITION`，其次小批量删除。
- 定时任务必须有防重入机制、批量上限、低峰调度和可观测指标。
