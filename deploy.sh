#!/bin/bash

# Calls travis/build_and_deploy_container.sh with the right arguments for the
# desired deployment environment.

set -e
set -x

source "${HOME}/google-cloud-sdk/path.bash.inc"

ssh-keygen -f ~/.ssh/google_compute_engine -N ""
cd $TRAVIS_BUILD_DIR
mkdir deployment
cp deploy.yml deployment
if [[ "$1" == production ]]; then
  gcloud auth activate-service-account --key-file /tmp/production-secret-key.json
  ./travis/build_and_deploy_container.sh ${TRAVIS_COMMIT} \
    gcr.io/mlab-oti/github-m-lab-scraper-sync mlab-oti scraper-cluster us-central1-a \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/${TRAVIS_REPO_SLUG}/tree/${TRAVIS_COMMIT}
elif [[ "$1" == staging ]]; then
  gcloud auth activate-service-account --key-file /tmp/staging-secret-key.json
  ./travis/build_and_deploy_container.sh ${TRAVIS_COMMIT} \
    gcr.io/mlab-staging/github-m-lab-scraper-sync mlab-staging scraper-cluster us-central1-a \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/${TRAVIS_REPO_SLUG}/tree/${TRAVIS_COMMIT}
elif [[ "$1" == sandbox-* ]]; then
  SANDBOXSUFFIX=$(echo "$1" | sed -e 's/^sandbox-//')
  [[ -n "${CLUSTERPREFIX}" ]] || exit 1
  gcloud auth activate-service-account --key-file /tmp/sandbox-secret-key.json
  ./travis/build_and_deploy_container.sh ${TRAVIS_COMMIT} \
    gcr.io/mlab-sandbox/github-m-lab-scraper-sync mlab-sandbox ${SANDBOXSUFFIX}-scraper-cluster us-central1-a \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper-${SANDBOXSUFFIX} \
    GITHUB_COMMIT http://github.com/${TRAVIS_REPO_SLUG}/tree/${TRAVIS_COMMIT}
else
  echo "BAD ARGUMENT TO $0"
  exit 1
fi
