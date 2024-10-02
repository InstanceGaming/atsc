from rich.text import Text
from atsc.common.constants import FLOAT_PRECISION_TIME


def boolean_text(condition: bool,
                 txt1: str,
                 txt1_style: str,
                 txt2: str,
                 txt2_style: str):
    if condition:
        return Text(txt1, style=txt1_style)
    else:
        return Text(txt2, style=txt2_style)


def text_or_dash(condition: bool, txt: str, txt_style: str):
    return boolean_text(condition, txt, txt_style, '-', 'bright_black')


def get_time_text(v: float, force_style=None):
    rounded = round(v, FLOAT_PRECISION_TIME)
    text = Text(format(rounded, '.1f'))
    if v < 0.0:
        color = 'red'
    else:
        color = 'white'
    text.stylize(force_style or color)
    return text


def combine_texts_new_line(*texts) -> Text:
    text = texts[0]
    for i in range(1, len(texts)):
        text = text.append('\n')
        if i < len(texts):
            text = text.append_text(texts[i])
    return text
