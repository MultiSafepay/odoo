#!/usr/bin/env bash

# Exit if any command fails
set -eo pipefail

RELEASE_VERSION=$1
RELEASE_FOLDER=".dist"
OUTPUT_FOLDER="multisafepay"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If tag is not supplied, latest tag is used
if [ -z "$RELEASE_VERSION" ]; then
  RELEASE_VERSION=$(git describe --tags --abbrev=0)
fi

echo "Creating release for version: $RELEASE_VERSION"

# Remove old release folder
rm -rf "$RELEASE_FOLDER"
mkdir -p "$RELEASE_FOLDER/$OUTPUT_FOLDER"

# Find all directories that don't start with '.'
for dir in "$SCRIPT_DIR"/*/; do
  dir_name=$(basename "$dir")

  # Skip hidden directories (starting with .)
  if [[ "$dir_name" == .* ]]; then
    continue
  fi

  echo "Adding directory: $dir_name"
  cp -r "$dir" "$RELEASE_FOLDER/$OUTPUT_FOLDER/$dir_name"
done

# Create the zip file
cd "$RELEASE_FOLDER"
zip -9 -r "${OUTPUT_FOLDER}_${RELEASE_VERSION}.zip" "$OUTPUT_FOLDER"

# Clean up the temporary folder
rm -rf "$OUTPUT_FOLDER"

echo "Release created: $RELEASE_FOLDER/${OUTPUT_FOLDER}_${RELEASE_VERSION}.zip"
