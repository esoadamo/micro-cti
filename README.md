# uCTI.app

MicroCTI is a micro-blogging search engine that records only cybersecurity-related posts and allows you to search multiple micro-bloggins platforms at the same time.

Supported sources:

- Mastodon
- Bluesky
- Telegram
- AirTable
- Baserow
- RSS

## Search language

A generic search can be performed with default fulltext. Recognized search modifiers are:
- Parentheses: `(`, `)` for grouping
- Logical operators: `AND`, `OR`
- Quotation marks: `"explicit needed phrases"` for exact phrases
- Plus (`+`): require term (e.g. `+vulnerability`)
- Minus (`-`): exclude term (e.g. `-phishing`)

Custom search language with commands:

- `!strict` - Only exact matches are returned (e.g. from quotation)
- `!from:YYYY-MM-DD` - Only return posts since this date inclusive
- `!to:YYYY-MM-DD` - Only return posts until this date inclusive
- `!min_score:0-100` - Only return posts with a score higher or equal than this
- `!debug` - Enables debug mode
- `!distinct[:0-100]` - Filters similar posts based on the specified threshold (optional)
- `!distinct_age:number_of_days` - Applies an additional penalty to older posts during distinct filtering
- `!count:1-100` - Limits the maximum number of returned posts
- `!age:number_of_days` - Only posts with maximum age in days

## Search modes

The default search mode sends the query directly to the backend and returs the whole wepage with results at once. However, there are two other search modes. Suppose your search URL was http://127.0.0.1/search/?q=my_query, then you can change the URL to following:
- http://127.0.0.1/rss/?q=my_query to get the results as RSS feed
