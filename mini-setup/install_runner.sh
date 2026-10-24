#!/bin/bash
# GeoMetis job runner for the Mac mini (Media-Server.local).
# Run once, in Terminal on the Mac mini:   bash install_runner.sh [path to the shared folder]
# Default shared folder: ~/Geometis-mini
# What it does: installs a small background service (a launchd agent, per user, no admin rights needed)
# that runs any *.sh file placed in <shared folder>/jobs/inbox, one at a time, and writes its output to
# <shared folder>/jobs/logs. It runs as you, only while you are logged in on the mini.
set -euo pipefail

SHARE="${1:-$HOME/Geometis-mini}"
SHARE="$(cd "$SHARE" 2>/dev/null && pwd)" || { echo "Shared folder not found: ${1:-$HOME/Geometis-mini}. Pass its path as the first argument."; exit 1; }
case "$SHARE" in
  */Documents/*|*/Desktop/*|*/Downloads/*)
    echo "The shared folder is inside Documents, Desktop or Downloads. macOS blocks background services there."
    echo "Move it to your home folder (e.g. ~/Geometis-mini), re-share it, and run this again."; exit 1;;
esac
[ "$(uname -m)" = "arm64" ] || echo "Note: expected an Apple Silicon Mac; continuing."

DIR="$HOME/.geometis-runner"
LABEL="co.synapsepartners.geometis-runner"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$DIR" "$HOME/Library/LaunchAgents" "$SHARE"/jobs/{inbox,running,done,failed,logs} "$SHARE/work"

cat > "$DIR/runner.sh" <<RUNNER
#!/bin/bash
# Runs jobs dropped in the inbox, oldest name first, one at a time. launchd never starts a second copy.
SHARE="$SHARE"
J="\$SHARE/jobs"
export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export GEOMETIS_SHARE="\$SHARE"
mkdir -p "\$J"/{inbox,running,done,failed,logs}
echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) \$(scutil --get LocalHostName 2>/dev/null) alive" > "\$J/heartbeat"
while :; do
  f=\$(ls -1 "\$J/inbox"/*.sh 2>/dev/null | sort | head -1)
  [ -z "\$f" ] && break
  n=\$(basename "\$f" .sh)
  if [[ ! "\$n" =~ ^[A-Za-z0-9._-]+\$ ]]; then mv "\$f" "\$J/failed/"; echo "rejected: bad name" > "\$J/logs/\$n.log"; continue; fi
  age=\$(( \$(date +%s) - \$(stat -f %m "\$f") ))
  if [ "\$age" -lt 5 ]; then sleep 5; continue; fi      # still being copied
  mv "\$f" "\$J/running/\$n.sh"
  log="\$J/logs/\$n.log"
  echo "=== \$n started \$(date -u +%Y-%m-%dT%H:%M:%SZ) on \$(scutil --get LocalHostName 2>/dev/null)" > "\$log"
  ( cd "\$SHARE/work" && /bin/bash "\$J/running/\$n.sh" ) >> "\$log" 2>&1
  rc=\$?
  echo "=== \$n exit \$rc at \$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "\$log"
  if [ \$rc -eq 0 ]; then mv "\$J/running/\$n.sh" "\$J/done/"; else mv "\$J/running/\$n.sh" "\$J/failed/"; fi
  echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) \$(scutil --get LocalHostName 2>/dev/null) alive" > "\$J/heartbeat"
done
RUNNER
chmod 700 "$DIR/runner.sh"

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/runner.sh</string></array>
  <key>WatchPaths</key><array><string>$SHARE/jobs/inbox</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/runner.out</string>
  <key>StandardErrorPath</key><string>$DIR/runner.err</string>
</dict></plist>
PL

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

# Self-test job: reports the machine, then the runner moves it to jobs/done.
cat > "$SHARE/jobs/inbox/000-selftest.sh" <<'T'
echo "host: $(scutil --get LocalHostName)"; sw_vers; uname -m
echo "memory GB: $(( $(sysctl -n hw.memsize) / 1073741824 ))"; sysctl -n machdep.cpu.brand_string
df -h "$HOME" | tail -1
echo "homebrew: $(command -v brew || echo 'not installed')"
echo "FileVault: $(fdesetup status)"
pmset -g | grep -E ' sleep|autorestart' || true
T
touch -t 200001010000 "$SHARE/jobs/inbox/000-selftest.sh"

echo
echo "Runner installed: $DIR/runner.sh, service $LABEL"
echo "Shared folder:    $SHARE"
command -v brew >/dev/null && echo "Homebrew:         found" || echo "Homebrew:         NOT found. Install it from https://brew.sh before the next step."
echo "Within a minute, $SHARE/jobs/logs/000-selftest.log should appear."
