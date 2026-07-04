import importlib.machinery
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "tests" / "c4d_runner" / "run_fixtures.py"


def _load_runner_module():
    module_name = "sentinel_fixture_runner_under_test"
    sys.modules.pop(module_name, None)
    loader = importlib.machinery.SourceFileLoader(module_name, str(RUNNER_PATH))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def test_placeholder_guid_values_preserves_path_and_sibling_index(sentinel_module):
    runner = _load_runner_module()

    value = {
        "check_id": "default_names",
        "violations": [
            {
                "identity": {
                    "type": "object",
                    "path": "/parent/Cube[1]",
                    "sibling_index": 1,
                    "guid": "volatile-guid",
                },
                "extras": {
                    "nested": {
                        "guid": "another-volatile-guid",
                        "path": "/keep/this/path",
                    }
                },
            }
        ],
    }

    assert runner._placeholder_guid_values(value) == {
        "check_id": "default_names",
        "violations": [
            {
                "identity": {
                    "type": "object",
                    "path": "/parent/Cube[1]",
                    "sibling_index": 1,
                    "guid": "<guid>",
                },
                "extras": {
                    "nested": {
                        "guid": "<guid>",
                        "path": "/keep/this/path",
                    }
                },
            }
        ],
    }
