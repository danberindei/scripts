#!/bin/bash
# Script to find and disable DNF repositories with no installed packages
# Prompts ONCE for confirmation before disabling all unused repos

set -e

REPO_DIR="/etc/yum.repos.d"

echo "Scanning enabled DNF repositories..."

# Get all enabled repo IDs
mapfile -t REPOIDS < <(dnf repolist --enabled -q | awk 'NR>1 {print $1}')

if [ ${#REPOIDS[@]} -eq 0 ]; then
    echo "No enabled repositories found."
    exit 0
fi

for REPOID in "${REPOIDS[@]}"; do
    PKGS=$(dnf repoquery --installed-from-repo="$REPOID" | head)
    if [ -z "$PKGS" ]; then
        FILE=$(grep -l "^\[$REPOID\]" "$REPO_DIR"/*.repo)
        if [ -z "$FILE" ]; then
            echo "Repo $REPOID not found in $REPO_DIR. Skipping."
            continue
        fi
        echo "No installed packages from repo: $REPOID ($FILE)"
        read -p "Disable repo $REPOID in $FILE? [y/N] " CONFIRM
        if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
            sudo dnf config-manager setopt "$REPOID.enabled=0"
            echo "Repo $REPOID disabled."
        else
            echo "Repo $REPOID left enabled."
        fi
    fi

    done

echo "Done."
