# Salesforce Security Assessment: 101

A pre-engagement reference for penetration testers. Covers architecture, access control layers, attack surfaces, and common misconfigurations across both Experience Cloud and Lightning Experience.

## 1. Architecture

Salesforce is a multi-tenant SaaS CRM. Every customer organisation (org) lives in a shared Salesforce data center but is logically isolated. Three network-facing environments exist per org:

| Environment | Domain pattern | Audience |
|---|---|---|
| Back-office / CRM | `*.my.salesforce.com` | Employees, admins (Lightning Experience) |
| Setup | `*.my.salesforce-setup.com` | Admins (Lightning Setup) |
| Front-office / portal | `*.my.site.com` | Customers, partners, public (Experience Cloud) |

All three environments share the **same database and security model**. A misconfigured object in the back-office is reachable from the front-office, including without authentication.

**Experience Cloud** (formerly Community Cloud) powers the front-office portal. It supports two rendering stacks:

- **Aura** (legacy, still dominant): server-side component framework, communicates via `/s/sfsites/aura`
- **LWR (Lightning Web Runtime)** (modern): React-like framework, serves components via `/webruntime/` CDN paths, still calls the same Aura endpoint for data

**Lightning Experience** is the internal CRM UI served at `/aura` on `my.salesforce.com` and `my.salesforce-setup.com`. It uses the `one:one` Aura app and exposes a different set of framework controllers (`aura://`) compared to Experience Cloud.

## 2. Access Control Model

Salesforce enforces access through three independent, cumulative layers. All three must be correctly configured; a gap in any one layer is exploitable.

### 2.1 Object-Level Security (OLS / CRUD)

Defined per profile. Controls whether a user can **Read / Create / Edit / Delete** records of a given object type (e.g. `Contact`, `Case`, `InterventionRequest__c`).

Checked via: Salesforce Setup > Profiles > Object Settings, or the `EntityDefinition` GraphQL object (queryable without introspection).

### 2.2 Field-Level Security (FLS)

Defined per profile per field. A user with OLS read on `Contact` may still be blocked from seeing `Email` or `Phone`.

Aura's `getRecord` / `getItems` respects FLS, but fields not explicitly hidden are returned by default.

### 2.3 Record-Level Security (RLS / Sharing)

Controls which **rows** of an accessible object a user can see. Configured through:

- **Org-Wide Defaults (OWD)**: baseline sharing for each object. `Public Read/Write`, `Public Read Only`, or `Private`. The `ExternalSharingModel` controls the guest-facing OWD specifically.
- **Sharing rules**: automated grants to groups or roles
- **Role hierarchy**: managers inherit access to subordinates' records
- **Manual sharing**: record-by-record grants

If OWD for an object is `Public Read/Write` for external users (`ExternalSharingModel = ReadWrite`), every authenticated or even guest user sees every record of that object.

**Key query to enumerate sharing models without introspection:**

```
GET /services/data/v59.0/graphql
{
  uiapi {
    query {
      EntityDefinition(where: {IsQueryable: {eq: true}}) {
        edges { node {
          QualifiedApiName
          ExternalSharingModel
          IsEverCreatable IsEverUpdatable IsEverDeletable
        }}
      }
    }
  }
}
```

## 3. The Guest User Profile

Every Experience Cloud site is associated with a **Guest User profile**. This profile represents any unauthenticated visitor. It has its own OLS, FLS, and sharing settings. There is no equivalent guest surface on Lightning Experience.

### 3.1 Critical profile settings

| Setting | Location | Impact if enabled |
|---|---|---|
| **API Enabled** | Profile > System Permissions | Allows programmatic calls to `/s/sfsites/aura` without a session. Primary vector for unauthenticated enumeration. Salesforce recommends unchecking this. |
| **Access Activities** | Profile > System Permissions | Exposes activity/event records to guest. Salesforce recommends unchecking this. |
| **OptionsGuestFileAccessEnabled** | Network object | Allows guests to access files linked to records they can read (ContentVersion, ContentDocument). |
| Object read permissions | Profile > Object Settings | Each object granted read access is queryable via `getItems` without credentials. |

To enumerate guest-accessible objects: call `getItems` on each object via the Aura endpoint with no cookie. Objects that return `SUCCESS` are readable by anyone on the internet.

