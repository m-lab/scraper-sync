#!/bin/bash

# Calls travis/build_and_deploy_container.sh with the right arguments for the
# desired deployment environment.  This script is intended to be run from the
# root directory of the repo, or by Travis from wherever Travis happens to call
# the script.
#
# If you run the deployment script locally and don't push your changes upstream,
# then the code URL will resolve to 404.  If you run the deployment script
# locally and you haven't committed your changes, then then URL will be a lie.
# Don't do those things.

USAGE="$0 [production|staging|arbitrary-string-sandbox] travis?"
if [[ -n "$2" ]] && [[ "$2" != travis ]]; then
  echo The second argument can only be the word travis or nothing at all.
  echo $USAGE
  exit 1
fi

set -e
set -x

source "${HOME}/google-cloud-sdk/path.bash.inc"

if [[ $2 == travis ]]; then
  cd $TRAVIS_BUILD_DIR
  GIT_COMMIT=${TRAVIS_COMMIT}
else
  GIT_COMMIT=$(git log -n 1 | head -n 1 | awk '{print $2}')
fi

if [[ -e deployment ]]
then
  echo "existing deployment/ directory is in the way."
  exit 1
fi
mkdir deployment
cp deploy.yml deployment
if [[ "$1" == production ]]; then
  if [[ $2 == travis ]]; then
    gcloud auth activate-service-account --key-file /tmp/production-secret-key.json
  fi
  ./travis/substitute_values.sh deployment \
    IMAGE_URL gcr.io/mlab-oti/github-m-lab-scraper-sync:${GIT_COMMIT} \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/m-lab/scraper-sync/tree/${GIT_COMMIT}
  ./travis/build_and_push_container.sh \
    gcr.io/mlab-oti/github-m-lab-scraper-sync:${GIT_COMMIT}  mlab-staging
  gcloud --project=mlab-oti container clusters get-credentials scraper-cluster \
    --zone=us-central1-a
elif [[ "$1" == staging ]]; then
  if [[ $2 == travis ]]; then
    gcloud auth activate-service-account --key-file /tmp/staging-secret-key.json
  fi
  ./travis/substitute_values.sh deployment \
    IMAGE_URL gcr.io/mlab-staging/github-m-lab-scraper-sync:${GIT_COMMIT} \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/m-lab/scraper-sync/tree/${GIT_COMMIT}
  ./travis/build_and_push_container.sh \
    gcr.io/mlab-staging/github-m-lab-scraper-sync:${GIT_COMMIT}  mlab-staging
  gcloud --project=mlab-staging container clusters get-credentials scraper-cluster \
    --zone=us-central1-a
elif [[ "$1" == sandbox-* ]]; then
  if [[ $2 == travis ]]; then
    gcloud auth activate-service-account --key-file /tmp/sandbox-secret-key.json
  fi
  SANDBOXSUFFIX=$(echo "$1" | sed -e 's/^sandbox-//')
  [[ -n "${SANDBOXSUFFIX}" ]] || exit 1
  ./travis/substitute_values.sh deployment \
    IMAGE_URL gcr.io/mlab-sandbox/github-m-lab-scraper-sync:${GIT_COMMIT} \
    SPREADSHEET_ID 143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY \
    NAMESPACE scraper \
    GITHUB_COMMIT http://github.com/m-lab/scraper-sync/tree/${GIT_COMMIT}
  ./travis/build_and_push_container.sh \
    gcr.io/mlab-sandbox/github-m-lab-scraper-sync:${GIT_COMMIT}  mlab-sandbox
  gcloud --project=mlab-sandbox container clusters get-credentials ${SANDBOXSUFFIX}-scraper-cluster \
    --zone=us-central1-a
else
  echo "BAD ARGUMENT TO $0"
  exit 1
fi
kubectl apply -f deployment/
