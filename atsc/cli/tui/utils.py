from asciimatics.widgets import Text


def text(txt: str) -> Text:
    rv = Text(readonly=True)
    rv.value = txt
    return rv
