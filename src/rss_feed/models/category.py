from typing import Optional
import html
import re

from pydantic_xml import BaseXmlModel, attr
from pydantic import field_serializer


class Category(BaseXmlModel):
    @field_serializer("content", "domain")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    content: str
    domain: Optional[str] = attr(name="domain")
