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

  # Three states, not two. The first version of this script tested only
  # "already applied?" and force-applied otherwise — which on a *partially*
  # applied tree made `patch` prompt ("Reversed (or previously applied) patch
  # detected! Assume -R?"), answer itself from the patch file arriving on
  # stdin, and reverse the hunks that were correctly in place. It then exited 0.
  # That is how the recorder half of this patch went missing while the player
  # half survived, and it would have flip-flopped on every run.
  #
  # `--batch -f` on every invocation, including the dry runs: a script that can
  # stop and ask a question is a script that will answer itself with whatever
  # happens to be on stdin.
  if patch -p1 -R --dry-run --batch -f -d "$target" <"$patchfile" >/dev/null 2>&1; then
    echo "apply-patches: $package already patched"
    continue
  fi

  if ! patch -p1 --dry-run --batch -f -d "$target" <"$patchfile" >/dev/null 2>&1; then
    # Neither cleanly applied nor cleanly appliable: some hunks are in and some
    # are out. There is no safe automatic move from here — applying reverses the
    # good hunks, reversing loses the rest — so stop and say so. A failed
    # install is recoverable; a half-patched audio stack is a bug report about
    # the panel talking over itself three weeks from now.
    echo "apply-patches: $package is partially patched — refusing to guess." >&2
    echo "  Restore it with:" >&2
    echo "    rm -rf $target && npm install" >&2
    exit 1
  fi

  patch -p1 --batch -f -d "$target" <"$patchfile"
  echo "apply-patches: patched $package"
done
