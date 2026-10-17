#!/bin/bash
# Ledgerscope daily refresh: rebuild from live DefiLlama, snapshot, push.
cd /Users/jj/Downloads/Code/ledgerscope || exit 1
export PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin
LOG=/tmp/ledgerscope_cron.log
echo "=== $(date) ===" >> "$LOG"
/usr/bin/python3 build.py >> "$LOG" 2>&1
TOKEN=$(/Users/jj/.claude/bin/vault get GITHUB_TOKEN 2>/dev/null)
[ -z "$TOKEN" ] && { echo "no token" >> "$LOG"; exit 1; }
git add -A
git -c user.name="Ledgerscope" -c user.email="noreply@ledgerscope.local" commit -q -m "daily refresh $(date +%F)" >> "$LOG" 2>&1
git push "https://b00831052:${TOKEN}@github.com/b00831052/ledgerscope.git" main >> "$LOG" 2>&1 && echo "pushed" >> "$LOG"
