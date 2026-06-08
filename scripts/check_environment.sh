#!/usr/bin/env bash

set -u

checks=(
  "git:git --version"
  "Python:python3 --version"
  "Node.js:node --version"
  "npm:npm --version"
  "Docker:docker --version"
)

printf '%s\n' "AI trading workstation environment check"
printf '%s\n' "========================================"

for check in "${checks[@]}"; do
  name="${check%%:*}"
  command="${check#*:}"
  executable="${command%% *}"

  if command -v "$executable" >/dev/null 2>&1; then
    printf '[INSTALLED] %s\n' "$name"
    $command
  else
    printf '[MISSING] %s\n' "$name"
  fi
done

if grep -qi microsoft /proc/version 2>/dev/null; then
  printf '[INSTALLED] WSL environment detected\n'
else
  printf '[MISSING] WSL environment not detected\n'
fi
