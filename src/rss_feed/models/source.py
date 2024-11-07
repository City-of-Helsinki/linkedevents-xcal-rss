import html
import re
from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, attr


class Source(BaseXmlModel):
    @field_serializer("content", "url")
    def escape_xml(string: str) -> str:
        return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=True)

    content: str
    url: str = attr(name="url")
