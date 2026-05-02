from types import SimpleNamespace
from unittest.mock import patch

from galaxy.agents.operations import AgentOperationsManager


class MutatingWorkflowContentsManager:
    def ensure_raw_description(self, definition):
        return SimpleNamespace(as_dict=definition)

    def build_workflow_from_raw_description(self, trans, raw_workflow_description, create_options, source=None):
        raw_workflow_description.as_dict["steps"]["0"]["subworkflow"] = object()
        return SimpleNamespace(
            stored_workflow=SimpleNamespace(id=1, name="Imported IWC workflow"),
            missing_tools=[("missing/tool", "Missing Tool", "1.0", "0")],
        )


def test_import_workflow_from_iwc_does_not_mutate_cached_definition():
    definition = {
        "name": "IWC workflow with subworkflow",
        "annotation": "",
        "tags": [],
        "steps": {
            "0": {
                "id": 0,
                "type": "subworkflow",
                "subworkflow": {
                    "name": "Embedded subworkflow",
                    "annotation": "",
                    "tags": [],
                    "steps": {},
                },
            }
        },
    }
    manifest = [
        {
            "workflows": [
                {
                    "trsID": "#workflow/github.com/iwc-workflows/with-subworkflow/main",
                    "definition": definition,
                }
            ]
        }
    ]
    app = SimpleNamespace(workflow_contents_manager=MutatingWorkflowContentsManager())
    trans = SimpleNamespace(security=SimpleNamespace(encode_id=lambda value: f"encoded-{value}"))
    ops = AgentOperationsManager(app, trans)

    with patch("galaxy.agents.iwc.fetch_manifest", return_value=manifest):
        result = ops.import_workflow_from_iwc("#workflow/github.com/iwc-workflows/with-subworkflow/main")

    assert result["id"] == "encoded-1"
    assert result["missing_tools"] == ["missing/tool"]
    assert isinstance(definition["steps"]["0"]["subworkflow"], dict)
