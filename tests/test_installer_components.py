import questionary

from basecamp.installer import (
    COMPONENT_COMPANION,
    COMPONENT_ENGINEERING,
    COMPONENT_STANDARD,
    COMPONENT_SWARM,
    _component_choices,
    resolve_install_selection,
)


def package_paths(component_ids: list[str]) -> list[str]:
    return [path for path, _label in resolve_install_selection(component_ids).ts_packages]


def test_all_groups_selected_includes_non_memory_packages_and_python_extras() -> None:
    selection = resolve_install_selection(
        [COMPONENT_STANDARD, COMPONENT_ENGINEERING, COMPONENT_COMPANION, COMPONENT_SWARM]
    )

    assert selection.python_extra == "[companion,swarm]"
    assert selection.python_extras == ("companion", "swarm")
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

    assert selection.python_extra == "[swarm]"
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


def test_swarm_auto_includes_required_standard_packages_and_python_extra() -> None:
    selection = resolve_install_selection([COMPONENT_SWARM])

    assert selection.python_extra == "[swarm]"
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


def test_component_choices_are_unselected_by_default() -> None:
    assert all(not choice.checked for choice in _component_choices())


def test_component_checkbox_prompt_constructs_without_default_value_error() -> None:
    prompt = questionary.checkbox(
        "Select optional components to install:",
        choices=_component_choices(),
    )

    assert prompt is not None
