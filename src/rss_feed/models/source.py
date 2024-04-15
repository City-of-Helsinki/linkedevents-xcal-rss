from pydantic_xml import BaseXmlModel, attr


class Source(BaseXmlModel):
    content: str
    url: str = attr(name="url")
