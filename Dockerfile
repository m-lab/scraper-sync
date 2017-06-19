FROM google/cloud-sdk
MAINTAINER Peter Boothe <pboothe@google.com>
# Install all the standard packages we need
RUN apt-get -q update && apt-get install -q -y python-dev python-pip
# Install all the python requirements
ADD requirements.txt /requirements.txt
RUN pip install -q -r requirements.txt
RUN mkdir -p operator/plsync
ADD operator/plsync operator/plsync/
ADD sync.py /sync.py
RUN chmod +x /sync.py
# The monitoring port
EXPOSE 9090
# The web status port
EXPOSE 80
# Start running the job
CMD /sync.py \
    --datastore_namespace=$NAMESPACE \
    --spreadsheet=$SPREADSHEET \
    --node_pattern_file=$NODE_PATTERN_FILE
