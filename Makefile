# Entry point for humans, CI and agents alike. Every target exits non-zero on failure.
DC := docker compose -f docker/compose.yml run --rm build

.PHONY: help check test-server test-web test-android build apk contract e2e clean

help:
	@echo "check         run everything that does not need the phone"
	@echo "test-server   python unittest"
	@echo "test-web      node:test"
	@echo "test-android  gradle JVM unit tests (container)"
	@echo "build apk     assemble the debug APK (container)"
	@echo "contract      hit the real upstream APIs (network, opt-in)"
	@echo "e2e           full end-to-end, needs the phone on adb"

check: test-server test-web test-android

test-server:
	python -m unittest discover -s server/tests -t .

test-web:
	node --test "web/test/**/*.test.js"

test-android:
	$(DC) ./gradlew test

build apk:
	$(DC) ./gradlew assembleDebug

contract:
	RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . -p "contract_*.py"

e2e:
	python e2e/run_e2e.py

clean:
	$(DC) ./gradlew clean
	rm -rf out
