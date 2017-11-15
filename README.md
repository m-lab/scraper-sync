| Branch | Build status | Coverage |
|:------:|:------------:|:--------:|
| Master | [![Build Status](https://travis-ci.org/m-lab/scraper-sync.svg?branch=master)](https://travis-ci.org/m-lab/scraper-sync) | [![Coverage Status](https://coveralls.io/repos/github/m-lab/scraper-sync/badge.svg?branch=master)](https://coveralls.io/github/m-lab/scraper-sync?branch=master) |

Scraper-sync provides a service that allows individual mlab nodes to query the
scraper status using the `/json_status` url. To get a JSON object that contains
only a subset of the data, use the `rsync_filter` argument.  For example, to
see, in JSON form, the status of all `mlab1` machines, GET the URL
`/json_status?rsync_filter=mlab1`

The `rsync_filter` argument is compared the URL of every rsync endpoint using
the substring operation.  It is anticipated that most uses of this endpoint will
be requesting a single node, and will be called from `delete_logs_safely.py`
