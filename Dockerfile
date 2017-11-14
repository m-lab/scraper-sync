FROM alpine:3.6
MAINTAINER Peter Boothe <pboothe@google.com>
# Install all the standard packages we need
RUN apk update && apk add python python-dev py2-pip gcc g++ libc-dev bash
# Install all the python requirements
ADD requirements.txt /requirements.txt
RUN pip install -r requirements.txt
ADD sync.py /sync.py
RUN chmod +x /sync.py
# The monitoring port
EXPOSE 9090
# The web status port
EXPOSE 80
# Start running the job
CMD /sync.py \
    --datastore_namespace=$NAMESPACE \
    --spreadsheet=$SPREADSHEET
