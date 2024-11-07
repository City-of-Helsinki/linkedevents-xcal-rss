import html
import re

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, attr


class Enclosure(BaseXmlModel):
    @field_serializer("url", "type")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    url: str = attr(name="url")
    length: int = attr(name="length")
    type: str = attr(name="type")
