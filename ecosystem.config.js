module.exports = {
  apps: [{
    name: 'liebian-bot',
    script: 'main.py',
    cwd: '/www/wwwroot/liebian',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production'
    },
    error_file: '/www/wwwroot/liebian/data/pm2-error.log',
    out_file: '/www/wwwroot/liebian/data/pm2-out.log',
    log_file: '/www/wwwroot/liebian/data/pm2-combined.log',
    time: true
  }]
};
