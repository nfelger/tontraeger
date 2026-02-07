#!/bin/bash
# Usage: ./sync.sh [local_directory] remote_user@remote_host:remote_directory
#
# This script rsyncs your local directory with a remote directory over SSH,
# excluding any files that are ignored by your .gitignore.
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

# Run rsync over SSH, using .gitignore rules to skip ignored files/directories.
rsync -a --filter=':- .gitignore' --compress --verbose --partial -e ssh "$LOCAL_DIR" "$REMOTE_LOCATION"
