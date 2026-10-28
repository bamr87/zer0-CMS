"""The GA4, Search Console and DataForSEO connectors: configured per site, their credential encrypted and
write-only, synced in a worker against each vendor's REST API (recorded HTTP: respx) — a Google service account's
key signs a JWT that Google's token endpoint trades for an access token — and their rows kept for priorities: AIEO's
opportunity rule over Search Console's queries, with the trend since the last sync and the site's keywords as the
business priority."""

import io
import json
from urllib.parse import parse_qs

import jwt
import pytest
import respx
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.test import override_settings

from aieo import connectors, services, tasks
from aieo.models import BrandContext, Connector, ConnectorData

from .conftest import answer

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
SERVICE_ACCOUNT = json.dumps({"client_email": "aieo@project.iam.gserviceaccount.com", "private_key": PEM.decode()})


@pytest.fixture
def google():
    with respx.mock(assert_all_called=False) as router:
        router.post(connectors.TOKEN_URI).respond(200, json={"access_token": "ya29.token", "expires_in": 3600})
        yield router


@pytest.fixture
def configurer(alice):
    alice.user_permissions.add(Permission.objects.get(codename="change_connector"))
    return type(alice).objects.get(pk=alice.pk)  # the permission cache read again


def connect(site, kind, options, credential=SERVICE_ACCOUNT):
    row = Connector(site=site, kind=kind, options=options)
    row.set_credential(credential)
    row.save()
    return row


def test_ga4_signs_a_jwt_for_its_token_and_reads_the_top_pages(site, google, worker):
    report = google.post(connectors.GA4.format(property="123456")).respond(
        200,
        json={
            "rows": [
                {
                    "dimensionValues": [{"value": "/backups/"}],
                    "metricValues": [{"value": "420"}, {"value": "0.61"}, {"value": "700"}],
                },
                {
                    "dimensionValues": [{"value": "/"}],
                    "metricValues": [{"value": "90"}, {"value": "0.4"}, {"value": "120"}],
                },
            ]
        },
    )
    row = connect(site, Connector.GA4, {"property_id": "properties/123456"})
    assert tasks.sync_connector(row.pk) == Connector.OK
    grant = parse_qs(google.calls[0].request.content.decode())
    claims = jwt.decode(grant["assertion"][0], KEY.public_key(), algorithms=["RS256"], audience=connectors.TOKEN_URI)
    assert claims["iss"] == "aieo@project.iam.gserviceaccount.com" and claims["scope"].endswith("analytics.readonly")
    assert report.calls.last.request.headers["authorization"] == "Bearer ya29.token"
    body = json.loads(report.calls.last.request.content)
    assert body["dimensions"] == [{"name": "pagePath"}] and body["metrics"][0] == {"name": "sessions"}
    data = ConnectorData.objects.get(connector=row)
    assert data.report == "top_pages" and data.rows[0] == {
        "page": "/backups/",
        "sessions": 420,
        "engagement_rate": 0.61,
        "views": 700,
    }


def test_a_keys_own_token_uri_is_never_where_the_grant_goes(site, google):
    """The service-account key is what a person pasted, so its `token_uri` is theirs to choose: the grant always goes
    to Google's own endpoint, and an address inside the network is never asked (nor its answer shown back)."""
    key = json.dumps({**json.loads(SERVICE_ACCOUNT), "token_uri": "http://10.0.0.5:9200/_steal"})
    row = connect(site, Connector.GA4, {"property_id": "1"}, credential=key)
    inside = google.post("http://10.0.0.5:9200/_steal").respond(500, json={"error": "internal answer leaked"})
    google.post(connectors.GA4.format(property="1")).respond(200, json={"rows": []})
    assert tasks.sync_connector(row.pk) == Connector.OK
    assert google.calls[0].request.url == connectors.TOKEN_URI and not inside.called
    row.refresh_from_db()
    assert row.error == ""


