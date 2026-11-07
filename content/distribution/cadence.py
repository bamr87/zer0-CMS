"""A channel's publishing cadence: when approved posts go out (issue #89).

Shared, as `gates.py` is, by the platform's release queue (`services.schedule`, `services.release_due`) and a site's
lane (`lane.pipeline.Pipeline.publish_queue`, `calendar`). Pure: no Django, no network and no clock of its own, so
every function that needs the time is given it. A cadence decides *when* an approved post goes, never *whether*:
approval, the gates and arming are unchanged, and a person's own publish of one named post is never held by it.

    {
      "timezone": "America/Denver",          an IANA zone; default UTC
      "slots": ["tue 09:00", "thu 09:00"],   the weekly release times: days (mon … sun, daily, weekdays, weekends,
                                             a range mon-fri, a list mon,wed) and a 24-hour local time
      "minGap": "48h",                       never closer than this to another post of the channel (default 0)
      "perDay": 1,                           at most this many in a local day (default 1)
      "perWeek": 2,                          at most this many in a local ISO week (default: no limit)
      "blackout": ["2026-12-24..2027-01-01"],  local dates, or inclusive ranges, with no release
      "afterPage": "1h",                     the phase: a share waits this long after its page went live (default 0)
      "grace": "6h"                          how late a run may still take a slot it missed (default 6h)
    }

Durations are whole minutes, hours and days, alone or together: `90m`, `48h`, `2d`, `1d12h`, or `0`. Every time
this module returns is aware and in UTC; the cadence's zone only decides what "Tuesday at 09:00" and "a day" mean.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KEYS = ("timezone", "slots", "minGap", "perDay", "perWeek", "blackout", "afterPage", "grace")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
GROUPS = {"daily": tuple(range(7)), "weekdays": tuple(range(5)), "weekends": (5, 6)}
SLOT = re.compile(r"\A(?P<days>[a-z][a-z,-]*)\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})\Z")
DURATION = re.compile(r"\A(?:\d+[dhm])+\Z")
UNITS = {"d": "days", "h": "hours", "m": "minutes"}
DEFAULT_GRACE = timedelta(hours=6)
HORIZON_DAYS = 366


class CadenceError(ValueError):
    """A cadence that cannot be read; `problems` lists every reason, each naming its key."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Item:
    """One post waiting for a slot: `not_before` is the earliest it may go (a pinned time, or its page's go-live plus
    `afterPage`), `pinned` says a person chose that time, and `order` is its place in the queue."""

    key: str
    not_before: datetime | None = None
    pinned: bool = False
    order: int = 0


@dataclass(frozen=True)
class Placement:
    key: str
    at: datetime | None
    reason: str = ""


