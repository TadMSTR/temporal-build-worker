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
        VAULT_ADDR: 'http://127.0.0.1:8200',
        VAULT_ROLE_ID: '0caa3421-5302-7494-df4a-f6f47fc53478',
        VAULT_SECRET_ID_FILE: '/home/ted/.secrets/temporal-worker-secret-id',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
