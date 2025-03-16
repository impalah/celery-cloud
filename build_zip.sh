#!/bin/bash

# -----------------------------------------------------------------------------
# Builds a zip lambda image
# -----------------------------------------------------------------------------

# Requires: sudo apt update && sudo apt install -y libcurl4-openssl-dev libssl-dev zlib1g-dev zip

# Declare variables
BASE_VERSION="0.1.0"
PLATFORM="x86_64-manylinux2014"
PYTHON_VERSION="3.12"

# Create dist folder
mkdir -p dist/build

# Delete old files
rm -rf dist/build/*
rm -f dist/*.zip
rm -f dist/*.txt

uv export --frozen --no-dev --no-editable -o dist/requirements.txt
uv pip install --no-installer-metadata --no-compile-bytecode --python-platform ${PLATFORM} --python ${PYTHON_VERSION} --target dist/build -r dist/requirements.txt
cd dist/build
zip -r ../package.${BASE_VERSION}.zip .
