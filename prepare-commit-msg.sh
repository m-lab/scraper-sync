#!/bin/bash
#
# Once the container is built, we should run it, which also runs
# git-hooks/python-prepare-commit-msg
#   ln -s ../../prepare-commit-msg.sh .git/hooks/prepare-commit-msg

set -e

# Keep the full-path filenames consistent to not confuse code coverage tools.
docker run -v `pwd`:`pwd` -w `pwd` synctest \
  ./git-hooks/python-prepare-commit-msg | (
  # If a filename argument was passed in, comment all output and append it to
  # that file.  Otherwise just allow the output of the command to go to stdout.
  if [[ -n "$1" ]]; then
    sed -e 's/^/# /' >> $1
  else
    cat -
  fi
)
