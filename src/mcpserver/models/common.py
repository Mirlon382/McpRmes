"""Constrained types shared by the tool parameters."""

from typing import Annotated

from pydantic import StringConstraints

# Deliberately not settings, unlike ToolLimits in settings.py: they say what a valid value is, not how much
# a call may cost.

# A graph URI fragment, a short filter value: short by nature.
MAX_SHORT_TEXT_CHARS = 200

# Control characters and DEL, except tab, line feed and carriage return. They carry no meaning in a
# filter, and in a log line they can fake or hide content.
NO_CONTROL_CHARS_PATTERN = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"

# ----------------------------------------------------------------------------------------------------------------------
# Types ----------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------------

# Free text used as a filter. Surrounding whitespace is dropped first, so "   " counts as empty.
ShortText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SHORT_TEXT_CHARS,
        pattern=NO_CONTROL_CHARS_PATTERN,
    ),
]
