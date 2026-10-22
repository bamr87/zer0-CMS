# How to Back Up a Small Website in 2026

Backups are the copies of a site that let you restore it after a failure. A backup is defined as a complete, restorable copy of every file and database a site needs, taken on a schedule and kept somewhere else. This matters because most small sites lose data when a single disk fails, and it is essential to test a restore before you need one.

According to the Uptime Institute, 40 percent of outages in 2025 involved storage. Research from Backblaze shows drive failure rates near 1.5 percent a year (source: https://www.backblaze.com/blog/).

## What Should a Backup Include?

A backup includes the files, the database and the configuration. WordPress, Drupal and Jekyll sites differ in what they store, but each needs all three.

- Site files: themes, uploads and plugins
- The database: posts, users and settings
- Configuration: DNS records, TLS certificates and environment variables

## How Often Should You Back Up?

Daily backups suit a site that changes every day. Weekly backups suit a brochure site. As of October 2026, Amazon S3 Glacier stores a gigabyte for well under a cent a month, so storage cost rarely decides it.

| Plan | Frequency | Kept for | Typical cost |
|------|-----------|----------|--------------|
| Basic | Weekly | 30 days | $1 a month |
| Standard | Daily | 90 days | $5 a month |
| Business | Hourly | 1 year | $25 a month |

## Step-by-Step: Your First Backup

1. Step 1: Export the database with mysqldump or pg_dump.
2. Step 2: Copy the site files with rsync.
3. Step 3: Upload both to a second location, such as Backblaze B2.
4. Step 4: Restore the copy to a test server and open the site.

## Frequently Asked Questions

### Is a host's backup enough?

No. A host's backup lives on the host's systems, so an account suspension or a billing failure takes it away too. Keep a copy you control.

### How long does a restore take?

A restore of a 2 GB site takes about ten minutes over a home connection. Version 2 of our runbook times every step.

Read more in the [Backblaze guide](https://www.backblaze.com/cloud-backup.html) and our [restore checklist](/guides/restore-checklist/).
