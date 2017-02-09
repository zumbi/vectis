#!/bin/sh
# vim:set ft=sh sw=4 sts=4 et:

set -e
set -u
set -x

if [ -n "${VECTIS_UNINSTALLED:-}" ]; then
    VECTIS="${PYTHON:-python3} ${VECTIS_UNINSTALLED}/run"
else
    VECTIS=vectis
fi

storage="$(mktemp -d)"
arch="$(dpkg --print-architecture)"

ln -s "${XDG_CACHE_HOME:-"${HOME}/.cache"}"/vectis/vectis-debian-sid-${arch}.qcow2 "${storage}"

if ! [ -f "${storage}/vectis-debian-sid-${arch}.qcow2" ]; then
    echo "1..0 # SKIP vectis-debian-sid-${arch}.qcow2 not found"
    exit 0
fi

if [ -z "${VECTIS_TEST_DEBIAN_MIRROR:-}" ]; then
    echo "1..0 # SKIP This test requires VECTIS_TEST_DEBIAN_MIRROR=http://192.168.122.1:3142/debian or similar"
    exit 0
fi

echo "1..1"

$VECTIS --vendor=debian --storage="${storage}" sbuild-tarball \
    --worker="qemu ${storage}/vectis-debian-sid-${arch}.qcow2" \
    --mirror="${VECTIS_TEST_DEBIAN_MIRROR}" \
    --suite=sid
$VECTIS --vendor=debian --storage="${storage}" sbuild \
    --worker="qemu ${storage}/vectis-debian-sid-${arch}.qcow2" \
    --mirror="${VECTIS_TEST_DEBIAN_MIRROR}" \
    --suite=sid hello
rm -fr "${storage}"

echo "ok 1"
