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

if [[ "$1" == production ]]; then
  KEY_FILE=/tmp/production-secret-key.json
  PROJECT=mlab-oti
  # TODO(dev): create independent sheets for each project
  SHEET_ID=143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY
  DATASTORE_NAMESPACE=scraper
  CLUSTER=scraper-cluster
  ZONE=us-central1-a
  NODE_PATTERN_FILE=operator/plsync/production_patterns.txt
elif [[ "$1" == staging ]]; then
  KEY_FILE=/tmp/staging-secret-key.json
  PROJECT=mlab-staging
  SHEET_ID=143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY
  DATASTORE_NAMESPACE=scraper
  CLUSTER=scraper-cluster
  ZONE=us-central1-a
  NODE_PATTERN_FILE=operator/plsync/staging_patterns.txt
elif [[ "$1" == sandbox-* ]]; then
  # The branch sandbox-pboothe will use the namespace scraper-pboothe, and will
  # deploy to the cluster scraper-cluster-pboothe.
  SANDBOXSUFFIX=$(echo "$1" | sed -e 's/^sandbox-//')
  [[ -n "${SANDBOXSUFFIX}" ]] || exit 1
  KEY_FILE=/tmp/sandbox-secret-key.json
  PROJECT=mlab-sandbox
  SHEET_ID=143pU25GJidW2KZ_93hgzHdqTqq22wgdxR_3tt3dvrJY
  # DATASTORE_NAMESPACE must be unique to a cluster (within the same project), so in
  # expectation that there might be multiple clusters running in sandbox, we add
  # the suffix to make it unique.
  DATASTORE_NAMESPACE=scraper-${SANDBOXSUFFIX}
  # Because there may be multiple clusters in sandbox, we use the branch name to
  # choose one.
  CLUSTER=scraper-cluster-${SANDBOXSUFFIX}
  ZONE=us-central1-a
  NODE_PATTERN_FILE=sandbox-nodes.txt
else
  echo "BAD ARGUMENT TO $0"
  exit 1
fi

if [[ -e deployment ]]
then
  echo "existing deployment/ directory is in the way."
  exit 1
fi
mkdir deployment
cp deploy.yml deployment

if [[ $2 == travis ]]; then
  gcloud auth activate-service-account --key-file ${KEY_FILE}
fi

# Configure the last pieces of deploy.yml
./travis/substitute_values.sh deployment \
  IMAGE_URL gcr.io/${PROJECT}/github-m-lab-scraper-sync:${GIT_COMMIT} \
  SPREADSHEET_ID ${SHEET_ID} \
  NAMESPACE ${DATASTORE_NAMESPACE} \
  GITHUB_COMMIT http://github.com/m-lab/scraper-sync/tree/${GIT_COMMIT}

# Build the image and push it to GCR
./travis/build_and_push_container.sh \
  gcr.io/${PROJECT}/github-m-lab-scraper-sync:${GIT_COMMIT} \
  ${PROJECT}

# Make sure that the kubectl command is associated with the right cluster
gcloud --project=${PROJECT} \
  container clusters get-credentials ${CLUSTER} --zone=${ZONE}

# Apply the config in the deployment/ directory to the cluster
kubectl apply -f deployment/
