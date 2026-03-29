module.exports = {
  apps: [
    {
      name: 'helm-temporal-worker',
      script: 'worker.py',
      interpreter: '/home/ted/repos/personal/helm-temporal-worker/venv/bin/python3',
      cwd: '/home/ted/repos/personal/helm-temporal-worker',
      autorestart: true,
      watch: false,
      max_restarts: 10,
      exp_backoff_restart_delay_ms: 5000,
      env: {
        PYTHONUNBUFFERED: '1',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
