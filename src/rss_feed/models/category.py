from typing import Optional

from pydantic_xml import BaseXmlModel, attr


class Category(BaseXmlModel):
    content: str
    domain: Optional[str] = attr(name="domain")
