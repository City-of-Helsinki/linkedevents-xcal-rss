import html
import re
from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, element


class TextInput(BaseXmlModel):
    @field_serializer("title", "description", "name", "link")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    title: str = element(tag="title")
    description: str = element(tag="description")
    name: str = element(tag="name")
    link: str = element(tag="link")
