"""
tests/test_api_clients.py — Tests for API client parsing (no real API calls)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.api_clients import ClinicalTrialsClient
from schemas.trial import TrialStatus, TrialPhase

def make_raw_study(nct_id="NCT12345678", status="RECRUITING", phase="PHASE3"):
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": nct_id,
                "briefTitle": "Test Diabetes Trial",
            },
            "statusModule": {
                "overallStatus": status,
                "startDateStruct": {"date": "2023-01-15"},
            },
            "descriptionModule": {
                "briefSummary": "<p>This is a <b>test</b> trial.</p>",
            },
            "conditionsModule": {
                "conditions": ["Type 2 Diabetes Mellitus"],
                "keywords": ["insulin"],
            },
            "designModule": {
                "studyType": "Interventional",
                "phases": [phase],
                "enrollmentInfo": {"count": 200},
            },
            "eligibilityModule": {
                "eligibilityCriteria": (
                    "Inclusion Criteria:\n- Age 18-70\n- HbA1c > 7.5%\n"
                    "Exclusion Criteria:\n- Pregnancy\n- Renal impairment"
                ),
                "minimumAge": "18 Years",
                "maximumAge": "70 Years",
                "sex": "ALL",
                "healthyVolunteers": "No",
            },
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "Drug", "name": "Metformin"},
                ]
            },
            "contactsLocationsModule": {
                "locations": [{"facility": "Stanford", "city": "Stanford", "country": "United States"}],
                "centralContacts": [],
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Stanford"}, "collaborators": []},
        }
    }

client = ClinicalTrialsClient()

def test_parse_trial_returns_trial():
    trial = client.parse_trial(make_raw_study())
    assert trial is not None
    assert trial.nct_id == "NCT12345678"

def test_parse_trial_strips_html():
    trial = client.parse_trial(make_raw_study())
    assert "<p>" not in trial.brief_summary
    assert "test" in trial.brief_summary.lower()

def test_parse_trial_status():
    trial = client.parse_trial(make_raw_study(status="RECRUITING"))
    assert trial.status == TrialStatus.RECRUITING

def test_parse_trial_phase():
    trial = client.parse_trial(make_raw_study(phase="PHASE3"))
    assert trial.phase == TrialPhase.PHASE3

def test_parse_eligibility_splits():
    trial = client.parse_trial(make_raw_study())
    assert len(trial.eligibility.inclusion) >= 1
    assert len(trial.eligibility.exclusion) >= 1
    assert trial.eligibility.minimum_age == 18
    assert trial.eligibility.maximum_age == 70

def test_trial_url_format():
    trial = client.parse_trial(make_raw_study(nct_id="NCT12345678"))
    assert trial.url == "https://clinicaltrials.gov/study/NCT12345678"

def test_missing_nct_returns_none():
    trial = client.parse_trial({"protocolSection": {"identificationModule": {}}})
    assert trial is None

def test_parse_age_years():
    assert client._parse_age_years("18 Years") == 18
    assert client._parse_age_years("6 Months") == 0
    assert client._parse_age_years("N/A") is None
    assert client._parse_age_years("") is None

def test_parse_bullets():
    text = "- Item one\n- Item two\n- Item three"
    bullets = client._parse_bullets(text)
    assert len(bullets) == 3


def test_parse_trialsmap_article_returns_trial():
    article_html = """
    <article class="bg-white rounded-xl shadow-lg hover:shadow-md transition-shadow p-6">
        <div class="mb-4">
            <div class="flex items-start justify-between gap-4 mb-2">
                <h2 class="text-xl font-semibold text-gray-900 leading-tight flex-1">
                    A study in people with type 2 diabetes
                </h2>
                <span class="px-3 py-1 bg-green-100 text-green-800 text-sm font-medium rounded-full whitespace-nowrap">
                    Recruiting
                </span>
            </div>
            <div class="space-y-4">
                <a href="https://clinicaltrials.gov/show/NCT01234567"
                   target="_blank"
                   rel="noopener noreferrer">
                    <span>NCT01234567 Clinical Trial Documentation</span>
                </a>
            </div>
        </div>
        <div class="mb-4">
            <p class="text-gray-700 leading-relaxed" x-show="expanded" x-cloak>
                Detailed summary for a recruiting diabetes study.
            </p>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4 p-4 bg-gray-50 rounded-lg">
            <div>
                <p class="text-xs text-gray-500 mb-1">Sponsor</p>
                <p class="text-sm font-medium text-gray-900">Example Sponsor</p>
            </div>
            <div>
                <p class="text-xs text-gray-500 mb-1">Age Range</p>
                <p class="text-sm font-medium text-gray-900">18 - 65+</p>
            </div>
            <div>
                <p class="text-xs text-gray-500 mb-1">Gender</p>
                <p class="text-sm font-medium text-gray-900">BOTH</p>
            </div>
        </div>
        <div x-data="{ showAllCountries: false, countries: [
            { name: 'United States', hits: 1 },
            { name: 'Canada', hits: 1 }
        ]}">
            <span class="font-medium">Contact:</span> Jane Doe
            <a href="mailto:jane@example.com">jane@example.com</a>
            <a href="tel:1234567890">1234567890</a>
        </div>
    </article>
    """
    trial = client._parse_trialsmap_article(
        article_html,
        conditions=["Type 2 Diabetes Mellitus"],
        keywords=["fatigue"],
    )

    assert trial is not None
    assert trial.nct_id == "NCT01234567"
    assert trial.status == TrialStatus.RECRUITING
    assert trial.sponsor == "Example Sponsor"
    assert trial.eligibility.minimum_age == 18
    assert trial.eligibility.maximum_age == 65
    assert trial.eligibility.sex_eligible == "All"
    assert trial.countries == ["United States", "Canada"]
