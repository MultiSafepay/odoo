#!/usr/bin/env bash

# Exit if any command fails
set -eo pipefail

RELEASE_VERSION=$1
REPOSITORY_SRC="src"
FILENAME_PREFIX="payment_multisafepay_official_"
FOLDER_PREFIX="payment_multisafepay_official"
RELEASE_FOLDER=".dist"

# If tag is not supplied, latest tag is used
if [ -z "$RELEASE_VERSION" ]
then
  RELEASE_VERSION=$(git describe --tags --abbrev=0)
fi

# Remove old folder
rm -rf "$RELEASE_FOLDER"

# Get the release via git archive
mkdir "$RELEASE_FOLDER"
git archive --format zip -9 --prefix="$FOLDER_PREFIX"/ --output "$RELEASE_FOLDER"/"$FILENAME_PREFIX""$RELEASE_VERSION".zip "$RELEASE_VERSION"

cd "$RELEASE_FOLDER"
unzip "$FILENAME_PREFIX""$RELEASE_VERSION".zip -d "$REPOSITORY_SRC"

# Change directory to the extracted folder
mv "$REPOSITORY_SRC"/"$FOLDER_PREFIX"/"$FOLDER_PREFIX" ./"$FOLDER_PREFIX"

# Remove the archive zip file
rm "$FILENAME_PREFIX""$RELEASE_VERSION".zip
rm -rf "$REPOSITORY_SRC"

# Zip everything
zip -9 -r "$FILENAME_PREFIX""$RELEASE_VERSION".zip "$FOLDER_PREFIX"

# Remove the remaining directory
rm -rf "$FOLDER_PREFIX"
