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
        // Vault mTLS config — set after Phase 6 (sysadmin) provisions certs
        // VAULT_ADDR: 'http://127.0.0.1:8200',
        // VAULT_ROLE_ID: '',
        // VAULT_SECRET_ID_FILE: '/home/ted/.secrets/temporal-worker-secret-id',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
