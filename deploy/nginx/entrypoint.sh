#!/bin/sh
set -eu

# The literal expression tells envsubst to replace only this variable, preserving Nginx variables.
# shellcheck disable=SC2016
envsubst '${PENNI_MORE_DOMAIN}' </etc/nginx/default.conf.template >/tmp/default.conf
exec "$@"
