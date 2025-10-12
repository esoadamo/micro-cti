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

The default search mode sends the query directly to the backend and returns the whole webpage with results at once. However, there are three other search modes. Suppose your search URL was http://127.0.0.1/search/?q=my_query, then you can change the URL to following:
- http://127.0.0.1/rss/?q=my_query to get the results as RSS feed
- http://127.0.0.1/search/dynamic/?q=my_query for dynamic search mode (loads results incrementally, suitable for large or slow queries)
- http://127.0.0.1/api/search?q=my_query to get results in JSON format for programmatic access

## Job Files & Scheduling

This project includes several job scripts for data ingestion, maintenance, and export. Below is a summary of each job file and its recommended schedule:

- **job-ingest.py**: Fetches posts from all sources, ingests them into the database, and generates tags. **Run hourly.**
- **job-cache-expire.py**: Removes expired search cache entries from the database. **Run daily.**
- **job-data-export.py**: Exports all posts (with tags) to a compressed JSONL file for backup or migration. **Run daily.**
- **job-data-import.py**: Imports posts from a backup file into the database, including tags. **Run ad-hoc when necessary.**
- **job-filter-tags.py**: Cleans up tags by deleting those with names that are too short/long and processes subtags. **Run daily.**
- **job-parse-ioc.py**: Parses indicators of compromise (IOCs) from all visible posts. **Run ad-hoc when necessary.**
- **job-tag.py**: Ingests all posts and generates tags for them. **Run ad-hoc when necessary.**
- **job-telegram-list-channels.py**: Lists all Telegram channels currently included/excluded in the configuration. **Run ad-hoc when necessary.**
- **job-filter-posts.py**: Scans all visible posts and hides those not related to cybersecurity. **Run ad-hoc when necessary.**

Refer to each script for more details on its usage and output.
