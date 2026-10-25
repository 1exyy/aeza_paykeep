from dataclasses import dataclass

from fastapi import Query


@dataclass
class Page:
    limit: int
    offset: int


def page_params(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> Page:
    return Page(limit=limit, offset=offset)
