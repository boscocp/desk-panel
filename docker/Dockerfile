# Android build toolchain. Nothing here is installed on the host - that is the
# whole point of ADR 0003. No Android Studio, no emulator, no AVD.
#
# Pinned by digest, not by tag: a tag is a moving target and this image is the
# definition of "reproducible build" for the whole project.
FROM eclipse-temurin:24.0.2_12-jdk-noble@sha256:dacac8e9a0df0d2bd24e702b4431132875c249930b70555ebd7ca285b5bee684

# Exact versions, never "latest". The task file is explicit about this.
ARG CMDLINE_TOOLS_VERSION=13114758
ARG ANDROID_PLATFORM=android-36
ARG BUILD_TOOLS=36.0.0

ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install --no-install-recommends -y ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

# sdkmanager insists on living at cmdline-tools/latest/ - that is its own
# layout requirement, not a version pin being dodged; the zip is pinned above.
RUN set -eux; \
    mkdir -p "${ANDROID_HOME}/cmdline-tools"; \
    curl -fsSL -o /tmp/cmdline-tools.zip \
      "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip"; \
    unzip -q /tmp/cmdline-tools.zip -d "${ANDROID_HOME}/cmdline-tools"; \
    mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest"; \
    rm /tmp/cmdline-tools.zip

ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"

# Licences first, on their own. `yes` is killed by SIGPIPE the moment
# sdkmanager stops reading, so this pipeline exits 141 even when it worked -
# which is exactly why it is not the command that asserts anything.
RUN set -eux; \
    yes | sdkmanager --licenses > /dev/null || true

# This one has no pipe, so its exit status is sdkmanager's own. An unaccepted
# licence or a bad package name fails the build here, loudly.
RUN set -eux; \
    sdkmanager --install \
      "platform-tools" \
      "platforms;${ANDROID_PLATFORM}" \
      "build-tools;${BUILD_TOOLS}"; \
    sdkmanager --list_installed

# Gradle writes here; compose mounts a named volume over it so the cache
# survives `--rm` without a slow bind mount.
ENV GRADLE_USER_HOME=/gradle
RUN mkdir -p /gradle && chmod 0777 /gradle

# Every build artefact must be writable by the host user, who compose passes in
# as user:. A fixed USER here would defeat that.
RUN chmod -R a+rX "${ANDROID_HOME}"

WORKDIR /workspace
