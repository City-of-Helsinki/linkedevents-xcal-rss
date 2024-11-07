from typing import Optional
import html
import re

from pydantic import field_serializer
from pydantic_xml import BaseXmlModel, attr


class Cloud(BaseXmlModel):
    @field_serializer("domain", "port", "path", "register_procedure", "protocol")
    def escape_xml(string: str) -> str:
        if string:
            return html.escape(re.sub(u'[^\u0020-\uD7FF\u0009\u000A\u000D\uE000-\uFFFD\U00010000-\U0010FFFF]+', '', string), quote=False)
        else:
            return

    domain: Optional[str] = attr(name="domain")
    port: Optional[str] = attr(name="port")
    path: Optional[str] = attr(name="path")
    register_procedure: Optional[str] = attr(name="registerProcedure")
    protocol: Optional[str] = attr(name="protocol")
