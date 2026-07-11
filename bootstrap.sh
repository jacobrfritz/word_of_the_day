#!/bin/bash
# bootstrap.sh: entrypoint script for word_of_the_day Docker container

set -e

# 1. Export container runtime environment variables to /etc/environment
# This ensures that cron tasks inherit any environment variables (like API keys, host, port, db path)
# passed to the container at startup.
echo "Exporting environment variables for cron..."
printenv | grep -v -E "no_proxy|PWD|OLDPWD" >> /etc/environment || true

# 2. Write the daily cron job configuration to /etc/cron.d/word-generator
# Standard system crontabs under /etc/cron.d/ require specifying the user (root).
# The schedule is set to run at midnight (0 0 * * *).
# The output is redirected to the stdout and stderr of the main container process (PID 1)
# so that the output of the daily word generation is visible in container/Docker logs.
echo "Creating daily word generation cron job at midnight Central Time..."
cat << 'EOF' > /etc/cron.d/word-generator
0 0 * * * root /app/.venv/bin/word_of_the_day --mode auto >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF

# Ensure proper permissions for the cron configuration file
# System-wide cron configuration files must be owned by root, not writable by group/others,
# and contain a trailing newline to be correctly parsed by cron daemon.
chmod 0644 /etc/cron.d/word-generator

# 3. Start the cron daemon in the background
echo "Starting cron daemon..."
service cron start

# 4. Handle CLI arguments gracefully.
# If the first argument looks like a flag/option (starts with a hyphen),
# prepend the default executable 'word_of_the_day' to run the CLI.
if [ "${1#-}" != "$1" ]; then
    set -- word_of_the_day "$@"
fi

# Execute the final container command
echo "Executing: $@"
exec "$@"
