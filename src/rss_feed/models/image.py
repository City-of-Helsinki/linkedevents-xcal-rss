from typing import Optional

from pydantic_xml import BaseXmlModel, element


class Image(BaseXmlModel):
    url: str = element(
        tag="url",
        default=None,
    )
    title: str = element(
        tag="title",
        default=None,
    )
    link: str = element(
        tag="link",
        default=None,
    )

    width: Optional[int] = element(
        tag="width",
        default=None,
    )
    height: Optional[int] = element(
        tag="height",
        default=None,
    )
    description: Optional[str] = element(
        tag="description",
        default=None,
    )
