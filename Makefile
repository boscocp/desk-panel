# Entry point for humans, CI and agents alike. Every target exits non-zero on failure.
DC := docker compose -f docker/compose.yml run --rm build

.PHONY: help wave-start check hooks lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-ci-hygiene lint-selftests lint-links lint-requirements lint-commits test-server test-web test-android connected build apk contract e2e clean

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
	@echo "lint-links    every Markdown link resolves (local half; CI does the remote one)"
	@echo "lint-requirements  docs/REQUIREMENTS.md still matches what the build pins"
	@echo "lint-commits  the last thirty commit subjects fit the convention"
	@echo "hooks         install .githooks (commit-msg checks the message shape)"
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
	@# Before the merge, where `main` is still the stale thing this session
	@# opened on -- this is the call that names what it was about to miss.
	python scripts/check_branch_base.py --report
	git merge --ff-only origin/main
	@# After it, as a post-condition. Only allowed to be green.
	python scripts/check_branch_base.py
	git switch -c "$(BRANCH)"
	@echo
	@echo "Read this before writing anything -- it is the wave's prompt:"
	@grep -n -m1 '^## Resuming after' tasks/STATUS.md

check: lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-ci-hygiene lint-selftests lint-links lint-requirements lint-commits test-server test-web test-android

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
#
# Two directories, because the glob used to be one and server/verify_login_scope.py
# -- 97 autostart-parser cases, the only way macOS is checkable from this desk --
# was a --self-test no target invoked (T10.3). Still a glob per directory and
# never a list of names: the next script to grow one is covered by being written.
#
# e2e/ is deliberately not here. e2e/layout/'s checks drive Firefox over
# Marionette and exit 2 without a browser, and keeping them outside `make check`
# is a documented decision; a glob reaching e2e/ would make `make check` need a
# browser the day somebody adds a --self-test there. Widen again, directory by
# directory, when a third one grows a self-test that is safe here.
SELFTESTS := $(shell grep -l '"--self-test"' scripts/*.py server/*.py)

# No backslash continuations in this recipe, deliberately. This worktree is
# CRLF, and a backslash followed by CR is not a line join, so make would run
# each line in its own shell and the target would die on its own error message
# with every script still unrun. The committed blob is LF, so a clone and CI
# never see it -- which is exactly what makes it worth removing. Found by review.
lint-selftests:
	@# discovery is a glob over scripts/, never a list of names
	@test -n "$(SELFTESTS)" || { echo "lint-selftests: nothing carries a --self-test"; exit 1; }
	@for s in $(SELFTESTS); do echo "--> $$s --self-test"; python "$$s" --self-test || exit 1; done

# Every Markdown file in the repository, the historical record included: a
# link rots the same whether a contributor or a future session follows it.
MARKDOWN := README.md CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md $(wildcard docs/*.md) $(wildcard docs/adr/*.md) $(wildcard docs/harness-notes/*.md) $(wildcard tasks/*.md) e2e/README.md e2e/layout/README.md

# The subset a reader actually follows. CI checks these *with* the network;
# `make check` does not, and the difference is deliberate twice over:
#
#   - `make check` is the command that has to work on a train. A guard that
#     fails because the wifi is bad is a guard people learn to skip.
#   - the harness notes and task files link to pull requests in this
#     repository, which is still private -- GitHub answers 404 rather than 403
#     for those, so an anonymous checker cannot tell "deleted" from "not
#     yours". T7.7 makes the repo public and this distinction goes away.
MARKDOWN_PUBLIC := README.md CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md $(wildcard docs/*.md) $(wildcard docs/adr/*.md)

lint-links:
	python scripts/check_links.py --skip-remote $(MARKDOWN)

lint-requirements:
	python scripts/check_requirements.py

# The convention asserted against the repository's own history, which is what
# makes it honest: a rule this log breaks is a rule nobody will follow, and it
# should fail here rather than in a stranger's first pull request. Thirty
# because that is roughly two waves, and because a shallow CI checkout has no
# more than that to offer.
lint-commits:
	git log --format=%s -30 | python scripts/check_commit_msg.py -

# Git runs no hook a clone brings with it -- that is a security property, not
# an oversight -- so this is opt-in and one line.
hooks:
	git config core.hooksPath .githooks
	@echo "hooks: commit-msg installed; scripts/check_commit_msg.py decides"

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
