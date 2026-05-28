import typing as t

import pytest
from pydantic import BaseModel

from brain_researcher.services.tools.schema_fixer import (
    _schema_for_type,
    generate_fixed_schema,
)


@pytest.mark.unit
def test_tuple_optional_pep604():
    schema = _schema_for_type(tuple[int, int] | None)
    assert schema == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
        "nullable": True,
    }


@pytest.mark.unit
def test_tuple_optional_typing_tuple():
    schema = _schema_for_type(t.Tuple[int, int] | None)
    assert schema == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
        "nullable": True,
    }


@pytest.mark.unit
def test_list_string_optional():
    schema = _schema_for_type(list[str] | None)
    assert schema["type"] == "array"
    assert schema["items"] == {"type": "string"}
    assert schema.get("nullable") is True


@pytest.mark.unit
def test_dict_str_int_schema():
    schema = _schema_for_type(dict[str, int])
    assert schema["type"] == "object"
    assert schema["additionalProperties"] == {"type": "integer"}


@pytest.mark.unit
def test_enum_filters_empty_string():
    from enum import Enum

    class E(Enum):
        A = "a"
        EMPTY = ""
        B = "b"

    schema = _schema_for_type(E)
    assert schema["type"] == "string"
    # empty string should be filtered out
    assert set(schema["enum"]) == {"a", "b"}


@pytest.mark.unit
def test_generate_fixed_schema_with_nested_fields():
    class M(BaseModel):
        coords: tuple[int, int] | None
        names: list[str] | None
        meta: dict[str, int]

    schema = generate_fixed_schema(M)
    assert schema["type"] == "object"
    props = schema["properties"]

    # coords: tuple[int, int] | None
    assert props["coords"]["type"] == "array"
    assert props["coords"]["items"] == {"type": "integer"}
    assert props["coords"]["minItems"] == 2
    assert props["coords"]["maxItems"] == 2
    assert props["coords"].get("nullable") is True

    # names: list[str] | None
    assert props["names"]["type"] == "array"
    assert props["names"]["items"] == {"type": "string"}
    assert props["names"].get("nullable") is True

    # meta: dict[str, int]
    assert props["meta"]["type"] == "object"
    assert props["meta"]["additionalProperties"] == {"type": "integer"}

