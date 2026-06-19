from basecamp.installer import (
    COMPONENT_COMPANION,
    COMPONENT_ENGINEERING,
    COMPONENT_STANDARD,
    COMPONENT_SWARM,
    resolve_install_selection,
)


def package_paths(component_ids: list[str]) -> list[str]:
    return [path for path, _label in resolve_install_selection(component_ids).ts_packages]


def test_all_groups_selected_includes_non_memory_packages_and_companion_extra() -> None:
    selection = resolve_install_selection(
        [COMPONENT_STANDARD, COMPONENT_ENGINEERING, COMPONENT_COMPANION, COMPONENT_SWARM]
    )

    assert selection.python_extra == "[companion]"
    assert package_paths([COMPONENT_STANDARD, COMPONENT_ENGINEERING, COMPONENT_COMPANION, COMPONENT_SWARM]) == [
        "core/pi",
        "pi-ui",
        "workspace/pi",
        "pi-tasks",
        "pi-git",
        "pi-engineering",
        "pi-companion/pi",
        "pi-swarm/extension",
    ]


def test_companion_unchecked_omits_companion_extra_and_ts_package() -> None:
    selection = resolve_install_selection([COMPONENT_STANDARD, COMPONENT_ENGINEERING, COMPONENT_SWARM])

    assert selection.python_extra == ""
    paths = [path for path, _label in selection.ts_packages]
    assert "pi-companion/pi" not in paths
    assert paths == [
        "core/pi",
        "pi-ui",
        "workspace/pi",
        "pi-tasks",
        "pi-git",
        "pi-engineering",
        "pi-swarm/extension",
    ]


def test_swarm_auto_includes_required_standard_packages() -> None:
    assert package_paths([COMPONENT_SWARM]) == [
        "core/pi",
        "pi-ui",
        "pi-tasks",
        "pi-swarm/extension",
    ]


def test_core_pi_is_always_first_and_not_duplicated() -> None:
    paths = package_paths([COMPONENT_STANDARD, COMPONENT_SWARM])

    assert paths[0] == "core/pi"
    assert paths.count("core/pi") == 1
    assert paths.count("pi-ui") == 1
    assert paths.count("pi-tasks") == 1
