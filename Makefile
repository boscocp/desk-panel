# Entry point for humans, CI and agents alike. Every target exits non-zero on failure.
DC := docker compose -f docker/compose.yml run --rm build

.PHONY: help wave-start check lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-ci-hygiene lint-selftests test-server test-web test-android connected build apk contract e2e clean

help:
	@echo "wave-start    fetch, prove main is current, cut BRANCH=wave/NN-slug"
	@echo "check         run everything that does not need the phone"
	@echo "test-server   python unittest"
	@echo "test-web      node:test"
	@echo "test-android  gradle JVM unit tests (container)"
	@echo "build apk     assemble the debug APK (container)"
	@echo "contract      hit the real upstream APIs (network, opt-in)"
	@echo "connected     Espresso tests on the phone (container + host adb)"
	@echo "e2e           full end-to-end, needs the phone on adb"
	@echo "lint-tasks    every acceptance criterion is a command with an exit code"
	@echo "lint-notes    every finished wave left a note in docs/harness-notes/"
	@echo "lint-status   STATUS.md and tasks/*.md still agree"
	@echo "lint-permissions  .claude/settings.json and reasonix.toml are still twins"
	@echo "lint-workflow ci.yml runs the same commands these targets do"
	@echo "lint-ci-hygiene  permissions, SHA pins, concurrency, dependabot"
	@echo "lint-selftests  every scripts/*.py that has a --self-test runs it"
	@echo "clean         remove build output"

# The first command of a wave, and the only one that talks to the network
# before any code is written. Two waves have been rebuilt from scratch on a
# `main` that had already shipped them -- PR #30 and PR #31 -- because the git
# status a session opens with is a snapshot that reads as current when it is
# not. "git fetch before you branch" was written in CLAUDE.md after the first
# and did not stop the second, so it is a command with an exit code now.
#
# It refuses rather than fast-forwarding on its own: a `main` that cannot be
# fast-forwarded means local commits nobody asked about, and moving it is a
# decision, not a step.
wave-start:
	@test -n "$(BRANCH)" || { echo "usage: make wave-start BRANCH=wave/NN-slug"; exit 2; }
	git fetch --quiet origin
	git switch main
	git merge --ff-only origin/main
	python scripts/check_branch_base.py
	git switch -c "$(BRANCH)"
	@echo
	@echo "Read this before writing anything -- it is the wave's prompt:"
	@grep -n -m1 '^## Resuming after' tasks/STATUS.md

check: lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-ci-hygiene lint-selftests test-server test-web test-android

lint-tasks:
	python scripts/check_acceptance.py

lint-notes:
	python scripts/check_harness_notes.py

lint-status:
	python scripts/check_status.py

lint-permissions:
	python scripts/check_permission_parity.py

# Both halves: the rules are checked against ci.yml, and the rules are
# checked against themselves.
lint-workflow:
	python scripts/check_workflow.py --self-test
	python scripts/check_workflow.py

# Runs against this checkout, so the properties hold before the push rather
# than after a runner says so. Its own rules are checked by lint-selftests.
lint-ci-hygiene:
	python scripts/check_ci_hygiene.py

# A self-test no target invokes is a test suite with no runner. after_update.py
# had one, nothing ran it, and it was red on Linux from the day it was written
# while every wave was judged on Windows (TT.12). Discovery is by grep over a
# glob, never a list: the next script to grow a --self-test is covered by being
# written, which a list would not do.
#
# It greps for the *quoted* flag, which is how a script that parses one spells
# it. A bare `--self-test` also matches a docstring that merely documents the
# flag, and such a script would then be run with an argument it does not
# understand -- after which its exit code says whatever its argv handling
# happens to say, which is not a self-test result. The cost is that an
# implementation spelling it '--self-test' in single quotes is missed; this
# repo writes double. Found by review.
SELFTESTS := $(shell grep -l '"--self-test"' scripts/*.py)

# No backslash continuations in this recipe, deliberately. This worktree is
# CRLF, and a backslash followed by CR is not a line join, so make would run
# each line in its own shell and the target would die on its own error message
# with every script still unrun. The committed blob is LF, so a clone and CI
# never see it -- which is exactly what makes it worth removing. Found by review.
lint-selftests:
	@# discovery is a glob over scripts/, never a list of names
	@test -n "$(SELFTESTS)" || { echo "lint-selftests: nothing carries a --self-test"; exit 1; }
	@for s in $(SELFTESTS); do echo "--> $$s --self-test"; python "$$s" --self-test || exit 1; done

test-server:
	python -m unittest discover -s server/tests -t .

test-web:
	node --test "web/test/**/*.test.js"

test-android:
	$(DC) ./gradlew test

build apk:
	$(DC) ./gradlew assembleDebug

# Gradle runs in the container; adb runs on the host. The container reaches the
# host's adb server over TCP instead of owning the USB device - see TT.7.
connected:
	adb start-server
	$(DC) ./gradlew connectedAndroidTest -PadbHost=host.docker.internal

contract:
	RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . -p "contract_*.py"

e2e:
	python e2e/run_e2e.py

clean:
	$(DC) ./gradlew clean
	rm -rf out