### 3.2 High-risk objects when guest-accessible

Salesforce Security actively monitors guest access to the following standard objects and notifies org owners when unusual activity is detected:

| Object | Why it matters |
|---|---|
| `ContentVersion` / `ContentDocument` | File content, potentially sensitive documents |
| `ContentVersionHistory` | Audit trail of file edits, reveals internal activity |
| `Profile` | Exposes permission sets and org configuration |
| `RecordType` | Maps object layout and business process structure |
| `StaticResource` | JavaScript bundles that may contain hardcoded endpoints, tokens, or API keys |
| `ProcessInstanceWorkitem` | Approval workflow state; reveals pending decisions and assignees |
| `TopicAssignment` | Content tagging; discloses internal taxonomy and linked records |

Accessing `Profile` or `StaticResource` without authentication is particularly impactful: `Profile` discloses org permission architecture and `StaticResource` frequently leaks internal endpoint paths and configuration embedded in front-end bundles.

### 3.3 Salesforce detection and notification

Salesforce Security monitors for unusual guest user activity across orgs. When a guest session queries sensitive standard objects in bulk, a notification is sent to the org's security contact referencing the guest user ID, source IP, timestamp, and list of accessed objects. Assessments against production orgs will be detected and escalated to the customer. Coordinate timing with the client accordingly.

