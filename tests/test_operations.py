import pytest

from app.operations import DESKTOP, SERVER, collect, operation


def test_operation_failure_metadata_and_host_flags():
    class Example:
        @operation(write=True, hosts=(DESKTOP,), failure="Could not save.")
        def save(self, value):
            return {"ok": True}

        @operation(write=False)
        def read(self):
            return {"ok": True}

    registry = collect(Example)
    assert registry["save"].failure == "Could not save."
    assert registry["save"].hosts == {DESKTOP}
    assert registry["save"].bind({"value": 1}) == {"value": 1}
    assert registry["read"].failure is None
    assert registry["read"].hosts == {DESKTOP, SERVER}


def test_registry_overrides_and_private_host_context():
    from app.operations import private_context

    class Shared:
        @operation(write=True, failure="Shared failure.")
        async def save(self, value=1):
            return value

    class Desktop:
        @operation(write=True, hosts=(DESKTOP,), timeout=20, failure="Desktop failure.")
        async def save(self, value=2, *, owner=None):
            return value

    registry = collect(Shared, Desktop)
    assert registry["save"].hosts == {DESKTOP}
    assert registry["save"].failure == "Desktop failure."
    assert registry["save"].timeout == 20
    assert registry["save"].bind({}) == {}
    assert private_context(Desktop().save, owner=b"host", ignored=True) == {"owner": b"host"}
    with pytest.raises(ValueError) as error:
        registry["save"].bind({"owner": "frontend"})
    assert error.value.code == "validation.unknown_field"


@pytest.mark.parametrize("payload", [None, [], "value", {"extra": True}, {}])
def test_operation_arguments_reject_invalid_payloads(payload):
    class Example:
        @operation(write=True)
        def save(self, value):
            pass

    with pytest.raises(ValueError):
        collect(Example)["save"].bind(payload)


def test_declared_argument_types_are_validated_before_dispatch():
    from pydantic import StrictBool
    from app.errors import UserError

    class Example:
        @operation(write=True)
        def save(self, enabled: StrictBool):
            raise AssertionError("must not dispatch")

    registered = collect(Example)["save"]
    with pytest.raises(UserError) as error:
        registered.bind({"enabled": "false"})
    assert error.value.code == "validation.type"
    assert error.value.params == {"field": "enabled", "expected": "boolean"}


def test_settings_payloads_use_models_and_keep_missing_defaults_out_of_the_call():
    from app.management import ApplicationManagement
    from app.errors import UserError

    registered = collect(ApplicationManagement)["save_custom_command"]
    command = {"name": "Greet", "enabled": True, "responses": ["Hello"],
               "permission": "USER", "per_user_seconds": 0, "global_seconds": 0, "aliases": []}
    bound = registered.bind({"command": command})["command"]
    assert bound["name"] == "greet"
    assert "id" not in bound
    assert bound["response_mode"] == "single"
    assert "stream_availability" not in bound
    with pytest.raises(UserError) as error:
        registered.bind({"command": {**command, "enabled": "false"}})
    assert error.value.code == "validation.type"
    assert error.value.params == {"field": "enabled", "expected": "boolean"}
