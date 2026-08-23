from pydantic import BaseModel, Field

#: What an event may be called: a slug of lowercase words joined by
#: underscores or dots, starting with a letter — `app_open`,
#: `settings.viewed`. The pattern is the whole defence against the events
#: table holding prose: anything that could carry a sentence is refused at
#: the door rather than redacted later.
_NAME = r"^[a-z][a-z0-9_.]{0,63}$"

#: More than any honest flush and few enough that a stuck client retrying a
#: giant batch cannot make one request expensive. The app reports moments,
#: not streams.
MAX_EVENTS_PER_REPORT = 25


class EventIn(BaseModel):
    """One reported moment. The server supplies the clock and the user."""

    name: str = Field(pattern=_NAME)


class EventReport(BaseModel):
    """A batch, because a phone coming back online may owe a few at once."""

    events: list[EventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_REPORT)
