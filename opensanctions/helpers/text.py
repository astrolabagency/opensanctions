import re
from banal import is_listish
from typing import Optional, List, Union
from normality import collapse_spaces

PREFIX_ = "INTERPOL-UN\s*Security\s*Council\s*Special\s*Notice\s*web\s*link:?"
PREFIX = re.compile(PREFIX_, re.IGNORECASE)

INTERPOL_URL_ = "https?:\/\/www\.interpol\.int\/[^ ]*(\s\d+)?"
INTERPOL_URL = re.compile(INTERPOL_URL_, re.IGNORECASE)
BRACKETED = re.compile(r"\(.*\)")


def clean_note(text: Union[Optional[str], List[Optional[str]]]) -> List[str]:
    out: List[str] = []
    if text is None:
        return out
    if is_listish(text):
        for t in text:
            out.extend(clean_note(t))
        return out
    text = PREFIX.sub(" ", text)
    text = INTERPOL_URL.sub(" ", text)
    text = collapse_spaces(text)
    if text is None:
        return out
    return [text]


def is_empty(text: Optional[str]) -> bool:
    """Check if the given text is empty: it can either be null, or
    the stripped version of the string could have 0 length."""
    if text is None:
        return True
    if isinstance(text, str):
        text = text.strip()
        return len(text) == 0
    return False


def remove_bracketed(text):
    """Helps to deal with property values where additional info has been supplied in
    brackets that makes it harder to parse the value. Examples:

    - Russia (former USSR)
    - 1977 (as Muhammad Da'ud Salman)

    It's probably not useful in all of these cases to try and parse and derive meaning
    from the bracketed bit, so we'll just discard it.
    """
    if text is None:
        return
    return BRACKETED.sub(" ", text)
