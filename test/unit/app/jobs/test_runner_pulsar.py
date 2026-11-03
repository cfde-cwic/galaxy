import os
import re
from typing import (
    Any,
    cast,
)

import pytest

from galaxy.app_unittest_utils.tools_support import UsesTools
from galaxy.jobs.runners.pulsar import (
    _tool_provided_metadata_client_outputs,
    PulsarComputeEnvironment,
)
from galaxy.model.store.discover import InvalidDiscoveredFilePathError
from galaxy.util.unittest import TestCase

INTERACTIVE_TOOL = """
<tool id="interactive_tool" name="Interactive Tool" tool_type="interactive" version="$version" profile="$profile">
    <entry_points>
        <entry_point name="Interactive Tool"><port>8080</port></entry_point>
    </entry_points>
    <outputs />
</tool>
"""
TOOL_WITH_EXTERNAL_METADATA_PATH = """
<tool id="external_metadata" name="External Metadata" version="$version" profile="$profile">
    <command>echo test</command>
    <inputs />
    <outputs provided_metadata_file="../outside.json" />
</tool>
"""


class TestPulsarToolProvidedMetadataClientOutputs(TestCase, UsesTools):
    def setUp(self):
        self.setup_app()
        cast(Any, self.app.config).interactivetools_enable = True
        self.tool_working_directory = os.path.join(self.test_directory, "working")
        os.makedirs(self.tool_working_directory)

    def tearDown(self):
        self.tear_down_app()

    def test_only_requests_enabled_tool_provided_metadata(self):
        enabled_tool = self._init_tool(profile="26.1", filename="enabled.xml")
        disabled_tool = self._init_tool(
            INTERACTIVE_TOOL,
            profile="26.1",
            filename="disabled.xml",
        )

        enabled_dynamic_output, enabled_file_sources = _tool_provided_metadata_client_outputs(
            enabled_tool, self.tool_working_directory
        )
        disabled_dynamic_output, disabled_file_sources = _tool_provided_metadata_client_outputs(
            disabled_tool, self.tool_working_directory
        )

        assert enabled_dynamic_output == re.escape("galaxy.json")
        assert enabled_file_sources == [{"path": "galaxy.json", "type": "galaxy"}]
        assert disabled_dynamic_output is None
        assert disabled_file_sources == []

    def test_rejects_metadata_path_outside_working_directory(self):
        tool = self._init_tool(
            TOOL_WITH_EXTERNAL_METADATA_PATH,
            profile="26.1",
            filename="external.xml",
        )

        with pytest.raises(InvalidDiscoveredFilePathError):
            _tool_provided_metadata_client_outputs(tool, self.tool_working_directory)


class _StubPathMapper:
    def __init__(self, remote_paths):
        self.remote_paths = remote_paths

    def remote_input_path_rewrite(self, local_path):
        return self.remote_paths.get(local_path)

    def remote_output_path_rewrite(self, local_path):
        return self.remote_paths.get(local_path)


class _StubLocalPathConfig:
    def input_path_rewrite(self, dataset):
        return None

    def output_path_rewrite(self, dataset):
        return None

    def input_extra_files_rewrite(self, dataset):
        return "/local/inputs/dataset_1_files"

    def output_extra_files_rewrite(self, dataset):
        return "/local/outputs/dataset_2_files"


class _StubDataset:
    def __init__(self, file_name, extra_files_path):
        self.file_name = file_name
        self.extra_files_path = extra_files_path

    def get_file_name(self):
        return self.file_name


def _compute_environment(remote_paths):
    compute_environment = PulsarComputeEnvironment.__new__(PulsarComputeEnvironment)
    compute_environment.path_mapper = _StubPathMapper(remote_paths)
    compute_environment.local_path_config = _StubLocalPathConfig()
    compute_environment.path_rewrites_input_extra = {}
    return compute_environment


def test_unstaged_input_extra_files_keep_local_path():
    # An input Pulsar reads in place (no staging) has no remote rewrite.
    compute_environment = _compute_environment({})
    dataset = _StubDataset("/local/inputs/dataset_1.dat", "/local/inputs/dataset_1_files")

    assert compute_environment.input_extra_files_rewrite(dataset) == "/local/inputs/dataset_1_files"
    assert compute_environment.path_rewrites_input_extra == {}


def test_staged_input_extra_files_are_rewritten():
    compute_environment = _compute_environment({"/local/inputs/dataset_1.dat": "/remote/inputs/dataset_1.dat"})
    dataset = _StubDataset("/local/inputs/dataset_1.dat", "/local/inputs/dataset_1_files")

    assert compute_environment.input_extra_files_rewrite(dataset) == "/remote/inputs/dataset_1_files"
    assert compute_environment.path_rewrites_input_extra == {
        "/local/inputs/dataset_1_files": "/remote/inputs/dataset_1_files"
    }


def test_unstaged_output_extra_files_keep_local_path():
    compute_environment = _compute_environment({})
    dataset = _StubDataset("/local/outputs/dataset_2.dat", "/local/outputs/dataset_2_files")

    assert compute_environment.output_extra_files_rewrite(dataset) == "/local/outputs/dataset_2_files"
