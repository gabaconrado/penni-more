# Deployment

Production requires Linux with systemd user services, journald, rootless Podman 4.9 or newer, a
Compose provider, Bash, OpenSSH, rsync, `getent`, `ss`, and at least 1 vCPU and 2 GB RAM. The
deployment account must have lingering enabled and permission to bind ports 80 and 443. Firewall,
SSH hardening, sysctl changes, package installation, and journal retention are host bootstrap tasks;
the scripts never use `sudo`.

Provision `${DEPLOY_REMOTE_DIR}/shared/.env` from `env/production.env.example` with mode `0600`.
Keep it outside releases. Install the systemd files into `~/.config/systemd/user`, update their
working directory if needed, then enable the application service and certificate timer.

Run `./penni-more.sh deploy --dry-run` before deployment. Deployment keeps `current` and `previous`
code releases and exactly one on-host pre-migration database backup. Code rollback does not undo a
migration. Database restoration is intentionally a manual maintenance-window operation and can
discard newer writes. There is no top-level remote restore command and no protection against host
or disk loss.

To restore the retained backup, first announce a maintenance window and record the selected dump
and explicit data-loss approval. On the production host, run the following from the deployment
account. The exact confirmation prevents an accidental paste from reaching the destructive steps:

```bash
cd "${DEPLOY_REMOTE_DIR}/current"
set -a
source shared/.env
source release.env
set +a
compose=(podman compose -p penni-more -f deploy/compose.yaml -f deploy/compose.production.yaml)
restore_dump="${DEPLOY_REMOTE_DIR}/shared/backups/<selected-release>.dump"
test -r "${restore_dump}"

systemctl --user stop penni-more.service
"${compose[@]}" up -d database
"${compose[@]}" exec -T database pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
safety_dump="${DEPLOY_REMOTE_DIR}/shared/backups/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).dump"
"${compose[@]}" exec -T database pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --format=custom >"${safety_dump}"

printf 'Type RESTORE-DATABASE to discard current database writes: '
read -r confirmation
test "${confirmation}" = RESTORE-DATABASE
"${compose[@]}" exec -T database dropdb --force --if-exists \
  -U "${POSTGRES_USER}" "${POSTGRES_DB}"
"${compose[@]}" exec -T database createdb -U "${POSTGRES_USER}" -O "${POSTGRES_USER}" \
  "${POSTGRES_DB}"
"${compose[@]}" exec -T database pg_restore --exit-on-error --no-owner --no-privileges \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <"${restore_dump}"
"${compose[@]}" run --rm server python manage.py migrate --noinput
systemctl --user start penni-more.service
curl --fail --silent --show-error "https://${PENNI_MORE_DOMAIN}/health/live"
```

Verify the internal readiness state and inspect the restored financial data before ending the
maintenance window. Keep the separate safety dump until that verification is complete. Never
automate these steps from `penni-more.sh`.

Bootstrap TLS after DNS points at the server by using the bootstrap Nginx template, then running
the Certbot service once. Start HSTS at 300 seconds and increase it only after renewal is proven.
Neither subdomains nor preload are enabled.
