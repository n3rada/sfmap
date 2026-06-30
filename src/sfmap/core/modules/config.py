# Built-in imports
from urllib.parse import quote_plus, urlparse

# Third-party imports
from loguru import logger

# Local imports
from ..client import AuraClient, REST_API_VERSION
from ..utils.storage import OutputWriter

_CONFIG_QUERIES: list[tuple[str, str]] = [
    (
        "ConnectedApplication",
        "SELECT Id, Name, CallbackUrl, Scopes, OptionsAllowAdminApprovedUsersOnly, OptionsFullContentPush FROM ConnectedApplication",
    ),
    (
        "NamedCredential",
        "SELECT Id, DeveloperName, Endpoint, PrincipalType, Protocol, AllowMergeFieldsInBody, AllowMergeFieldsInHeader FROM NamedCredential",
    ),
    (
        "RemoteSiteSetting",
        "SELECT Id, Name, Url, IsActive, DisableProtocolSecurity FROM RemoteSiteSetting WHERE IsActive = true",
    ),
    (
        "AuthProvider",
        "SELECT Id, DeveloperName, FriendlyName, ProviderType, AuthorizeUrl, TokenUrl, UserInfoUrl, IsApexDefined FROM AuthProvider",
    ),
    (
        "Certificate",
        "SELECT Id, DeveloperName, ExpirationDate, KeySize, MasterLabel FROM Certificate",
    ),
    (
        "OrgWideEmailAddress",
        "SELECT Id, Address, DisplayName, IsAllowAllProfiles FROM OrgWideEmailAddress",
    ),
    (
        "LoginIpRange",
        "SELECT Id, ProfileId, StartAddress, EndAddress FROM LoginIpRange",
    ),
    (
        "FlowDefinitionView",
        "SELECT Id, ApiName, Label, ProcessType, TriggerType, IsActive, RunInMode FROM FlowDefinitionView WHERE IsActive = true",
    ),
    (
        "Profile",
        (
            "SELECT Id, Name, "
            "PermissionsModifyAllData, PermissionsViewAllData, PermissionsManageUsers, "
            "PermissionsApiEnabled, PermissionsAuthorizeNetworkConnections, "
            "PermissionsManageConnectedApps, PermissionsCustomizeApplication, "
            "PermissionsViewSetup, PermissionsManageAuthProviders, PermissionsRunFlow "
            "FROM Profile ORDER BY Name"
        ),
    ),
    (
        "PermissionSet",
        (
            "SELECT Id, Name, IsCustom, Label, "
            "PermissionsModifyAllData, PermissionsViewAllData, PermissionsManageUsers, "
            "PermissionsApiEnabled, PermissionsAuthorizeNetworkConnections, "
            "PermissionsManageConnectedApps, PermissionsCustomizeApplication, "
            "PermissionsRunFlow "
            "FROM PermissionSet WHERE IsCustom = true ORDER BY Name"
        ),
    ),
]

_TOOLING_QUERIES: list[tuple[str, str]] = [
    (
        "SecurityHealthCheck",
        "SELECT Score, RiskType, ScoreGroup FROM SecurityHealthCheck",
    ),
    (
        "SessionSettings",
        (
            "SELECT SessionTimeout, ForceLogout, EnablePostMessageWindowConfirm, "
            "EnableClickjackNonsetupSFDC, EnableClickjackNonsetupUser, "
            "EnableClickjackSetup, EnableSMSResetPassword "
            "FROM SessionSettings LIMIT 1"
        ),
    ),
    (
        "ApexClass_WithoutSharing",
        "SELECT Id, Name, ApiVersion FROM ApexClass WHERE Body LIKE '%without sharing%'",
    ),
]

