from brain_researcher.legacy.api_gateway.auth_middleware import (
    UserInfo as LegacyUserInfo,
)
from brain_researcher.legacy.api_gateway.auth_middleware import (
    get_current_user as legacy_get_current_user,
)
from brain_researcher.services.shared.auth_middleware import (
    UserInfo as SharedUserInfo,
)
from brain_researcher.services.shared.auth_middleware import (
    get_current_user as shared_get_current_user,
)
from brain_researcher.services.telemetry import api as telemetry_api


def test_legacy_auth_middleware_shim_reexports_shared_symbols() -> None:
    assert LegacyUserInfo is SharedUserInfo
    assert legacy_get_current_user is shared_get_current_user


def test_telemetry_imports_shared_auth_symbols() -> None:
    assert telemetry_api.UserInfo is SharedUserInfo
    assert telemetry_api.get_current_user is shared_get_current_user
