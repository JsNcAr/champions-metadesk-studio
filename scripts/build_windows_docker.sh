#!/usr/bin/env bash
# Helper script to build Windows .exe using Docker on Linux

set -e

echo "🐳 Building Windows executable using Docker (Wine + Python 3.13)..."

# Ensure output directory exists
mkdir -p dist

# Build Docker image
docker build -f Dockerfile.windows -t pcpt-windows-builder .

# Run container and export dist/PokemonChampionsPlanningTool.exe
docker run --rm -v "$(pwd)/dist:/output:z" pcpt-windows-builder

echo "✅ Windows build complete! Executable located at: dist/PokemonChampionsPlanningTool.exe"
