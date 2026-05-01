"""Direct tests for the semantic validators on ``UserToolSource``.

These tests construct ``UserToolSource`` payloads in-memory and assert that
each rule (id pattern, container shape, citation shape, undeclared
``inputs.<name>`` references in ``shell_command`` / ``configfiles``,
output discovery requirements, blank required fields) raises a
``ValidationError`` whose distilled output identifies the offending field.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from galaxy.tool_util_models import (
    format_validation_errors,
    UserToolSource,
)

VALID_TOOL = {
    "class": "GalaxyUserTool",
    "id": "my-cool-tool",
    "name": "My Cool Tool",
    "version": "0.1.0",
    "description": "A cool tool.",
    "container": "quay.io/biocontainers/python:3.13",
    "shell_command": "head -n '$(inputs.n_lines)' '$(inputs.data_input.path)' > out.txt",
    "inputs": [
        {"type": "integer", "name": "n_lines"},
        {"type": "data", "name": "data_input"},
    ],
    "outputs": [
        {"type": "data", "name": "out", "from_work_dir": "out.txt"},
    ],
    "citations": [
        {"type": "doi", "content": "10.1234/abc.def"},
    ],
}


def _doc(**overrides):
    base = deepcopy(VALID_TOOL)
    base.update(overrides)
    return base


def _assert_error_contains(exc: ValidationError, needle: str) -> None:
    flat = " | ".join(format_validation_errors(exc))
    assert needle in flat, f"expected substring {needle!r} in errors:\n{flat}"


def test_happy_path():
    UserToolSource.model_validate(VALID_TOOL)


def test_hyphenated_id_is_accepted():
    UserToolSource.model_validate(_doc(id="with-hyphens-and_underscores"))


@pytest.mark.parametrize(
    "bad_id",
    ["My-Tool", "1starts_with_digit", "has space", "trailing!", "_leading_underscore"],
)
def test_invalid_id_rejected(bad_id):
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(_doc(id=bad_id))
    _assert_error_contains(info.value, "String should match pattern")


@pytest.mark.parametrize("bad_container", ["", "   ", "definitely not a container", "foo bar baz"])
def test_invalid_container_rejected(bad_container):
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(_doc(container=bad_container))
    _assert_error_contains(info.value, "container")


@pytest.mark.parametrize(
    "container",
    [
        "quay.io/biocontainers/samtools:1.17",
        "docker://my-registry/image:tag",
        "oras://example.org/image",
        "busybox",
        "ubuntu:latest",
        "library/python:3.11-slim",
    ],
)
def test_valid_container_shapes(container):
    UserToolSource.model_validate(_doc(container=container))


def test_blank_name_rejected():
    # Long enough to clear `min_length=5`, so the whitespace-rejection
    # field_validator is what fires.
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(_doc(name="       "))
    _assert_error_contains(info.value, "must not be empty or whitespace")


def test_undeclared_inputs_ref_in_shell_command():
    bad = _doc(shell_command="echo $(inputs.foo)")
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "inputs.foo")


def test_conditional_top_level_name_resolves_for_nested_ref():
    """`$(inputs.cond.test_parameter)` must validate against the conditional's
    top-level name, not its nested `test_parameter` -- a regression test
    for the false-positive concern with conditionals/repeats/sections.
    """
    UserToolSource.model_validate(
        _doc(
            shell_command="echo $(inputs.cond.test_parameter) > out.txt",
            inputs=[
                {
                    "type": "conditional",
                    "name": "cond",
                    "test_parameter": {"type": "boolean", "name": "test_parameter"},
                    "whens": [
                        {"discriminator": True, "parameters": []},
                        {"discriminator": False, "parameters": []},
                    ],
                }
            ],
        )
    )


def test_repeat_and_section_top_level_names_resolve():
    UserToolSource.model_validate(
        _doc(
            shell_command="echo $(inputs.my_repeat[0].x) $(inputs.my_section.y) > out.txt",
            inputs=[
                {"type": "repeat", "name": "my_repeat", "parameters": []},
                {"type": "section", "name": "my_section", "parameters": []},
            ],
        )
    )


def test_undeclared_inputs_ref_in_configfile():
    bad = _doc(
        configfiles=[
            {
                "name": "script",
                "filename": "script.sh",
                "content": "echo $(inputs.unknown)",
                "eval_engine": "ecmascript",
            }
        ]
    )
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "inputs.unknown")


def test_data_output_without_from_work_dir_or_discovery_rejected():
    bad = _doc(outputs=[{"type": "data", "name": "out"}])
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "from_work_dir")


def test_collection_output_without_discover_rejected():
    bad = _doc(
        outputs=[
            {
                "type": "collection",
                "name": "outs",
                "structure": {"collection_type": "list"},
            }
        ]
    )
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "discover_datasets")


def test_invalid_doi_citation_rejected():
    bad = _doc(citations=[{"type": "doi", "content": "not-a-doi"}])
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "DOI")


def test_invalid_bibtex_citation_rejected():
    bad = _doc(citations=[{"type": "bibtex", "content": "no leading at-sign"}])
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    _assert_error_contains(info.value, "bibtex")


def test_unknown_type_citation_with_doi_content_accepted():
    UserToolSource.model_validate(_doc(citations=[{"type": "reference", "content": "10.1234/abc.def"}]))


def test_no_citations_accepted():
    UserToolSource.model_validate(_doc(citations=None))


def test_format_validation_errors_distills_loc_and_msg():
    bad = _doc(id="BAD-ID", container="")
    with pytest.raises(ValidationError) as info:
        UserToolSource.model_validate(bad)
    assert format_validation_errors(info.value) == [
        "id: String should match pattern '^[a-z][a-z0-9_-]*$'",
        "container: Value error, container must not be empty",
    ]
