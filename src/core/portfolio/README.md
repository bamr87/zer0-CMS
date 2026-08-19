# `core/portfolio` — the track record

Catering answers *what should I write next*. This answers the question that decides whether anyone keeps asking it: **has any of this added up to anything?**

One post is a post. Forty posts tied to real work is a record, and it is what an editor, a client, or a hiring manager actually looks at.

## Why it works before analytics do

Everything is computed from the ledger, with the contract supplying each entry's collection. Cadence and streak are properties of *when you published*, not of how it performed — so a portfolio is meaningful from the first entry, unlike Lanes B–D which stay empty until statistics exist.

## The streak is anchored to the data, not to today

`streakOf` counts back from the newest month **in the ledger**. A portfolio that reported a broken streak because the reader happened to open it in a quiet week would be measuring the calendar, not the work. "Three months running, most recently in June" stays true in July.

## The topic axis is the author's own

Collections, the same axis `catering/` groups by. No clustering, no inferred interests, nothing derived about anybody. A portfolio is a fact about the author's output.

## Shape

| Export | Purpose |
|---|---|
| `buildPortfolio(ledger, contract?)` | the record; pure, contract optional |
| `renderPortfolio(portfolio)` | as text |
| `streakOf(byMonth)` | consecutive months, exported because it is the subtle one |

Without a contract every entry lands in `uncategorised` rather than being silently mis-filed.
