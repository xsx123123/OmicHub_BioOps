#!/bin/sh
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DOCKER_SOCKET="/var/run/docker.sock"
DOCKER_SOCKET_GID=""

if [ -S "$DOCKER_SOCKET" ]; then
  DOCKER_SOCKET_GID="$(stat -c '%g' "$DOCKER_SOCKET")"
fi

run_as_worker() {
  if [ -n "$DOCKER_SOCKET_GID" ]; then
    setpriv --reuid "$PUID" --regid "$PGID" --groups "$DOCKER_SOCKET_GID" -- "$@"
  else
    setpriv --reuid "$PUID" --regid "$PGID" --clear-groups -- "$@"
  fi
}

if [ "$#" -eq 1 ] && [ "$1" = "bash" ] && [ -t 0 ] && [ -t 1 ]; then
  set -- zsh
fi

prepare_directory() {
  directory="$1"
  mkdir -p "$directory"
  if [ "$(id -u)" -eq 0 ]; then
    chown "$PUID:$PGID" "$directory"
  fi
}

for directory in \
  /data/cygnusx/.cache \
  /data/cygnusx/.conda_envs \
  /data/cygnusx/.mamba \
  /data/cygnusx/logs/app \
  /data/cygnusx/logs/celery/tasks \
  /data/cygnusx/logs/snakemake \
  /tmp/cygnusx-home
do
  prepare_directory "$directory"
done

if [ "$(id -u)" -eq 0 ]; then
  run_as_worker sh -c '
    for directory do
      probe="$directory/.cygnusx-write-test-$$"
      touch "$probe"
      rm -f "$probe"
    done
  ' sh \
    /data/cygnusx/.cache \
    /data/cygnusx/.conda_envs \
    /data/cygnusx/.mamba \
    /data/cygnusx/logs/app \
    /data/cygnusx/logs/celery/tasks \
    /data/cygnusx/logs/snakemake \
    /tmp/cygnusx-home
  if [ -n "$DOCKER_SOCKET_GID" ]; then
    exec setpriv --reuid "$PUID" --regid "$PGID" --groups "$DOCKER_SOCKET_GID" -- \
      env HOME="$HOME" LOGNAME=cygnusx USER=cygnusx "$@"
  fi
  exec setpriv --reuid "$PUID" --regid "$PGID" --clear-groups -- \
    env HOME="$HOME" LOGNAME=cygnusx USER=cygnusx "$@"
fi

exec "$@"
