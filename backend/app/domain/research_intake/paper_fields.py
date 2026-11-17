from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ContentText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


def unique_keywords(keywords: list[str]) -> list[str]:
    if len({keyword.lower() for keyword in keywords}) != len(keywords):
        raise ValueError('Keywords must be unique.')
    return keywords


PaperKeywords = Annotated[list[ShortText], Field(min_length=4, max_length=6), AfterValidator(unique_keywords)]
