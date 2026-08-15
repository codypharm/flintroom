#!/bin/sh
#
# Reapply our patches to node_modules after every install.
#
# One patch exists today and it is not cosmetic: `react-native-audio-api` opens
# both its Oboe streams in a configuration where Android's acoustic echo
# canceller cannot run, and the phone sits on a desk with the speaker on. See
# `docs/echo-cancellation.md` for the measurements.
#
# Without this, a plain `npm install` silently reverts the fix and the symptom
# is the panel interrupting itself — which `docs/voice-latency.md` records as
# indistinguishable from model latency. A quiet regression with a confusing
# symptom is exactly the thing worth automating.
#
# `patch-package` is the usual tool for this and was tried first. It refuses to
# diff this package at all ("your changes involve creating symlinks") because
# the published tarball ships symlinked FFmpeg xcframeworks for iOS, and its
# --include/--exclude filters do not run early enough to avoid them. POSIX
# `patch` has no such trouble, needs no dependency, and is already installed
# everywhere this builds.

set -e

cd "$(dirname "$0")/.."

for patchfile in patches/*.patch; do
  [ -e "$patchfile" ] || continue

  # patches/<package>+<version>.patch — the convention patch-package uses, kept
  # so this stays a drop-in should that tool ever handle the symlinks.
  name=$(basename "$patchfile" .patch)
  package=${name%+*}
  target="node_modules/$package"

  if [ ! -d "$target" ]; then
    echo "apply-patches: $package not installed, skipping"
    continue
  fi

  # A reverse dry-run succeeds only when the patch is already in place, which
  # makes this idempotent without `-N` — whose exit codes cannot distinguish
  # "already applied" from "did not apply".
  if patch -p1 -R --dry-run -f -d "$target" <"$patchfile" >/dev/null 2>&1; then
    echo "apply-patches: $package already patched"
    continue
  fi

  patch -p1 -d "$target" <"$patchfile"
  echo "apply-patches: patched $package"
done
