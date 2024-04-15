from typing import Optional

from pydantic_xml import BaseXmlModel, attr


class GUID(BaseXmlModel):
    content: str
    is_permalink: Optional[bool] = attr(
        name="isPermalink",
        default=None,
    )