@dataclass(frozen=True)
class Cadence:
    timezone: str
    slots: tuple[tuple[int, time], ...]
    min_gap: timedelta = timedelta(0)
    per_day: int = 1
    per_week: int | None = None
    blackout: tuple[tuple[date, date], ...] = ()
    after_page: timedelta = timedelta(0)
    grace: timedelta = DEFAULT_GRACE
    zone: ZoneInfo = field(default=ZoneInfo("UTC"), compare=False, repr=False)

    # ── reading the calendar ─────────────────────────────────────────────────
    def local(self, at: datetime) -> datetime:
        return at.astimezone(self.zone)

    def dark(self, day: date) -> bool:
        """A blackout date: no release that local day."""
        return any(start <= day <= end for start, end in self.blackout)

    def slots_from(self, start: datetime, *, days: int = HORIZON_DAYS):
        """Every slot at or after `start`, in order, for `days` local days — blackout days left out."""
        first = self.local(start).date()
        for offset in range(days + 1):
            day = first + timedelta(days=offset)
            if self.dark(day):
                continue
            for weekday, at in self.slots:
                if weekday != day.weekday():
                    continue
                when = datetime.combine(day, at, tzinfo=self.zone).astimezone(UTC)
                if when >= start:
                    yield when

    # ── the rules ────────────────────────────────────────────────────────────
    def reasons(self, at: datetime, taken) -> list[str]:
        """Why a post may not go at `at`, given the times other posts of the channel went or are to go."""
        out = []
        day = self.local(at).date()
        if self.dark(day):
            out.append(f"{day.isoformat()} is a blackout date")
        others = [t for t in taken if t is not None]
        if self.min_gap and (near := [t for t in others if abs(at - t) < self.min_gap]):
            closest = min(near, key=lambda t: abs(at - t))
            out.append(f"within {describe(self.min_gap)} of the post at {self.show(closest)} (minGap)")
        if sum(1 for t in others if self.local(t).date() == day) >= self.per_day:
            out.append(f"{day.isoformat()} already has {self.per_day} (perDay)")
        if self.per_week is not None:
            week = day.isocalendar()[:2]
            if sum(1 for t in others if self.local(t).date().isocalendar()[:2] == week) >= self.per_week:
                out.append(f"the week of {day.isoformat()} already has {self.per_week} (perWeek)")
        return out

    def next_slot(self, after: datetime, taken=()) -> datetime | None:
        """The first slot at or after `after` the rules allow, or None inside a year (every slot dark or full)."""
        taken = list(taken)
        return next((s for s in self.slots_from(after) if not self.reasons(s, taken)), None)

    def open_slot(self, now: datetime, history=()) -> datetime | None:
        """The slot a run at `now` may take, for a lane that runs on a timer rather than at each slot: the latest
        slot no older than `grace`, with nothing published since it opened and the rules holding now."""
        history = [t for t in history if t is not None]
        latest = None
        for slot in self.slots_from(now - self.grace, days=(self.grace.days + 2)):
            if slot > now:
                break
            latest = slot
        if latest is None or any(t >= latest for t in history):
            return None
        return latest if not self.reasons(now, history) else None

    def plan(self, items, *, times, taken=()) -> list[Placement]:
        """Give each item the first of `times` it may take, in queue order: at each time, the earliest pinned item
        that is due goes first, then the first unpinned item that is ready. What finds no time says why."""
        taken = list(taken)
        waiting = sorted(items, key=lambda i: i.order)
        placed: dict[str, Placement] = {}
        for at in times:
            if not waiting:
                break
            if self.reasons(at, taken):
                continue
            due = [i for i in waiting if i.not_before is None or i.not_before <= at]
            pinned = sorted((i for i in due if i.pinned), key=lambda i: (i.not_before, i.order))
            pick = (pinned or due or [None])[0]
            if pick is None:
                continue
            placed[pick.key] = Placement(pick.key, at)
            taken.append(at)
            waiting.remove(pick)
        for item in waiting:
            placed[item.key] = Placement(item.key, None, "no slot within a year: every one is dark or full")
        return [placed[i.key] for i in items]

    # ── words ────────────────────────────────────────────────────────────────
    def show(self, at: datetime | None) -> str:
        """A time as a person in the cadence's zone reads it: `Tue 2026-11-10 09:00 MST`."""
        if at is None:
            return "—"
        local = self.local(at)
        return f"{DAYS[local.weekday()].capitalize()} {local:%Y-%m-%d %H:%M} {local.tzname()}"

    def summary(self) -> str:
        """The cadence in words: `tue,thu 09:00 (America/Denver), at most 1 a day, 48h apart`."""
        by_time: dict[time, list[int]] = {}
        for day, at in self.slots:
            by_time.setdefault(at, []).append(day)
        slots = ", ".join(f"{_days_word(days)} {at:%H:%M}" for at, days in sorted(by_time.items()))
        parts = [f"{slots} ({self.timezone})", f"at most {self.per_day} a day"]
        if self.per_week is not None:
            parts.append(f"{self.per_week} a week")
        if self.min_gap:
            parts.append(f"{describe(self.min_gap)} apart")
        if self.after_page:
            parts.append(f"{describe(self.after_page)} after the page")
        return ", ".join(parts)


def _days_word(days) -> str:
    found = tuple(sorted(days))
    named = {group: name for name, group in GROUPS.items()}
    return named.get(found) or ",".join(DAYS[d] for d in found)


# ── reading a cadence ───────────────────────────────────────────────────────


def duration(value) -> timedelta:
    """`90m`, `48h`, `2d`, `1d12h` or `0` → a timedelta; ValueError otherwise."""
    text = str(value).strip().lower().replace(" ", "")
    if text == "0":
        return timedelta(0)
    if isinstance(value, bool) or not DURATION.match(text):
        raise ValueError(text)
    total = timedelta(0)
    for amount, unit in re.findall(r"(\d+)([dhm])", text):
        total += timedelta(**{UNITS[unit]: int(amount)})
    return total