_RISKY_CONN_APP_SCOPES = {"full", "api", "web", "refresh_token"}
_RISKY_PERM_FLAGS = (
    "PermissionsModifyAllData",
    "PermissionsViewAllData",
    "PermissionsManageUsers",
    "PermissionsManageConnectedApps",
    "PermissionsManageAuthProviders",
    "PermissionsCustomizeApplication",
)


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _soql_all(client: AuraClient, endpoint: str, soql: str) -> list[dict]:
    records: list[dict] = []
    url = f"{endpoint}?q={quote_plus(soql)}"
    while url:
        try:
            resp = client.rest_get(url)
        except Exception:
            logger.exception("SOQL query error")
            break
        if resp.status_code != 200:
            logger.debug(f"SOQL HTTP {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        records.extend(data.get("records", []))
        next_url = data.get("nextRecordsUrl")
        url = f"{_base_url(endpoint)}{next_url}" if next_url else None
    return records


def _flag_risky(obj_name: str, records: list[dict]) -> None:
    if obj_name == "ConnectedApplication":
        for r in records:
            scopes = set((r.get("Scopes") or "").lower().split())
            risky = scopes & _RISKY_CONN_APP_SCOPES
            if risky:
                logger.warning(f"ConnectedApp {r.get('Name')!r}: broad scopes {sorted(risky)}")
        return

    if obj_name == "RemoteSiteSetting":
        for r in records:
            if r.get("DisableProtocolSecurity"):
                logger.warning(f"RemoteSiteSetting {r.get('Name')!r}: protocol security disabled (HTTP callouts allowed)")
            if (r.get("Url") or "").startswith("http://"):
                logger.warning(f"RemoteSiteSetting {r.get('Name')!r}: plaintext HTTP endpoint {r.get('Url')!r}")
        return

    if obj_name in ("Profile", "PermissionSet"):
        for r in records:
            active_flags = [f for f in _RISKY_PERM_FLAGS if r.get(f)]
            if active_flags:
                logger.warning(
                    f"{obj_name} {r.get('Name')!r}: risky permissions: {', '.join(active_flags)}"
                )
        return

    if obj_name == "FlowDefinitionView":
        for r in records:
            mode = r.get("RunInMode", "")
            if "without" in (mode or "").lower() or mode == "SystemModeWithoutSharing":
                logger.warning(f"Flow {r.get('ApiName')!r}: runs without sharing ({mode})")
        return


def run(client: AuraClient, aura_url: str, out: OutputWriter) -> dict[str, int]:
    """
    Query Salesforce for setup/configuration objects via SOQL and Tooling API.
    Flags high-risk findings. Requires Bearer token for most queries.
    Returns {object_name: record_count} for every successful query.
    """
    base = _base_url(aura_url)
    soql_endpoint = f"{base}/services/data/{REST_API_VERSION}/query"
    tooling_endpoint = f"{base}/services/data/{REST_API_VERSION}/tooling/query"
    config_out = out.subdir("config")

    probe = f"{soql_endpoint}?q={quote_plus('SELECT Id FROM ConnectedApplication LIMIT 1')}"
    try:
        resp = client.rest_get(probe)
    except Exception:
        logger.exception("Config probe failed")
        return {}

    if resp.status_code not in (200, 201):
        hint = " (pass --bearer for OAuth access)" if not client.has_bearer else ""
        logger.info(f"Config SOQL not accessible (HTTP {resp.status_code}){hint}")
        return {}

    logger.info("Config SOQL accessible, querying setup objects")
    results: dict[str, int] = {}

    for obj_name, soql in _CONFIG_QUERIES:
        records = _soql_all(client, soql_endpoint, soql)
        if records is None:
            continue
        results[obj_name] = len(records)
        if records:
            _flag_risky(obj_name, records)
            path = config_out.save(f"config_{obj_name}.json", records)
            logger.success(f"Config {obj_name}: {len(records)} record(s) saved to {path}")
        else:
            logger.debug(f"Config {obj_name}: 0 records")

    tooling_probe = f"{tooling_endpoint}?q={quote_plus('SELECT Score FROM SecurityHealthCheck LIMIT 1')}"
    try:
        tresp = client.rest_get(tooling_probe)
        tooling_ok = tresp.status_code in (200, 201)
    except Exception:
        tooling_ok = False

    if tooling_ok:
        logger.info("Tooling API accessible, querying session and health settings")
        for obj_name, soql in _TOOLING_QUERIES:
            records = _soql_all(client, tooling_endpoint, soql)
            if not records:
                logger.debug(f"Tooling config {obj_name}: 0 records")
                continue
            results[obj_name] = len(records)
            path = config_out.save(f"config_{obj_name}.json", records)
            if obj_name == "SecurityHealthCheck":
                scores = [r.get("Score") for r in records if r.get("Score") is not None]
                if scores:
                    low = min(scores)
                    if low < 80:
                        logger.warning(f"SecurityHealthCheck: lowest score {low} (below 80)")
                    else:
                        logger.info(f"SecurityHealthCheck: lowest score {low}")
            elif obj_name == "ApexClass_WithoutSharing":
                logger.warning(f"ApexClass_WithoutSharing: {len(records)} class(es) with 'without sharing' keyword")
            logger.success(f"Tooling config {obj_name}: {len(records)} record(s) saved to {path}")
    else:
        logger.info("Tooling API not accessible for config queries (bearer may lack Tooling permission)")

    config_out.save("config_summary.json", {k: v for k, v in results.items() if v > 0})

    if results:
        logger.success(
            f"Config review: {len([v for v in results.values() if v > 0])} object type(s) with data, see {config_out}/"
        )
    else:
        logger.info("Config review: no records returned (check bearer token permissions)")

    return results
