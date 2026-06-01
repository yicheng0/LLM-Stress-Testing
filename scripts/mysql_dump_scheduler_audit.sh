#!/usr/bin/env bash
set -u

# Read-only scheduler audit for recurring MySQL dump/log cleanup tasks.
# Run on the host or container where the suspicious MySQL client connection
# originates. The script does not edit crontabs, timers, or Kubernetes objects.

keywords='SQL_NO_CACHE|mysqldump|mysql .*dump|dump|log|billing|bill'

section() {
  printf '\n===== %s =====\n' "$1"
}

run() {
  local label="$1"
  shift
  section "$label"
  "$@" 2>&1 || true
}

section "host"
date
hostname
id

if command -v crontab >/dev/null 2>&1; then
  run "current user crontab" crontab -l
else
  section "current user crontab"
  echo "crontab command not found"
fi

if [ -f /etc/crontab ]; then
  run "/etc/crontab suspicious entries" grep -Eni "$keywords|/30|\*/30" /etc/crontab
fi

if [ -d /etc/cron.d ]; then
  run "/etc/cron.d suspicious entries" grep -REni "$keywords|/30|\*/30" /etc/cron.d
fi

for cron_dir in /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /etc/cron.monthly; do
  if [ -d "$cron_dir" ]; then
    run "$cron_dir listing" ls -la "$cron_dir"
    run "$cron_dir suspicious content" grep -REni "$keywords" "$cron_dir"
  fi
done

if command -v systemctl >/dev/null 2>&1; then
  run "systemd timers" systemctl list-timers --all --no-pager
  run "systemd units suspicious names" systemctl list-units --all --no-pager
fi

if command -v kubectl >/dev/null 2>&1; then
  run "kubernetes cronjobs" kubectl get cronjobs --all-namespaces -o wide
  run "kubernetes cronjob yaml suspicious content" sh -c "kubectl get cronjobs --all-namespaces -o yaml | grep -Eni '$keywords|schedule:'"
fi

for search_dir in /opt /srv /data /app /usr/local/bin /usr/local/sbin; do
  if [ -d "$search_dir" ]; then
    run "$search_dir suspicious scripts" sh -c "find '$search_dir' -maxdepth 4 -type f 2>/dev/null | grep -Ei '\\.(sh|sql|py|pl|conf|env|service|timer)$' | xargs -r grep -HEni '$keywords|SQL_NO_CACHE'"
  fi
done

section "next steps"
cat <<'EOF'
1. Match suspicious job timing with MySQL SHOW FULL PROCESSLIST Host/User.
2. Back up the job definition before changing it.
3. Prefer lowering frequency and adding a non-overlap lock before deleting jobs.
4. Move full dump/export work to a read replica when possible.
EOF
