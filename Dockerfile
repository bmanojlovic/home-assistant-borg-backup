ARG BUILD_FROM
FROM $BUILD_FROM

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Setup base
ENV LANG=C.UTF-8

RUN apk add --no-cache \
        borgbackup \
        openssh-keygen \
        openssh-client \
        jq \
        pigz \
        python3 \
        py3-pip \
	py3-psutil \
    && pip3 install --no-cache-dir \
        psutil

# Home Assistant CLI
ARG BUILD_ARCH
ARG CLI_VERSION
RUN curl -Lso /usr/bin/ha \
        "https://github.com/home-assistant/cli/releases/download/${CLI_VERSION}/ha_${BUILD_ARCH}" \
    && chmod a+x /usr/bin/ha 

# Copy required data for add-on
COPY run.py /
RUN chmod a+x /run.py

CMD [ "python3", "/run.py" ]
