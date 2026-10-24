#!/bin/bash
# Removes the GeoMetis job runner from the Mac mini. The shared folder and its contents are left in place.
LABEL="co.synapsepartners.geometis-runner"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/.geometis-runner"
echo "Runner removed."
