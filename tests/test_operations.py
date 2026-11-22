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
    assert error.value.code == "operations.invalid_operation_arguments"


@pytest.mark.parametrize("payload", [None, [], "value", {"extra": True}, {}])
def test_operation_arguments_reject_invalid_payloads(payload):
    class Example:
        @operation(write=True)
        def save(self, value):
            pass

    with pytest.raises(ValueError):
        collect(Example)["save"].bind(payload)
