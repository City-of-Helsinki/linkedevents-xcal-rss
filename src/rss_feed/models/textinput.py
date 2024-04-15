from pydantic_xml import BaseXmlModel, element


class TextInput(BaseXmlModel):
    title: str = element(tag="title")
    description: str = element(tag="description")
    name: str = element(tag="name")
    link: str = element(tag="link")
