"""Fixtures for the content switches' tests: a small hub switch map, two outlets, a manager and GitHub recorded with
respx — an unscripted request fails the test, and nothing reaches GitHub."""

import pytest
import respx
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from switches.models import SwitchConfig

API = "https://api.github.com"
HUB = "/repos/bamr87/bamr87/contents/_data/fleet.yml"
TOKEN = "zer0-test-credential-not-a-token"

MAP = """\
toolchain: {}
switches:
  schema: switches/v1
  global: {state: 'on', reason: null}
  groups:
    lh-loops: {state: 'on'}
    paused: {state: 'off', reason: paused for the audit}
  loops:
    lh/factory:
      repo: o/lh
      workflow: .github/workflows/content-factory.yml
      group: lh-loops
      gate: {kind: repo_variable, name: CONTENT_FACTORY_ENABLED, semantics: opt_in}
      default: 'off'
      state: 'on'
      verified: true
      reason: maintainer instruction
      set_by: bamr87
      set_at: '2026-11-24'
    lh/issue-1:
      repo: o/lh
      workflow: .github/workflows/factory--issue-factory-1.yml
      group: lh-loops
      gate: {kind: repo_variable, name: ISSUE_FACTORY_ENABLED, semantics: opt_in}
      default: 'off'
      state: 'on'
      verified: true
    lh/issue-2:
      repo: o/lh
      workflow: .github/workflows/factory--issue-factory-2.yml
      group: lh-loops
      gate: {kind: repo_variable, name: ISSUE_FACTORY_ENABLED, semantics: opt_in}
      default: 'off'
      state: 'on'
      verified: true
    lh/auto-merge:
      repo: o/lh
      workflow: .github/workflows/auto-merge.yml
      group: lh-loops
      gate: {kind: repo_variable, name: AUTO_MERGE_ENABLED, semantics: opt_in}
      default: 'off'
      state: 'off'
      verified: true
      hold: {kind: env, name: HUB_ORIGINATION_HOLD, value: 'true', lift: a new amendment}
    lh/weekly-epic:
      repo: o/lh
      workflow: .github/workflows/weekly-epic.yml
      group: lh-loops
      gate: {kind: repo_variable, name: WEEKLY_EPIC_ENABLED, semantics: opt_in}
      default: 'off'
      state: unverified
    lh/nightly:
      repo: o/lh
      workflow: .github/workflows/nightly.yml
      group: lh-loops
      gate: {kind: none}
      default: 'on'
      state: unverified
    ij/daily:
      repo: O/IJ
      workflow: .github/workflows/cms-daily.yml
      group: lh-loops
      gate: {kind: repo_variable, name: CMS_DAILY_LOOP_ENABLED, semantics: opt_out}
      default: 'on'
      state: 'on'
    ij/links:
      repo: o/ij
      workflow: .github/workflows/link-checker.yml
      group: paused
      gate: {kind: repo_variable, name: LINK_CHECKER_ENABLED, semantics: opt_out}
      default: 'on'
      state: 'on'
    hub/pulse:
      repo: bamr87/bamr87
      workflow: .github/workflows/fleet-pulse.yml
      group: lh-loops
      gate: {kind: repo_variable, name: FLEET_PULSE_ENABLED, semantics: opt_out}
      default: 'on'
      state: unverified
"""

LH = {
    "CONTENT_FACTORY_ENABLED": "true",
    "ISSUE_FACTORY_ENABLED": "false",
    "AUTO_MERGE_ENABLED": "true",
    "BRAND_SWEEP_ENABLED": "false",
    "NODE_VERSION": "20",
}
IJ = {"LINK_CHECKER_ENABLED": "true", "QUEST_FIX_ENABLED": "true", "CONTENT_AUTOMERGE_ENABLED": "false"}


def variables_of(values: dict) -> dict:
    return {"total_count": len(values), "variables": [{"name": k, "value": v} for k, v in values.items()]}


@pytest.fixture
def manager(db):
    person = get_user_model().objects.create_user("manager", password="pw")
    person.user_permissions.add(Permission.objects.get(codename="manage_site"))
    return person


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager)
    return client


@pytest.fixture
def config(db):
    config = SwitchConfig.load()
    config.outlets = ["o/lh", "o/ij"]
    config.save()
    return config


@pytest.fixture
def credential(config):
    config.set_credential(TOKEN)
    config.save()
    return config


@pytest.fixture
def github():
    """GitHub, recorded: the hub's map, and each outlet's variables (one page each)."""
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get(HUB).respond(200, text=MAP)
        router.get("/repos/o/lh/actions/variables").respond(200, json=variables_of(LH))
        router.get("/repos/o/ij/actions/variables").respond(200, json=variables_of(IJ))
        yield router
