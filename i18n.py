"""Minimale Uebersetzungsschicht (Deutsch/Englisch).

Der deutsche Text ist zugleich der Schluessel: tr("Quellordner:") liefert bei
Sprache 'de' den Text selbst, bei 'en' die Uebersetzung aus EN. Platzhalter
({name}) werden per str.format ersetzt. Fehlt eine Uebersetzung, wird der
deutsche Text verwendet (nie ein Absturz)."""

LANG = "de"
LANGUAGES = {"de": "Deutsch", "en": "English"}


def set_lang(lang: str):
    global LANG
    LANG = lang if lang in LANGUAGES else "de"


def get_lang() -> str:
    return LANG


def tr(text: str, **kw) -> str:
    s = EN.get(text, text) if LANG == "en" else text
    return s.format(**kw) if kw else s


from en_dict import EN_PAIRS as EN  # noqa: E402
