#!/bin/bash

set -e
set -x

source "${HOME}/google-cloud-sdk/path.bash.inc"

ssh-keygen -f ~/.ssh/google_compute_engine -N ""
cd $TRAVIS_BUILD_DIR
mkdir deployment
if [[ "$1" = staging ]]
then
  gcloud auth activate-service-account --key-file /tmp/staging-secret-key.json
  ./travis/build_and_deploy_container.sh ${TRAVIS_COMMIT} \
    gcr.io/mlab-staging/github-m-lab-scraper mlab-staging scraper-cluster us-central1-a \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/${TRAVIS_REPO_SLUG}/tree/${TRAVIS_COMMIT}
fi
