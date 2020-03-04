#!/bin/bash

export ADDON_NAME="borg-backup"
export GITHUB_URL="https://github.com/bmanojlovic/home-assistant-borg-backup/"
export AUTHOR="Boris Manojlovic <boris@steki.net>"
export DOCKER_USER="bmanojlovic"

#docker run -it --rm --privileged --name "${ADDON_NAME}" \
#        -v ~/.docker:/root/.docker \
#        -v "$(pwd)":/docker \
#        hassioaddons/build-env:latest \
#        --target . \
#        --tag-test \
#        --all \
#        --from "homeassistant/{arch}-base" \
#        --author  "${AUTHOR}" \
#        --doc-url "${GITHUB_URL}" \
#	--image "${DOCKER_USER}/{arch}-${ADDON_NAME}" \
#        --parallel

docker run --rm --privileged \
	-v ~/.docker:/root/.docker \
	homeassistant/amd64-builder --all -t borg_backup \
	-r https://github.com/bmanojlovic/home-assistant-addons -b master