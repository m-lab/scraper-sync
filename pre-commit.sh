#!/bin/bash
#
# We have to do our testing inside a container, so first we build the container,
# then we build the container that has the unit tests added.  If the build
# passes, then so does git-hooks/python-pre-commit
#   ln -s ../../pre-commit.sh .git/hooks/pre-commit

set -e

docker build . -f Dockerfile -t sync
docker build . -f TestDockerfile -t synctest
docker run -v `pwd`:/test -w /test synctest ./git-hooks/python-pre-commit
rm -f *.pyc
