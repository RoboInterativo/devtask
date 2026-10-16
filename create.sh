#!/bin/sh
DOCKER_USER='TOKEN'
DOCKER_REGISTRY="registry.robointerativo.org"
PASSWD=`echo "${DOCKER_USER}:${DOCKER_TOKEN}" | tr -d '\n' | base64 -i -w 0`
DOCKER_REGISTRY2="docker-int.robointerativo.org"
DOCKER_REGISTRY3="docker-proxy.robointerativo.org"


CONFIG="{\"auths\":  {
   \"${DOCKER_REGISTRY}\": {  \"auth\": \"${PASSWD}\"  },
   \"${DOCKER_REGISTRY2}\": {  \"auth\": \"${NEXUS}\"  },
   \"${DOCKER_REGISTRY3}\": {  \"auth\": \"${NEXUS}\"  }
 }}"

echo "${CONFIG}" > config.json
DOCKER_CONFIG=`echo $CONFIG |base64 -w 0`
