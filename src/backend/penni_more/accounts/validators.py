"""Validation boundaries for database-resident currency flag uploads."""

from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from django.core.exceptions import ValidationError

MAX_FLAG_SVG_BYTES = 64 * 1024
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


class UploadedFlag(Protocol):
    """The portion of Django's uploaded-file interface used by validation."""

    name: str
    content_type: str | None

    def read(self, size: int = -1, /) -> bytes: ...


def validate_flag_svg(upload: UploadedFlag) -> str:
    """Validate a small UTF-8 SVG upload and return its decoded text."""
    if Path(upload.name).suffix.lower() != ".svg":
        raise ValidationError("Upload a file with an .svg extension.", code="extension")
    if upload.content_type and upload.content_type != "image/svg+xml":
        raise ValidationError("The uploaded file must use the image/svg+xml type.", code="type")

    content = upload.read(MAX_FLAG_SVG_BYTES + 1)
    if len(content) > MAX_FLAG_SVG_BYTES:
        raise ValidationError("The SVG flag must be 64 KiB or smaller.", code="size")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError("The SVG flag must be valid UTF-8.", code="encoding") from error

    lowered = text.lower()
    if "\x00" in text:
        raise ValidationError("The SVG flag cannot contain NUL bytes.", code="nul")
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValidationError(
            "DOCTYPE and ENTITY declarations are not allowed.", code="declaration"
        )
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValidationError("The uploaded file is not valid XML.", code="xml") from error
    if root.tag != f"{{{SVG_NAMESPACE}}}svg":
        raise ValidationError("The uploaded file must have an SVG root element.", code="root")
    return text
