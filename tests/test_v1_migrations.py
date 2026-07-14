from django.apps import apps
from django.db import migrations
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState


PROJECT_APPS = {
    "audit",
    "harness",
    "integrations",
    "mcp",
    "orders",
    "policy",
    "portfolio",
}
V1_INITIAL = "0001_v1_initial"


def test_project_apps_have_only_clean_v1_initial_migrations() -> None:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    project_nodes = {node for node in loader.graph.nodes if node[0] in PROJECT_APPS}

    assert project_nodes == {(app_label, V1_INITIAL) for app_label in PROJECT_APPS}
    for app_label, migration_name in project_nodes:
        migration = loader.get_migration(app_label, migration_name)
        assert migration.initial is True
        assert not migration.replaces
        assert not any(isinstance(operation, migrations.RunPython) for operation in migration.operations)
        assert all(
            dependency[1] == V1_INITIAL
            for dependency in migration.dependencies
            if dependency[0] in PROJECT_APPS
        )

    assert ("orders", "orderintent") not in loader.project_state().models


def test_v1_migration_graph_matches_current_models() -> None:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    changes = MigrationAutodetector(
        loader.project_state(),
        ProjectState.from_apps(apps),
    ).changes(graph=loader.graph)

    assert not {app_label: changes[app_label] for app_label in PROJECT_APPS if app_label in changes}
