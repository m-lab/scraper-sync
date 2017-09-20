#!/bin/bash

source /root/google-cloud-sdk/path.bash.inc
gcloud config set project mlab-sandbox
gcloud beta emulators datastore start --consistency=1.0 --no-store-on-disk &
sleep 5
echo RUNNING ENV INIT
$(gcloud beta emulators datastore env-init)
env
./git-hooks/python-pre-commit
