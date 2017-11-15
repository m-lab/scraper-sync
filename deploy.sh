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

# Adapted from the one from ezprompt.net
function git_is_dirty {
    status=`git status 2>&1 | tee`
    dirty=`echo -n "${status}" 2> /dev/null | grep "modified:" &> /dev/null; echo "$?"`
    newfile=`echo -n "${status}" 2> /dev/null | grep "new file:" &> /dev/null; echo "$?"`
    renamed=`echo -n "${status}" 2> /dev/null | grep "renamed:" &> /dev/null; echo "$?"`
    deleted=`echo -n "${status}" 2> /dev/null | grep "deleted:" &> /dev/null; echo "$?"`
    bits=''
    if [ "${renamed}" == "0" ]; then
        bits=">${bits}"
    fi
    if [ "${newfile}" == "0" ]; then
        bits="+${bits}"
    fi
    if [ "${deleted}" == "0" ]; then
        bits="x${bits}"
    fi
    if [ "${dirty}" == "0" ]; then
        bits="!${bits}"
    fi
    [[ -n "${bits}" ]]
}

if [[ "$1" == production ]]; then
  KEY_FILE=/tmp/mlab-oti.json
  PROJECT=mlab-oti
  DATASTORE_NAMESPACE=scraper
  CLUSTER=scraper-cluster
  ZONE=us-central1-a
  EXTERNAL_IP=35.193.213.113
  if git_is_dirty ; then
    echo "We won't deploy to production with uncommitted changes"
    exit 1
  fi
elif [[ "$1" == staging ]]; then
  KEY_FILE=/tmp/mlab-staging.json
  PROJECT=mlab-staging
  DATASTORE_NAMESPACE=scraper
  CLUSTER=scraper-cluster
  ZONE=us-central1-a
  EXTERNAL_IP=35.184.20.213
  if git_is_dirty ; then
    echo "We won't deploy to staging with uncommitted changes"
    exit 1
  fi
elif [[ "$1" == sandbox-* ]]; then
  # The branch sandbox-pboothe will use the namespace scraper-pboothe, and will
  # deploy to the cluster scraper-cluster-pboothe.
  SANDBOXSUFFIX=$(echo "$1" | sed -e 's/^sandbox-//')
  [[ -n "${SANDBOXSUFFIX}" ]] || exit 1
  KEY_FILE=/tmp/mlab-sandbox.json
  PROJECT=mlab-sandbox
  # DATASTORE_NAMESPACE must be unique to a cluster (within the same project), so in
  # expectation that there might be multiple clusters running in sandbox, we add
  # the suffix to make it unique.
  DATASTORE_NAMESPACE=scraper-${SANDBOXSUFFIX}
  # Because there may be multiple clusters in sandbox, we use the branch name to
  # choose one.
  CLUSTER=scraper-cluster-${SANDBOXSUFFIX}
  ZONE=us-central1-a
  # The EXTERNAL_IP value will be inherited from the calling environment for
  # sandbox
else
  echo "BAD ARGUMENT TO $0"
  exit 1
fi

cp sync.yml deployment

if [[ $2 == travis ]]; then
  gcloud auth activate-service-account --key-file ${KEY_FILE}
fi

# Configure the last pieces of the .yml files
./travis/substitute_values.sh deployment \
  IMAGE_URL gcr.io/${PROJECT}/github-m-lab-scraper-sync:${GIT_COMMIT} \
  NAMESPACE ${DATASTORE_NAMESPACE} \
  GITHUB_COMMIT http://github.com/m-lab/scraper-sync/tree/${GIT_COMMIT} \
  EXTERNAL_IP ${EXTERNAL_IP}

# Build the image and push it to GCR
./travis/build_and_push_container.sh \
  gcr.io/${PROJECT}/github-m-lab-scraper-sync:${GIT_COMMIT} \
  ${PROJECT}

# Make sure that the kubectl command is associated with the right cluster
gcloud --project=${PROJECT} \
  container clusters get-credentials ${CLUSTER} --zone=${ZONE}

# Apply the config in the deployment/ directory to the cluster
kubectl apply -f deployment/
