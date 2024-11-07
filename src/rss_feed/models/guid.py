import html
import re
from typing import Optional

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, attr


class GUID(BaseXmlModel):
    @field_serializer("content")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    content: str
    is_permalink: Optional[bool] = attr(
        name="isPermalink",
        default=None,
    )