def describe(span: timedelta) -> str:
    minutes = int(span.total_seconds() // 60)
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    out = "".join(f"{n}{u}" for n, u in ((days, "d"), (hours, "h"), (minutes, "m")) if n)
    return out or "0"


def weekdays(text: str) -> tuple[int, ...]:
    """`mon`, `mon,wed`, `mon-fri`, `fri-mon` (wrapping), `daily`, `weekdays`, `weekends` → weekday numbers."""
    if text in GROUPS:
        return GROUPS[text]
    out: list[int] = []
    for part in text.split(","):
        ends = part.split("-")
        if len(ends) == 1 and ends[0] in DAYS:
            out.append(DAYS.index(ends[0]))
        elif len(ends) == 2 and ends[0] in DAYS and ends[1] in DAYS:
            first, last = DAYS.index(ends[0]), DAYS.index(ends[1])
            out.extend((first + n) % 7 for n in range((last - first) % 7 + 1))
        else:
            raise ValueError(part)
    return tuple(sorted(set(out)))


def _slots(value, problems) -> tuple[tuple[int, time], ...]:
    if not isinstance(value, list) or not value:
        problems.append('cadence.slots: needs at least one slot, like "tue 09:00" or "mon-fri 08:30"')
        return ()
    out = set()
    for index, raw in enumerate(value):
        match = SLOT.match(str(raw).strip().lower())
        try:
            if not match:
                raise ValueError(raw)
            hour, minute = int(match["hour"]), int(match["minute"])
            at = time(hour, minute)
            out.update((d, at) for d in weekdays(match["days"]))
        except ValueError:
            problems.append(
                f'cadence.slots[{index}]: "{raw}" is not a slot — days and a 24-hour time, like "tue 09:00", '
                '"mon-fri 08:30", "mon,wed 12:00" or "daily 17:45"'
            )
    return tuple(sorted(out))


def _blackout(value, problems) -> tuple[tuple[date, date], ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        problems.append('cadence.blackout: a list of dates or ranges, like ["2026-12-24..2027-01-01"]')
        return ()
    out = []
    for index, raw in enumerate(value):
        try:
            first, _, last = str(raw).strip().partition("..")
            start = date.fromisoformat(first)
            end = date.fromisoformat(last) if last else start
            if end < start:
                raise ValueError(raw)
            out.append((start, end))
        except ValueError:
            problems.append(
                f'cadence.blackout[{index}]: "{raw}" is not a date or a range (YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD)'
            )
    return tuple(out)


def _count(spec, key, problems, default):
    value = spec.get(key, default)
    if value is None and default is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        problems.append(f"cadence.{key}: a whole number from 1, got {value!r}")
        return default
    return value


def _span(spec, key, problems, default):
    if key not in spec:
        return default
    try:
        return duration(spec[key])
    except ValueError:
        problems.append(f'cadence.{key}: "{spec[key]}" is not a duration (like "90m", "48h", "2d" or "1d12h")')
        return default


def parse(spec) -> Cadence | None:
    """A cadence from its settings, None when there are none (`{}` or absent: posts go when they are approved, as
    before). Raises CadenceError naming every problem; an unknown key is one, so a typo never silently loosens it."""
    if spec in (None, {}):
        return None
    if not isinstance(spec, dict):
        raise CadenceError(['cadence: an object of settings, like {"slots": ["tue 09:00"]}'])
    problems: list[str] = []
    for key in spec:
        if key not in KEYS:
            problems.append(f"cadence.{key} is not a setting (known: {', '.join(KEYS)})")
    name = str(spec.get("timezone") or "UTC").strip()
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(f'cadence.timezone: "{name}" is not a time zone (an IANA name, like "America/Denver")')
        zone = ZoneInfo("UTC")
    cadence = Cadence(
        timezone=name,
        slots=_slots(spec.get("slots"), problems),
        min_gap=_span(spec, "minGap", problems, timedelta(0)),
        per_day=_count(spec, "perDay", problems, 1),
        per_week=_count(spec, "perWeek", problems, None),
        blackout=_blackout(spec.get("blackout"), problems),
        after_page=_span(spec, "afterPage", problems, timedelta(0)),
        grace=_span(spec, "grace", problems, DEFAULT_GRACE),
        zone=zone,
    )
    if problems:
        raise CadenceError(problems)
    return cadence


def problems(spec) -> list[str]:
    try:
        parse(spec)
    except CadenceError as e:
        return e.problems
    return []


def moment(value, zone: ZoneInfo) -> datetime:
    """A pinned time as a person writes it — `2026-11-10 09:00`, `2026-11-10T09:00:00-07:00`, `…Z`, or a date —
    read in the cadence's zone when it names none. ValueError for anything else."""
    text = str(value).strip()
    if not text:
        raise ValueError("empty")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(UTC)
