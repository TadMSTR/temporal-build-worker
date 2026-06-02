const path = require('path');

module.exports = {
  apps: [
    {
      name: 'temporal-build-worker',
      script: 'worker.py',
      interpreter: path.join(__dirname, 'venv/bin/python3'),
      cwd: __dirname,
      autorestart: true,
      watch: false,
      max_restarts: 10,
      exp_backoff_restart_delay_ms: 5000,
      env: {
        PYTHONUNBUFFERED: '1',
        MATRIX_ROOM: 'sysadmin',
        // SECURITY[accepted]: Vault on loopback HTTP — loopback traffic not reachable externally,
        // consistent with forge accepted-risks baseline. Audit: temporal-mtls-2026-06.
        VAULT_ADDR: 'http://127.0.0.1:8200',
        // SECURITY[info]: role_id is semi-public per Vault AppRole design (analogous to a username).
        // secret_id is the actual credential, stored in VAULT_SECRET_ID_FILE (chmod 600, not in git).
        VAULT_ROLE_ID: '0caa3421-5302-7494-df4a-f6f47fc53478',
        VAULT_SECRET_ID_FILE: '/home/ted/.secrets/temporal-worker-secret-id',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
