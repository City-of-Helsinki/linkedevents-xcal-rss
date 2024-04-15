from typing import Optional

from pydantic_xml import BaseXmlModel, element


class Image(BaseXmlModel):
    url: str = element(
        tag="url",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    title: str = element(
        tag="title",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    link: str = element(
        tag="link",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )

    width: Optional[int] = element(
        tag="width",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    height: Optional[int] = element(
        tag="height",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    description: Optional[str] = element(
        tag="description",
        default=None,
        nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
