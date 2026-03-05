# Rsync commands for euler -> markov -> shannon workflow

1. shannon to markov
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                pi@shannon:dev/myrssfeed/ ~/dev/myrssfeed/
```

2. markov to shannon
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                ~/dev/myrssfeed/ pi@shannon:dev/myrssfeed/
```

3. markov to euler
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                ~/dev/myrssfeed/ joe@euler:dev/myrssfeed/
```

4. euler to markov
```bash
rsync -avz --progress \
                                --exclude='.git/' \
                                --exclude='.venv/' \
                                joe@euler:dev/myrssfeed/ ~/dev/myrssfeed/
```
