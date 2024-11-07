import html
import re
from typing import Optional

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, element


class Image(BaseXmlModel):
    @field_serializer("url", "title", "link", "description")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    url: str = element(
        tag="url", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    title: str = element(
        tag="title", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    link: str = element(
        tag="link", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )

    width: Optional[int] = element(
        tag="width", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    height: Optional[int] = element(
        tag="height", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
    description: Optional[str] = element(
        tag="description", default=None, nsmap={"": "urn:ietf:params:xml:ns:xcal"}
    )
