#!/usr/bin/env bash
# Install what `flet build linux` needs on this machine: Flutter's Linux desktop toolchain.
# Flutter itself (~2 GB) is installed by the first `flet build ... --yes` into ~/flutter.
#
#   scripts/flet_build_prereqs.sh          show what would be installed (nothing changes)
#   scripts/flet_build_prereqs.sh --yes    install it (asks for sudo)
set -euo pipefail

INSTALL=0
[[ "${1:-}" == "--yes" ]] && INSTALL=1

if command -v zypper >/dev/null 2>&1; then
  MANAGER=zypper
  PACKAGES=(clang cmake ninja pkgconf gtk3-devel xz-devel gcc-c++ libstdc++-devel git unzip curl which)
  have() { rpm -q --whatprovides "$1" >/dev/null 2>&1; }
  exists() { zypper --non-interactive --quiet search --match-exact "$1" >/dev/null 2>&1; }
  install() { sudo zypper --non-interactive install "$@"; }
elif command -v apt-get >/dev/null 2>&1; then
  MANAGER=apt
  PACKAGES=(clang cmake ninja-build pkg-config libgtk-3-dev liblzma-dev libstdc++-12-dev git unzip curl)
  have() { dpkg -s "$1" >/dev/null 2>&1; }
  exists() { apt-cache show "$1" >/dev/null 2>&1; }
  install() { sudo apt-get update && sudo apt-get install -y "$@"; }
elif command -v dnf >/dev/null 2>&1; then
  MANAGER=dnf
  PACKAGES=(clang cmake ninja-build pkgconf-pkg-config gtk3-devel xz-devel gcc-c++ libstdc++-devel git unzip curl which)
  have() { rpm -q --whatprovides "$1" >/dev/null 2>&1; }
  exists() { dnf info "$1" >/dev/null 2>&1; }
  install() { sudo dnf install -y "$@"; }
else
  echo "No zypper, apt or dnf found. Install Flutter's Linux prerequisites by hand:"
  echo "  https://docs.flutter.dev/get-started/install/linux/desktop"
  exit 1
fi

missing=() unknown=()
for pkg in "${PACKAGES[@]}"; do
  if have "$pkg"; then
    echo "  ok       $pkg"
  elif exists "$pkg"; then
    echo "  missing  $pkg"; missing+=("$pkg")
  else
    echo "  ?        $pkg (no package with this name on this system: look for its equivalent)"; unknown+=("$pkg")
  fi
done

if (( ${#missing[@]} == 0 )); then
  echo "Everything flet build needs is installed (${MANAGER})."
elif (( INSTALL )); then
  install "${missing[@]}"
else
  echo
  echo "To install the missing packages:  scripts/flet_build_prereqs.sh --yes"
fi
(( ${#unknown[@]} == 0 )) || echo "Not found by name: ${unknown[*]} — tell me the package names your system uses."
