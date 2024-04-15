from typing import Optional

from pydantic_xml import BaseXmlModel, attr


class Cloud(BaseXmlModel):
    domain: Optional[str] = attr(name="domain")
    port: Optional[str] = attr(name="port")
    path: Optional[str] = attr(name="path")
    register_procedure: Optional[str] = attr(name="registerProcedure")
    protocol: Optional[str] = attr(name="protocol")
