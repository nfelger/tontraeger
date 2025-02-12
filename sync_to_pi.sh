#!/bin/bash
# Usage: ./sync.sh [local_directory] remote_user@remote_host:remote_directory
#
# This script rsyncs your local directory with a remote directory over SSH,
# excluding any files that are ignored by your .gitignore.
#
# It uses process substitution to generate an exclude list from:
#   git ls-files -i --exclude-standard
#
# Example:
#   ./sync.sh . user@remote:/path/to/destination

# Check arguments
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 [local_directory] remote_user@remote_host:remote_directory"
    exit 1
fi

# Determine local directory and remote location
if [ "$#" -eq 2 ]; then
    LOCAL_DIR="$1"
    REMOTE_LOCATION="$2"
else
    # If only one argument, assume current directory as local folder.
    LOCAL_DIR="."
    REMOTE_LOCATION="$1"
fi

# Ensure we are inside a Git repository
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "Error: This script must be run from within a Git repository."
    exit 1
fi

# Run rsync over SSH.
rsync -a --exclude-from=<(git ls-files --others --ignored --exclude-standard) --compress --verbose --partial -e ssh "$LOCAL_DIR" "$REMOTE_LOCATION" 
