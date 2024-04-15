from pydantic_xml import BaseXmlModel, attr


class Enclosure(BaseXmlModel):
    url: str = attr(name="url")
    length: int = attr(name="length")
    type: str = attr(name="type")