Official guidance:
- [Securely Share Your Experience Cloud Sites with Guest Users](https://help.salesforce.com/s/articleView?id=sf.networks_guest_user_security.htm)
- [Guest User Record Access Development Best Practices](https://help.salesforce.com/s/articleView?id=sf.networks_guest_user_record_access.htm)
- [Guest User Data Exposure advisory](https://help.salesforce.com/s/articleView?id=000390737&type=1)

## 4. The Experience Cloud Aura Endpoint

`POST /s/sfsites/aura`

This is the primary RPC channel for Experience Cloud portals. Not documented publicly. All actions are sent in a `message` POST parameter as JSON.

Key action descriptors:

| Descriptor | What it does |
|---|---|
| `serviceComponent://ui.force.components.controllers.lists.selectableListDataProvider.SelectableListDataProviderController/ACTION$getItems` | Dump records of an object (equivalent to a SOQL SELECT) |
| `serviceComponent://ui.force.components.controllers.detail.DetailController/ACTION$getRecord` | Fetch a single record by ID |
| `serviceComponent://ui.force.components.controllers.recordGvp.RecordGvpController/ACTION$getObjectInfo` | Fetch field metadata for an object |
| `apex://<ControllerName>/ACTION$<methodName>` | Call an `@AuraEnabled` Apex method |
| `aura://ComponentController/ACTION$getComponent` | Fetch a Lightning component definition |

Every request carries three parameters:
- `message`: JSON body with the action descriptor and params
- `aura.context`: JSON with `fwuid` (framework version), `app`, and loaded component hashes
- `aura.token`: CSRF token tied to the session (use `"undefined"` for unauthenticated calls)

The access level applied is that of the current session's profile. Guest User if no cookie, authenticated profile otherwise.

## 5. The Lightning Experience Aura Endpoint

`POST /aura` on `*.my.salesforce.com` or `*.my.salesforce-setup.com`

The internal equivalent of the Experience Cloud Aura endpoint. Uses the `one:one` app context instead of `siteforce:communityApp`. Always requires an authenticated session (`sid` cookie from a full Salesforce license user). No guest surface exists.

Key action descriptors specific to Lightning:

| Descriptor | What it does |
|---|---|
| `aura://RecordUiController/ACTION$getObjectInfo` | Fetch object metadata and field definitions |
| `aura://RecordUiController/ACTION$getRecord` | Fetch a record by ID with field-level data |
| `aura://RecordUiController/ACTION$getListUi` | Fetch list view records |
| `aura://RecordUiController/ACTION$createRecord` | Create a record |
| `aura://RecordUiController/ACTION$deleteRecord` | Delete a record |
| `aura://SetupMetadataController/ACTION$isAccessCheckEnabled` | Query Setup configuration flags |
| `aura://ApexActionController/ACTION$execute` | Invoke Apex via the generic Lightning Apex bridge |
| `apex://<ControllerName>/ACTION$<methodName>` | Call a custom `@AuraEnabled` Apex method |

Security relevance: `aura://RecordUiController` exposes full CRUD on any object the session's profile can access. If a low-privilege internal user's profile has broad OLS permissions, these controllers expose all readable records without further access checks. `ApexActionController` can invoke custom Apex that bypasses standard sharing rules when written with `without sharing`.

The `aura.context` for Lightning uses `app: "one:one"` and a different `fwuid` than Experience Cloud. The framework version must match the live org; a mismatch returns a version error that leaks the real `fwuid`.

## 6. REST API Surfaces

In addition to Aura, the following REST endpoints are active on Salesforce deployments:

| Endpoint | Auth required | Notes |
|---|---|---|
| `/services/data/v{version}/graphql` | Optional (guest if API Enabled) | GraphQL uiapi; queryable via `EntityDefinition` even with introspection disabled |
| `/services/apexrest/<path>` | Optional | Custom REST endpoints exposed via `@RestResource` Apex classes |
| `/chatter/` | Optional | Chatter REST API; file upload, feeds, groups |
| `/services/data/v{version}/query?q=<SOQL>` | Bearer token | Standard SOQL query API; requires internal OAuth session |
| `/services/data/v{version}/tooling/` | Bearer token | Apex source code, metadata; requires internal session |
| `/sfc/servlet.shepherd/version/download/<ContentVersionId>` | Session cookie (or none if misconfigured) | Direct file download by ID; IDOR vector |
| `/servlet/servlet.FileDownload?file=<Id>` | Session cookie (or none if misconfigured) | Legacy file download |

### GraphQL uiapi without introspection

Standard GraphQL introspection (`__schema`) is disabled on Salesforce. The full org schema is still accessible via the `EntityDefinition` object, which returns every queryable object's API name, sharing model, and CRUD flags. This is not a vulnerability; it is a documented API. But it allows a tester to map the entire data model without any admin access.

Salesforce docs: [GraphQL API Developer Guide](https://developer.salesforce.com/docs/platform/graphql/guide/graphql-about.html)

## 7. Content and File Access

Salesforce stores all user-uploaded files as `ContentDocument` / `ContentVersion` records. These are linked to other records via `ContentDocumentLink`.

Download paths:
- `ContentVersion`: `/sfc/servlet.shepherd/version/download/<ContentVersionId>` (prefix `068`)
- `ContentDocument`: `/sfc/servlet.shepherd/document/download/<ContentDocumentId>` (prefix `069`)

If the Guest User profile has `OptionsGuestFileAccessEnabled` set or if `ContentVersion` is readable by guest, these endpoints return file content without authentication when called with a valid ID. IDs are discoverable from any guest-accessible object that stores a file reference.

**ContentDistribution** records expose a public URL for a file that bypasses all session checks; useful for finding files intentionally made public and verifying whether the scope is broader than intended.

## 8. ID Format and Enumeration

Salesforce record IDs are 15 or 18 characters, base-62. The first 3 characters are the **key prefix**, which identifies the object type:

| Prefix | Object |
|---|---|
| `001` | Account |
| `003` | Contact |
| `005` | User |
| `006` | Opportunity |
| `069` | ContentDocument |
| `068` | ContentVersion |
| `500` | Case |
| `0F9` | ContentDistribution |
| `a0X`, `a0N`, etc. | Custom objects (variable) |

IDs are not sequential but are **not cryptographically random**. They are base-62 encoded identifiers with a checksum. Enumeration is feasible when IDs are disclosed in API responses and the access control on `getRecord` is missing an authorisation check (IDOR).

## 9. Common Misconfiguration Patterns

| Finding | Root cause | Salesforce control |
|---|---|---|
| Guest reads sensitive objects | OLS read granted to Guest User profile | Profile > Object Settings |
| Guest downloads files | `OptionsGuestFileAccessEnabled` or ContentVersion OLS | Network object / Profile |
| All authenticated users see all records (no RLS) | OWD set to `Public Read/Write` or `Public Read Only` for external sharing | Setup > Sharing Settings > Org-Wide Defaults |
| IDOR on file download | ContentVersion/ContentDocument readable by guest, IDs disclosed in public responses | Profile + OWD |
| API Enabled on Guest profile | System permission left on | Profile > System Permissions > API Enabled |
| Apex method callable without auth | `@AuraEnabled` method on a class accessible via Guest profile | Review Apex class sharing and profile permissions |
| GraphQL schema fully exposed | EntityDefinition queryable by guest | Not a misconfiguration; by design. Restrict object permissions instead. |
| Broad Lightning CRUD via RecordUiController | Internal profile has OLS read/write on too many objects | Profile > Object Settings |
| Apex bridge exposes privileged logic | `ApexActionController` invokes `without sharing` class | Review Apex class sharing model |
| Named Credentials or External Services exposed | Tooling API readable by low-privilege user | Profile > API Enabled + restrict Tooling access |

## 10. Assessment Checklist

### Experience Cloud

Before starting:
- [ ] Identify the site URL pattern (`*.my.site.com` vs legacy `*.force.com`)
- [ ] Determine if the site uses Aura, LWR, or both (check response headers and JS bundle paths)
- [ ] Obtain a guest session (no cookie) and an authenticated session (community user cookie)
- [ ] Note the Aura `fwuid` from a bootstrap call; required for valid `aura.context`
- [ ] Check `robots.txt` and `crossdomain.xml` for disclosed endpoints

Key phases:
1. **Surface exposure**: guest vs authenticated object count, `ExternalSharingModel` per object
2. **Aura object dump**: enumerate and dump all objects readable via `getItems`
3. **CRUD probe**: attempt `createRecord` / `deleteRecord` on accessible objects
4. **IDOR probe**: test IDs found in authenticated dumps against the guest session
5. **GraphQL sweep**: use `EntityDefinition` to map the full schema, then query each object
6. **ApexREST fuzz**: wordlist-fuzz `/services/apexrest/` for exposed custom REST endpoints
7. **Static resources**: enumerate `/resource/` paths for leaked JS/config bundles
8. **Chatter**: probe file upload endpoint for information disclosure
9. **Content distribution**: check for publicly accessible file distribution records

### Lightning Experience

Before starting:
- [ ] Obtain an authenticated session (`sid` cookie from a full Salesforce license user)
- [ ] Capture `aura.context` from a POST to `/aura` (save as `lightning_ctx.json`)
- [ ] Capture `aura.token` from the same POST (save as `token.txt`)
- [ ] Obtain a Bearer token from `/services/data/` requests for REST surface coverage

Key phases:
1. **Controller probe**: fuzz `aura://` framework controllers for callable or access-denied responses
2. **Object enumeration**: call `getConfigData` in Lightning context to list accessible objects
3. **RecordUi CRUD**: test `createRecord` / `deleteRecord` via `aura://RecordUiController` across accessible objects
4. **REST surface**: run SOQL and Tooling API queries to enumerate metadata, Apex source, Named Credentials, and Connected Apps
5. **ApexREST fuzz**: wordlist-fuzz `/services/apexrest/` for custom API endpoints

## 11. Reference Links

| Resource | URL |
|---|---|
| Salesforce Security Implementation Guide | https://developer.salesforce.com/docs/atlas.en-us.securityImplGuide.meta/securityImplGuide/ |
| Experience Cloud Security | https://help.salesforce.com/s/articleView?id=sf.networks_security.htm |
| Securely Share Sites with Guest Users | https://help.salesforce.com/s/articleView?id=sf.networks_guest_user_security.htm |
| Guest User Record Access Best Practices | https://help.salesforce.com/s/articleView?id=sf.networks_guest_user_record_access.htm |
| UAR: Guest and Auth User Access Report | https://help.salesforce.com/s/articleView?id=sf.networks_uar_report.htm |
| Sharing Architecture (OWD, roles, rules) | https://trailhead.salesforce.com/content/learn/modules/data_security |
| GraphQL API Guide | https://developer.salesforce.com/docs/platform/graphql/guide/ |
| Aura Framework Docs | https://developer.salesforce.com/docs/atlas.en-us.lightning.meta/lightning/ |
| Lightning RecordUi API | https://developer.salesforce.com/docs/atlas.en-us.uiapi.meta/uiapi/ |
| ContentDocument Object Reference | https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_contentdocument.htm |
| Salesforce Trust (incident history) | https://status.salesforce.com |
| HackerOne Salesforce Program | https://hackerone.com/salesforce |
