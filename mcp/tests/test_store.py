from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cryptography.fernet import Fernet

from patentradar_mcp.security import SecretBox
from patentradar_mcp.store import Store


def test_workspace_keys_are_encrypted_and_isolated(tmp_path: Path) -> None:
    db_path = tmp_path / "store.sqlite3"
    store = Store(db_path, SecretBox(Fernet.generate_key()))
    first_id, first_token = store.create_workspace()
    second_id, second_token = store.create_workspace()

    store.update_keys(first_id, {"tavily": "tvly-secret-value"})

    assert store.authenticate(first_token) == first_id
    assert store.authenticate(second_token) == second_id
    assert store.key_status(first_id)["tavily"] is True
    assert store.key_status(second_id)["tavily"] is False
    assert store.decrypted_keys(first_id) == {"tavily": "tvly-secret-value"}
    assert b"tvly-secret-value" not in db_path.read_bytes()


def test_case_cannot_be_read_from_another_workspace(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.sqlite3", SecretBox(Fernet.generate_key()))
    owner_id, _ = store.create_workspace()
    stranger_id, _ = store.create_workspace()
    case = store.create_case(owner_id, "CN114512759B")

    try:
        store.get_case(stranger_id, case["id"])
    except KeyError as exc:
        assert "不属于当前工作区" in str(exc)
    else:
        raise AssertionError("cross-workspace case read should fail")


def test_three_workspaces_can_create_cases_concurrently(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.sqlite3", SecretBox(Fernet.generate_key()))
    workspace_ids = [store.create_workspace()[0] for _ in range(3)]

    with ThreadPoolExecutor(max_workers=3) as executor:
        cases = list(
            executor.map(
                lambda workspace_id: store.create_case(workspace_id, "CN114512759B"),
                workspace_ids,
            )
        )

    assert len({case["id"] for case in cases}) == 3
    assert {case["workspace_id"] for case in cases} == set(workspace_ids)


def test_provider_search_batches_are_merged(tmp_path: Path) -> None:
    store = Store(tmp_path / "store.sqlite3", SecretBox(Fernet.generate_key()))
    workspace_id, _ = store.create_workspace()
    case = store.create_case(workspace_id, "CN114512759B")

    store.save_search_results(
        workspace_id,
        case["id"],
        {"queries": ["查询一"], "search_modes": ["discovery"], "configured_providers": ["tavily"], "results": [{"url": "https://a.example"}], "errors": []},
        stage="module_2_competitor_search",
    )
    merged = store.save_search_results(
        workspace_id,
        case["id"],
        {"queries": ["查询二"], "search_modes": ["evidence"], "configured_providers": ["tavily"], "results": [{"url": "https://b.example"}], "errors": []},
        stage="module_2_competitor_search",
    )

    bucket = merged["artifacts"]["_provider_search"]["module_2_competitor_search"]
    assert bucket["queries"] == ["查询一", "查询二"]
    assert bucket["search_modes"] == ["discovery", "evidence"]
    assert bucket["result_count"] == 2
