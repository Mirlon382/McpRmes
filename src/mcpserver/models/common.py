"""Constrained types shared by the tool parameters of every source."""

from typing import Annotated

from pydantic import Field, StringConstraints

# Deliberately not settings, unlike ToolLimits in settings.py: they say what a valid value is, not how much
# a call may cost. A search query is a few keywords and synonyms; past this it is abuse or a pasted document.
MAX_SEARCH_TEXT_CHARS = 500

# A place name, a graph URI fragment: short by nature.
MAX_SHORT_TEXT_CHARS = 200

# Wide enough for every historical series and for the 1900/2100 defaults of search_melodi_datasets;
# what it stops is a typo or a made-up value (`20244`, `-1`) reaching Elasticsearch as a filter.
MIN_YEAR = 1900
MAX_YEAR = 2100

# Control characters and DEL, except tab, line feed and carriage return. They carry no meaning in a
# search, and in a log line they can fake or hide content.
NO_CONTROL_CHARS_PATTERN = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"

# ----------------------------------------------------------------------------------------------------------------------
# Types ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------

# Free text sent to a search engine. Surrounding whitespace is dropped first, so "   " counts as empty.
SearchText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SEARCH_TEXT_CHARS,pattern=NO_CONTROL_CHARS_PATTERN),
]

Year = Annotated[int, Field(ge=MIN_YEAR, le=MAX_YEAR)]

ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SHORT_TEXT_CHARS,pattern=NO_CONTROL_CHARS_PATTERN),
]