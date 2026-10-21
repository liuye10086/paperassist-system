"""Server-owned signed-number policy for new approvals, not legacy/raw replay."""
import re
import unicodedata

NUMERIC_VERSION=2
SIGNS=str.maketrans({'−':'-','－':'-','﹣':'-','＋':'+','﹢':'+'})
SIGNED=re.compile(r'[+-]?\s*(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE]\s*[+-]?\s*[0-9]+)?')
MARKERS=re.compile(r'(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE]\s*[-+]?\s*[0-9]+)?|[-+]')


def validation_version(value):
    if type(value) is not int or value not in (1,NUMERIC_VERSION):raise ValueError('Unknown numeric validation version')
    return value


def normalized(text):
    # Plus/minus uncertainty and superscript/subscript signs cannot certify one
    # exact frozen value. Refuse them instead of silently extracting a magnitude.
    if any(c in text for c in '±∓⁺⁻₊₋➕➖') or any(c.isdecimal() and c not in '0123456789' for c in text):
        raise ValueError('Ambiguous numeric notation requires an explicit supported signed value')
    text=text.translate(SIGNS)
    if re.search(r'[+-]\s*[+-]',text):raise ValueError('Compound numeric signs require an unambiguous signed value')
    return text


def canonical(token):
    return re.sub(r'\s+','',token).removeprefix('+')


def numbers(text):
    text=normalized(text)
    # A sign outside a group is not consumed by SIGNED. Do not certify its
    # inner magnitude: grouped expressions require formula interpretation.
    if any(unicodedata.category(m[1])=='Ps' for m in re.finditer(r'[+-]\s*(\S)',text)):
        raise ValueError('Signed parenthesized expressions require an explicit supported signed value')
    return [canonical(m[0]) for m in SIGNED.finditer(text)]


def value(text):
    text=normalized(text)
    match=SIGNED.fullmatch(text.strip())
    if not match:raise ValueError('Numeric binding must contain one complete signed value')
    return canonical(match[0])


def language_markers(text):
    # Unlike scientific value equivalence, textual invariance also retains
    # standalone + / - operators (Q3−Q1, A + 5) and conservatively all hyphens.
    return [re.sub(r'\s+','',m[0]) for m in MARKERS.finditer(normalized(text))]


def checker_text(text):
    """Canonical numeric projection only after exact v2 authority is verified."""
    return SIGNED.sub(lambda m:re.match(r'\s*',m[0])[0]+canonical(m[0]),normalized(text))
