# Rsync commands for euler -> markov -> shannon workflow

1. Stop the running service first so SQLite and Python files are not updated underneath a live process
```bash
ssh joe@shannon 'sudo systemctl stop myrssfeed'
```

2. Ship to Prod
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                --exclude='node_modules/' \
                                --exclude='__pycache__/' \
                                --exclude='.pycache_compile/' \
                                --exclude='.DS_Store' \
                                --exclude='certs/' \
                                --exclude='feeds/' \
                                --exclude='logs/' \
                                ~/dev/myrssfeed/ joe@shannon:~/prod/myrssfeed/
```

3. Reinstall dependencies if needed and restart the service
```bash
ssh joe@shannon 'cd ~/prod/myrssfeed && ./install.sh'
```

4. If the page still fails, inspect the latest service traceback directly
```bash
ssh joe@shannon 'sudo journalctl -u myrssfeed -n 120 --no-pager'
```