def test_search_console_rows_rank_the_update_queue_by_aieos_opportunity_rule(alice, site, google):
    BrandContext.objects.update_or_create(
        site=site, defaults={"competitors": {"keywords": ["backup"], "competitors": [], "topics": []}}
    )
    query = google.post(connectors.GSC.format(site="sc-domain%3Abackups.example.com"))
    rows = [
        {
            "keys": ["nightly backup", "https://backups.example.com/b"],
            "clicks": 30,
            "impressions": 4000,
            "ctr": 0.0075,
            "position": 8.2,
        },
        {
            "keys": ["restore", "https://backups.example.com/r"],
            "clicks": 2,
            "impressions": 100,
            "ctr": 0.02,
            "position": 41,
        },
    ]
    query.respond(200, json={"rows": rows})
    row = connect(site, Connector.GSC, {"site_url": "sc-domain:backups.example.com"})
    assert tasks.sync_connector(row.pk) == Connector.OK
    rows[0]["impressions"] = 6000
    query.respond(200, json={"rows": rows})
    assert tasks.sync_connector(row.pk) == Connector.OK
    ranked = services.priorities(alice, site)
    first = ranked["queue"][0]
    assert first["query"] == "nightly backup" and first["components"]["business_priority"] == 100
    assert first["components"]["trend"] == 100  # impressions up 50% since the sync before
    assert (
        ranked["queue"][1]["components"]["trend"] == 50 and ranked["queue"][1]["components"]["business_priority"] == 50
    )
    assert ranked["quick_wins"] == [q for q in ranked["queue"] if q["opportunity_score"] >= 60][:10]


