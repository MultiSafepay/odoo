#!/usr/bin/env bash
# Exit if any command fails
set -eo pipefail

RELEASE_VERSION=$1
RELEASE_FOLDER=".dist"
ZIP_NAME="payment_multisafepay_${RELEASE_VERSION}.zip"

# If tag is not supplied, use string "HEAD" or git describe
if [ -z "$RELEASE_VERSION" ]; then
    RELEASE_VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "HEAD")
    ZIP_NAME="payment_multisafepay_${RELEASE_VERSION}.zip"
fi

echo "Building release for version: $RELEASE_VERSION"

# Clean up old build folder
rm -rf "$RELEASE_FOLDER"
mkdir -p "$RELEASE_FOLDER"

# Create a temporary working directory
TEMP_DIR="$RELEASE_FOLDER/temp"
mkdir -p "$TEMP_DIR"

# Archive the source code from the specified version/tag
# We use tar to piping to avoid creating an intermediate zip of the whole repo
git archive --format=tar "$RELEASE_VERSION" | tar -x -C "$TEMP_DIR"

# Navigate to temp dir to zip relative paths
pushd "$TEMP_DIR" > /dev/null

# Zip the two module directories
# we check if they exist to avoid errors if the structure is different in the tag
if [ -d "payment_multisafepay" ] && [ -d "payment_multisafepay_enhaced" ]; then
    zip -9 -r "../$ZIP_NAME" payment_multisafepay payment_multisafepay_enhaced
else
    echo "Error: Module directories not found in archive content."
    ls -la
    exit 1
fi

popd > /dev/null

# Clean up temp dir
rm -rf "$TEMP_DIR"

echo "Successfully created $RELEASE_FOLDER/$ZIP_NAME"
