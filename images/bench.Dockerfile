# One image for arms B, C and D. Pin the base digest before the main run.
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq make python3 python3-pip python3-venv python-is-python3 \
        procps findutils coreutils iproute2 fio \
    && rm -rf /var/lib/apt/lists/*

# ubuntu:24.04 ships user "ubuntu" as UID 1000; OpenShell runs non-root images as declared USER.
RUN mkdir -p /sandbox/workspace && chown -R 1000:1000 /sandbox
# pip settings live in /etc/pip.conf, not ENV: OpenShell `sandbox exec` does not propagate image ENV,
# so ENV-based settings would make arms B and C/D behave differently.
RUN printf '[global]\nbreak-system-packages = true\ndisable-pip-version-check = true\n' > /etc/pip.conf
USER 1000:1000
WORKDIR /sandbox/workspace
CMD ["sleep", "infinity"]
