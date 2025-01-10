# uCTI.app

MicroCTI is a micro-blogging search engine that records only cybersecurity-related posts and allows you to search multiple micro-bloggins platforms at the same time.

Supported sources:

- Mastodon
- Bluesky
- Telegram
- AirTable
- RSS

## Search language

A generic search can be performed with default fulltext. Recognized search modifiers are `(`, `)`, `AND`, `OR`, `"explicit needed phrases"`.

Custom search language with commands:

- `!strict` - removes all posts that do not match explicit command
- `!fast` - performs the search directly in databse, less accurate, but much faster
- `!min_score:<0-100>` - show posts only with score greater or equal to
- `!from:YYY-MM-DD` - show posts only newer than this date or equal
- `!to:YYY-MM-DD` - show posts only older than this date or equal
- `!age:<DAYS>` - show posts only with maximum age of `<DAYS>` days

## Search modes

The default search mode sends the query directly to the backend and returs the whole wepage with results at once. However, there are two other search modes. Suppose your search URL was http://127.0.0.1/search/?q=my_query, then you can change the URL to following:
- http://127.0.0.1/rss/?q=my_query to get the results as RSS feed
- http://127.0.0.1/search/dynamic/?q=my_query to get the results streamed, usefull for searches that are using larger timeframe

