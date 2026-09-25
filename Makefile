# Entry point for humans, CI and agents alike. Every target exits non-zero on failure.
DC := docker compose -f docker/compose.yml run --rm build

.PHONY: help check lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-selftests test-server test-web test-android connected build apk contract e2e clean

help:
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
	@echo "lint-selftests  every scripts/*.py that has a --self-test runs it"
	@echo "clean         remove build output"

check: lint-tasks lint-notes lint-status lint-permissions lint-workflow lint-selftests test-server test-web test-android

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

# A self-test no target invokes is a test suite with no runner. after_update.py
# had one, nothing ran it, and it was red on Linux from the day it was written
# while every wave was judged on Windows (TT.12). Discovery is by grep over a
# glob, never a list: the next script to grow a --self-test is covered by being
# written, which a list would not do.
lint-selftests:
	@# discovery is a glob over scripts/, never a list of names
	@found=$$(grep -l -- '--self-test' scripts/*.py); \
	test -n "$$found" || { echo "lint-selftests: nothing carries a --self-test"; exit 1; }; \
	for s in $$found; do \
		echo "--> $$s --self-test"; \
		python "$$s" --self-test || exit 1; \
	done

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
