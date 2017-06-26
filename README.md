| Branch | Build status | Coverage |
|:------:|:------------:|:--------:|
| Master | [![Build Status](https://travis-ci.org/m-lab/scraper-sync.svg?branch=master)](https://travis-ci.org/m-lab/scraper-sync) | [![Coverage Status](https://coveralls.io/repos/github/m-lab/scraper-sync/badge.svg?branch=master)](https://coveralls.io/github/m-lab/scraper-sync?branch=master) |
| Staging | [![Build Status](https://travis-ci.org/m-lab/scraper-sync.svg?branch=staging)](https://travis-ci.org/m-lab/scraper-sync) | [![Coverage Status](https://coveralls.io/repos/github/m-lab/scraper-sync/badge.svg?branch=staging)](https://coveralls.io/github/m-lab/scraper-sync?branch=staging) |

Scraper-sync pushes the status of the scraper job out to the coordinating
spreadsheet that is read by the fleet.

This needs to be done centrally in a loop like this because of daily API quota
limits in the sheets API; if each scraper instance update the spreadsheet every
scrape, then the sheet would get updated many tens of thousands of times per
day.  Unfortunately, the sheets API limits each sheet to 40,000 API calls per
day.
