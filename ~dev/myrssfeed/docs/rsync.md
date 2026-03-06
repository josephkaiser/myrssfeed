# Rsync commands for euler -> markov -> shannon workflow

1. Ship to Prod
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                --exclude='certs/' \
                                --exclude='feeds/' \
                                ~/dev/myrssfeed/ pi@host:~/dev/myrssfeed/
```