def test_dataforseo_reads_the_organic_results_with_basic_auth(site):
    with respx.mock() as router:
        serp = router.post(connectors.DATAFORSEO).respond(
            200,
            json={
                "tasks": [
                    {
                        "status_code": 20000,
                        "result": [
                            {
                                "keyword": "nightly backup",
                                "items": [
                                    {
                                        "type": "organic",
                                        "rank_absolute": 1,
                                        "url": "https://a.example/",
                                        "domain": "a.example",
                                        "title": "A",
                                    },
                                    {"type": "paid", "rank_absolute": 2, "url": "https://ad.example/"},
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        row = connect(site, Connector.DATAFORSEO, {"keywords": ["nightly backup"]}, credential="me@example.com:secret")
        assert tasks.sync_connector(row.pk) == Connector.OK
    assert serp.calls.last.request.headers["authorization"].startswith("Basic ")
    assert json.loads(serp.calls.last.request.content)[0]["keyword"] == "nightly backup"
    assert ConnectorData.objects.get(connector=row).rows == [
        {"keyword": "nightly backup", "rank": 1, "url": "https://a.example/", "domain": "a.example", "title": "A"}
    ]


def test_a_refusal_or_a_bad_key_is_said_on_the_connector(site, google):
    google.post(connectors.GA4.format(property="1")).respond(
        403, json={"error": {"message": "no access to property 1"}}
    )
    row = connect(site, Connector.GA4, {"property_id": "1"})
    assert tasks.sync_connector(row.pk) == Connector.FAILED
    row.refresh_from_db()
    assert row.error == "GA4 answered HTTP 403: no access to property 1"
    bad = connect(site, Connector.GSC, {"site_url": "https://backups.example.com/"}, credential="not json")
    assert tasks.sync_connector(bad.pk) == Connector.FAILED
    bad.refresh_from_db()
    assert "service account" in bad.error


def test_connectors_are_configured_over_the_api_with_a_write_only_encrypted_credential(
    configurer, bob, staff, api, site, google, django_capture_on_commit_callbacks
):
    body = {
        "site": site.pk,
        "kind": "ga4",
        "enabled": True,
        "options": {"property_id": "123"},
        "credential": SERVICE_ACCOUNT,
    }
    assert api(bob).post("/api/v2/aieo/connectors/", body, format="json").status_code == 403
    made = api(configurer).post("/api/v2/aieo/connectors/", body, format="json")
    assert made.status_code == 201, made.content
    data = made.json()
    assert "credential" not in data and data["has_credential"] and data["can_edit"]
    row = Connector.objects.get(public_id=data["id"])
    assert row.credential_encrypted and SERVICE_ACCOUNT not in row.credential_encrypted
    assert row.get_credential() == SERVICE_ACCOUNT
    assert api(bob).get("/api/v2/aieo/connectors/").json() == []  # not a site bob edits
    google.post(connectors.GA4.format(property="123")).respond(200, json={"rows": []})
    with django_capture_on_commit_callbacks(execute=True):
        synced = api(configurer).post(f"/api/v2/aieo/connectors/{data['id']}/sync/")
    assert synced.status_code == 202 and synced.json()["status"] == "syncing"
    row.refresh_from_db()
    assert row.status == Connector.OK and row.last_synced_at
    assert api(configurer).get(f"/api/v2/aieo/connectors/{data['id']}/data/").json()["rows"] == []
    off = api(configurer).patch(f"/api/v2/aieo/connectors/{data['id']}/", {"enabled": False}, format="json")
    assert (
        off.status_code == 200
        and api(configurer).post(f"/api/v2/aieo/connectors/{data['id']}/sync/").status_code == 409
    )
    priorities = api(configurer).get("/api/v2/aieo/priorities/", {"site": site.pk})
    assert priorities.status_code == 200 and priorities.json()["queue"] == []
    assert api(bob).get("/api/v2/aieo/priorities/", {"site": site.pk}).status_code == 404


def test_rotating_the_ai_keys_carries_every_connectors_credential(site):
    """A connector's credential is under the AI layer's keys: `rotate_ai_credentials`, the one command that rotates
    them, moves it too (`ai.crypto.credentials_rotated`, as distribution's channels and the automations' secrets do),
    and one no key can read stops the rotation, named — never a connector that fails to sync once the old key goes."""
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    with override_settings(AI_CREDENTIAL_KEYS=[old]):
        row = connect(site, Connector.DATAFORSEO, {"keywords": ["backup"]}, credential="login:password")
    out = io.StringIO()
    with override_settings(AI_CREDENTIAL_KEYS=[new, old]):
        call_command("rotate_ai_credentials", stdout=out)
    assert "1 credential(s) re-encrypted" in out.getvalue()
    with override_settings(AI_CREDENTIAL_KEYS=[new], SECRET_KEY="another-secret"):
        assert Connector.objects.get(pk=row.pk).get_credential() == "login:password"
    with override_settings(AI_CREDENTIAL_KEYS=[old], SECRET_KEY="another-secret"):
        with pytest.raises(CommandError, match="DataForSEO"):
            call_command("rotate_ai_credentials", stdout=io.StringIO())


def test_removing_a_connector_takes_the_right_to_delete_one(configurer, site, api):
    row = connect(site, Connector.DATAFORSEO, {"keywords": ["backup"]}, credential="login:password")
    url = f"/api/v2/aieo/connectors/{row.public_id}/"
    assert api(configurer).delete(url).status_code == 403 and Connector.objects.filter(pk=row.pk).exists()
    configurer.user_permissions.add(Permission.objects.get(codename="delete_connector"))
    remover = type(configurer).objects.get(pk=configurer.pk)
    assert api(remover).delete(url).status_code == 204 and not Connector.objects.filter(pk=row.pk).exists()


def test_a_failed_sync_is_logged_without_the_frames_that_hold_its_credential(site, caplog, monkeypatch):
    """A traceback carries its frames' variables — a service account's whole key, its private key, the signed grant —
    which Sentry sends unless a name is on its list; an unexpected failure is logged by its type alone."""

    def broken(connector):
        key = connector.get_credential()  # what the vendor client's frames hold when it fails  # noqa: F841
        raise KeyError("access_token")

    monkeypatch.setattr(connectors, "fetch_rows", broken)
    row = connect(site, Connector.GA4, {"property_id": "1"})
    with caplog.at_level("ERROR", logger="aieo.tasks"):
        assert tasks.sync_connector(row.pk) == Connector.FAILED
    assert caplog.records and all(r.exc_info is None for r in caplog.records)
    row.refresh_from_db()
    assert row.error == "the sync failed: KeyError"


def test_the_performance_analyst_reads_the_sites_last_synced_rows(alice, fake, worker, site):
    """AIEO's performance agent reads analytics (`ga_data`, `gsc_data`, `dataforseo_data`): the site's last synced
    rows of each connector, where the person gave none of their own."""
    gsc = Connector.objects.create(site=site, kind=Connector.GSC, options={"site_url": "sc-domain:x"})
    ga4 = Connector.objects.create(site=site, kind=Connector.GA4, options={"property_id": "1"})
    ConnectorData.objects.create(connector=gsc, report="queries", rows=[{"query": "old query", "impressions": 1}])
    ConnectorData.objects.create(connector=gsc, report="queries", rows=[{"query": "nightly backup", "impressions": 9}])
    ConnectorData.objects.create(connector=ga4, report="top_pages", rows=[{"page": "/backups/", "sessions": 420}])
    fake.script = [answer({"quick_wins": ["Refresh the guide"], "declining_content": [], "roadmap": []})]
    worker(services.run_agent, alice, "aieo-performance", site=site, inputs={"dataforseo_data": "given by hand"})
    sent = fake.calls[0]["messages"][0]["content"]
    assert "## Gsc data" in sent and "nightly backup" in sent and "old query" not in sent  # the last sync's rows
    assert "## Ga data" in sent and "/backups/" in sent and "## Dataforseo data\n\ngiven by hand" in sent
