#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py

# Create the LangGraph checkpointer's own tables. Kept out of the app startup
# because it is DDL and several workers would race on it.
#
# Outside ENVIRONMENT=local this branch is never taken: Settings refuses to
# load without a valid CHECKPOINT_ENCRYPTION_KEY, so the app has already failed
# by now. Locally the key is optional and no checkpoint is ever written --
# build_serde() raises without a key, so nothing can land unencrypted.
if [ -n "${CHECKPOINT_ENCRYPTION_KEY}" ]; then
    python -m app.checkpoint_pre_start
else
    echo "本地环境未配置 CHECKPOINT_ENCRYPTION_KEY，跳过 checkpoint 建表。"
fi
