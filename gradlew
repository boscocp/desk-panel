#!/bin/sh
# Thin delegator: the real Gradle wrapper and project live in android/
# (see tasks/T2.1-gradle-project.md). This lets `./gradlew` work from the
# repository root, which is what the Makefile and CI expect, without a
# second copy of the wrapper jar.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR/android"
exec ./gradlew "$@"
