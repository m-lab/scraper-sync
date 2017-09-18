| Branch | Build status | Coverage |
|:------:|:------------:|:--------:|
| Master | [![Build Status](https://travis-ci.org/m-lab/scraper-sync.svg?branch=master)](https://travis-ci.org/m-lab/scraper-sync) | [![Coverage Status](https://coveralls.io/repos/github/m-lab/scraper-sync/badge.svg?branch=master)](https://coveralls.io/github/m-lab/scraper-sync?branch=master) |

Scraper-sync pushes the status of the scraper job out to the coordinating
spreadsheet that is read by the fleet.

This needs to be done centrally in a loop like this because of daily API quota
limits in the sheets API; if each scraper instance update the spreadsheet every
scrape, then the sheet would get updated many tens of thousands of times per
day.  Unfortunately, the sheets API limits each sheet to 40,000 API calls per
day.

The system also provides an alternate method of getting the same information,
namely to query the service directly at the `/scraper_status` url. To get a JSON
object that contains only a subset of the data, use the `rsync_address`
argument.  For example, to see, in JSON form, the status of all `mlab1`
machines, GET the URL `/scraper_status?rsync_address=mlab1`

The `rsync_address` argument is compared the URL of every rsync endpoint using
the substring operation.
