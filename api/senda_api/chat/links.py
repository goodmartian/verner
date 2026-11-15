"""Links in the text of an answer: the only one is a drawn shape, `[the way out](shape:A3)`. The interface turns it into
something to click, so a target that names no shape drawn so far in the chat (or any other link) would be a dead link:
it is reduced to its label."""

import re

LINK = re.compile(r"\[([^\]\n]{1,120})\]\(([^)\s\n]{1,80})\)")
SHAPE = re.compile(r"^shape:A([1-9]\d{0,5})$")


def only_known(text: str, shapes: int) -> str:
    """The text with every link kept that names one of the `shapes` shapes drawn so far, and the rest as their labels."""

    def keep(found: re.Match) -> str:
        target = SHAPE.match(found.group(2))
        return found.group(0) if target and int(target.group(1)) <= shapes else found.group(1)

    return LINK.sub(keep, text)
