"""
utils/api_clients.py
────────────────────
HTTP clients for all three external APIs:
  1. ClinicalTrials.gov v2 API  — trial data
  2. OpenFDA API                — drug interactions and adverse events
  3. RxNorm API                 — drug name normalization and RxNorm codes

Each client:
  - Uses httpx for async HTTP requests
  - Has retry logic (3 attempts with exponential backoff) via tenacity
  - Cleans and validates raw API responses
  - Returns typed Pydantic objects — never raw dicts
  - Handles rate limits and API errors gracefully
"""

import asyncio
import math
import re
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.schemas.trial import (
    ClinicalTrial,
    DrugInteractionFlag,
    EligibilityCriteria,
    SafetyLevel,
    TrialIntervention,
    TrialLocation,
    TrialPhase,
    TrialStatus,
)

# ── Shared HTTP timeout configuration ─────────────────────────────────────────
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

CTG_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 ClinicalTrialMatcher/1.0"
    ),
}

TRIALSMAP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Origin": "https://trialsmap.com",
    "Referer": "https://trialsmap.com/search",
    "User-Agent": CTG_HEADERS["User-Agent"],
}

# Prompt-shaped phrases a small model may echo instead of real conditions.
_QUERY_ARTIFACTS = {
    "medical condition names",
    "normalized conditions",
    "primary conditions",
    "secondary keywords",
    "search terms",
    "additional search terms",
    "list of conditions",
    "main conditions",
    "conditions",
    "symptoms",
}


# ═══════════════════════════════════════════════════════════════════════════════
# CLINICALTRIALS.GOV CLIENT
# ═══════════════════════════════════════════════════════════════════════════════


class ClinicalTrialsClient:
    """
    Client for ClinicalTrials.gov v2 API.
    Documentation: https://clinicaltrials.gov/data-api/api

    The v2 API returns structured JSON with these key sections:
      - protocolSection: main trial data
      - resultsSection: trial results (if available)
      - derivedSection: computed fields
    """

    BASE_URL = settings.clinicaltrials_base_url

    # Fields to request from API — only what we need, reduces response size
    FIELDS = ",".join(
        [
            "protocolSection.identificationModule",
            "protocolSection.statusModule",
            "protocolSection.descriptionModule",
            "protocolSection.conditionsModule",
            "protocolSection.designModule",
            "protocolSection.eligibilityModule",
            "protocolSection.armsInterventionsModule",
            "protocolSection.contactsLocationsModule",
            "protocolSection.sponsorCollaboratorsModule",
        ]
    )

    def _normalize_query_terms(self, terms: list[str], limit: int) -> list[str]:
        """Trim, deduplicate, and cap free-text search terms.

        LLM output occasionally echoes prompt instructions (for example
        "Medical Condition Names"). Those artifacts make ClinicalTrials.gov
        queries invalid or return nothing, so they are discarded here as a
        second line of defence.
        """
        cleaned = []
        seen = set()

        for raw_term in terms:
            if not isinstance(raw_term, str) or not raw_term.strip():
                continue

            term = " ".join(raw_term.strip().split())
            key = term.casefold()
            if key in _QUERY_ARTIFACTS or key in seen:
                continue
            if len(term) > 120 or len(term.split()) > 10:
                continue

            seen.add(key)
            cleaned.append(term)

            if len(cleaned) >= limit:
                break

        return cleaned

    def _build_ctg_search_variants(
        self,
        conditions: list[str],
        keywords: list[str],
        status: str,
        min_age: int | None,
        sex: str | None,
        page_size: int,
    ) -> list[dict[str, str]]:
        """
        Build a small sequence of increasingly simpler requests.

        ClinicalTrials.gov sometimes rejects more complex requests with 403. We keep
        the first attempt specific, then progressively relax optional filters.
        """
        cleaned_conditions = self._normalize_query_terms(conditions, limit=3)
        cleaned_keywords = self._normalize_query_terms(keywords, limit=3)

        primary_condition = cleaned_conditions[0] if cleaned_conditions else ""
        all_conditions = " ".join(cleaned_conditions)
        keyword_query = " ".join(cleaned_keywords)
        patient_query = " ".join(part for part in [all_conditions, keyword_query] if part).strip()

        base_params = {
            "pageSize": str(min(page_size, 20)),
            "format": "json",
            "countTotal": "true",
            "filter.overallStatus": status,
        }
        if min_age:
            base_params["filter.advanced"] = f"AREA[MinimumAge]RANGE[MIN, {min_age} years]"

        variants: list[dict[str, str]] = []

        # Start with the single most reliable query: one condition, no
        # free-text keywords. Extra terms are only added after this fails.
        if primary_condition:
            params = dict(base_params)
            params["query.cond"] = primary_condition
            variants.append(params)

        if primary_condition and keyword_query:
            params = dict(base_params)
            params["query.cond"] = primary_condition
            params["query.term"] = keyword_query
            variants.append(params)

        if all_conditions:
            params = dict(base_params)
            params["query.cond"] = all_conditions
            variants.append(params)

        if patient_query:
            params = dict(base_params)
            params["query.patient"] = patient_query
            variants.append(params)

        if keyword_query:
            params = dict(base_params)
            params["query.term"] = keyword_query
            variants.append(params)

        unique_variants = []
        seen_variants = set()
        for params in variants:
            signature = tuple(sorted(params.items()))
            if signature in seen_variants:
                continue
            seen_variants.add(signature)
            unique_variants.append(params)

        return unique_variants

    def _parse_trialsmap_age_range(self, age_text: str) -> tuple[int | None, int | None]:
        numbers = [int(value) for value in re.findall(r"\d+", age_text or "")]
        if not numbers:
            return None, None
        if len(numbers) == 1:
            return numbers[0], None
        return numbers[0], numbers[1]

    def _parse_trialsmap_status(self, status_text: str) -> TrialStatus:
        normalized = re.sub(r"\s+", "_", (status_text or "").strip().upper())
        mapping = {
            "RECRUITING": TrialStatus.RECRUITING,
            "NOT_YET_RECRUITING": TrialStatus.NOT_YET_RECRUITING,
            "ACTIVE,_NOT_RECRUITING": TrialStatus.ACTIVE_NOT_RECRUITING,
            "ACTIVE_NOT_RECRUITING": TrialStatus.ACTIVE_NOT_RECRUITING,
            "COMPLETED": TrialStatus.COMPLETED,
            "TERMINATED": TrialStatus.TERMINATED,
            "WITHDRAWN": TrialStatus.WITHDRAWN,
            "SUSPENDED": TrialStatus.SUSPENDED,
        }
        return mapping.get(normalized, TrialStatus.UNKNOWN)

    def _parse_trialsmap_sex(self, gender_text: str) -> str:
        value = (gender_text or "").strip().upper()
        if value == "MALE":
            return "Male"
        if value == "FEMALE":
            return "Female"
        return "All"

    def _extract_trialsmap_field(self, article_html: str, label: str) -> str:
        pattern = (
            rf"<p class=\"text-xs text-gray-500 mb-1\">{re.escape(label)}</p>\s*"
            rf"<p class=\"text-sm font-medium text-gray-900\">(.*?)</p>"
        )
        match = re.search(pattern, article_html, flags=re.DOTALL)
        if not match:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip()

    def _parse_trialsmap_article(
        self,
        article_html: str,
        conditions: list[str],
        keywords: list[str],
    ) -> ClinicalTrial | None:
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", article_html, flags=re.DOTALL)
        if not title_match:
            return None

        brief_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title_match.group(1))).strip()
        if not brief_title:
            return None

        link_match = re.search(r"href=\"(https://clinicaltrials\.gov/show/(NCT\d{8}))\"", article_html)
        if not link_match:
            return None

        trial_url = link_match.group(1)
        nct_id = link_match.group(2)

        status_match = re.search(
            r"rounded-full whitespace-nowrap\">\s*([^<]+?)\s*</span>",
            article_html,
            flags=re.DOTALL,
        )
        status = self._parse_trialsmap_status(status_match.group(1) if status_match else "")

        summary_match = re.search(
            r"<p class=\"text-gray-700 leading-relaxed\" x-show=\"expanded\"[^>]*>(.*?)</p>",
            article_html,
            flags=re.DOTALL,
        )
        brief_summary = re.sub(
            r"\s+",
            " ",
            re.sub(r"<[^>]+>", " ", summary_match.group(1) if summary_match else brief_title),
        ).strip()

        sponsor = self._extract_trialsmap_field(article_html, "Sponsor") or None
        age_text = self._extract_trialsmap_field(article_html, "Age Range")
        gender_text = self._extract_trialsmap_field(article_html, "Gender")
        min_age, max_age = self._parse_trialsmap_age_range(age_text)
        sex_eligible = self._parse_trialsmap_sex(gender_text)

        countries = []
        for country in re.findall(r"\{ name: '([^']+)', hits: \d+ \}", article_html):
            if country not in countries:
                countries.append(country)
        locations = [TrialLocation(country=country, status=status.value) for country in countries]

        contact_name_match = re.search(
            r"<span class=\"font-medium\">Contact:</span>\s*([^<]+)",
            article_html,
            flags=re.DOTALL,
        )
        contact_email_match = re.search(r"href=\"mailto:([^\"]+)\"", article_html)
        contact_phone_match = re.search(r"href=\"tel:([^\"]+)\"", article_html)

        return ClinicalTrial(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=brief_title,
            acronym=None,
            status=status,
            phase=TrialPhase.NA,
            study_type="Interventional",
            brief_summary=brief_summary or brief_title,
            detailed_description=brief_summary or None,
            conditions=conditions,
            keywords=keywords,
            interventions=[],
            intervention_names=[],
            eligibility=EligibilityCriteria(
                raw_text="Eligibility details unavailable from TrialsMap fallback.",
                inclusion=[],
                exclusion=[],
                minimum_age=min_age,
                maximum_age=max_age,
                sex_eligible=sex_eligible,
                accepts_healthy_volunteers=False,
            ),
            locations=locations,
            location_count=len(locations),
            countries=countries,
            sponsor=sponsor,
            collaborators=[],
            start_date=None,
            completion_date=None,
            primary_completion_date=None,
            enrollment_count=None,
            enrollment_type=None,
            overall_contact_name=contact_name_match.group(1).strip() if contact_name_match else None,
            overall_contact_phone=contact_phone_match.group(1).strip() if contact_phone_match else None,
            overall_contact_email=contact_email_match.group(1).strip() if contact_email_match else None,
            url=trial_url,
        )

    async def _search_trials_via_trialsmap(
        self,
        conditions: list[str],
        keywords: list[str],
        page_size: int,
    ) -> dict[str, Any]:
        """
        HTML fallback when ClinicalTrials.gov is blocked from the local network.

        TrialsMap mirrors recruiting trial search results using public sources and is
        reachable from the user's machine in this environment.
        """
        search_terms = self._normalize_query_terms(conditions, limit=3)
        if not search_terms:
            search_terms = self._normalize_query_terms(keywords, limit=3)
        if not search_terms:
            raise RuntimeError("No search terms available for TrialsMap fallback")

        search_query = " ".join(search_terms)
        max_pages = max(1, min(5, math.ceil(min(page_size, 35) / 7)))

        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=TRIALSMAP_HEADERS,
            trust_env=False,
            follow_redirects=True,
        ) as client:
            landing = await client.get("https://trialsmap.com/search")
            landing.raise_for_status()

            token_match = re.search(
                r"name=\"csrfmiddlewaretoken\" value=\"([^\"]+)\"",
                landing.text,
            )
            if not token_match:
                raise RuntimeError("TrialsMap fallback failed: missing CSRF token")

            response = await client.post(
                "https://trialsmap.com/search",
                data={
                    "csrfmiddlewaretoken": token_match.group(1),
                    "q": search_query,
                },
            )
            response.raise_for_status()

            html_pages = [response.text]
            for page_num in range(2, max_pages + 1):
                next_page = await client.get(f"https://trialsmap.com/search?page={page_num}")
                if next_page.status_code != 200:
                    break
                if "No trials found" in next_page.text:
                    break
                html_pages.append(next_page.text)

        total_match = re.search(
            r"Found <span class=\"font-semibold text-gray-900\">([\d,]+)</span> clinical trials",
            html_pages[0],
        )
        total_count = int(total_match.group(1).replace(",", "")) if total_match else 0

        parsed_trials: list[ClinicalTrial] = []
        seen_nct_ids = set()
        for html_page in html_pages:
            for article_html in re.findall(r"(<article class=\"bg-white.*?</article>)", html_page, flags=re.DOTALL):
                trial = self._parse_trialsmap_article(article_html, conditions, keywords)
                if not trial or trial.nct_id in seen_nct_ids:
                    continue
                seen_nct_ids.add(trial.nct_id)
                parsed_trials.append(trial)
                if len(parsed_trials) >= page_size:
                    break
            if len(parsed_trials) >= page_size:
                break

        logger.warning(
            f"Using TrialsMap fallback source for trial search. "
            f"Recovered {len(parsed_trials)} trials for query '{search_query}'."
        )
        return {
            "studies": [],
            "parsed_trials": parsed_trials,
            "total_count": total_count or len(parsed_trials),
            "next_page_token": None,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def search_trials(
        self,
        conditions: list[str],
        keywords: list[str] | None = None,
        status: str = "RECRUITING",
        min_age: int | None = None,
        max_age: int | None = None,
        sex: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """
        Search ClinicalTrials.gov for trials matching patient criteria.

        Returns raw API response dict — cleaning happens in parse_trial().
        Uses cursor-based pagination internally (API uses pageToken).
        """
        query_variants = self._build_ctg_search_variants(
            conditions=conditions,
            keywords=keywords or [],
            status=status,
            min_age=min_age,
            sex=sex,
            page_size=page_size,
        )

        last_error = None
        data = None

        async with httpx.AsyncClient(timeout=TIMEOUT, headers=CTG_HEADERS, trust_env=False) as client:
            for idx, params in enumerate(query_variants, start=1):
                try:
                    logger.info(f"Querying ClinicalTrials.gov (attempt {idx}/{len(query_variants)}): params={params}")
                    response = await client.get(f"{self.BASE_URL}/studies", params=params)
                    response.raise_for_status()
                    data = response.json()
                    if not data.get("studies") and idx < len(query_variants):
                        logger.info(
                            f"ClinicalTrials.gov returned 0 studies on attempt {idx}; trying a simpler query variant"
                        )
                        continue
                    break
                except httpx.HTTPStatusError as e:
                    last_error = e
                    body_preview = e.response.text[:300].replace("\n", " ").strip()
                    logger.warning(
                        f"ClinicalTrials.gov HTTP {e.response.status_code} on attempt {idx}: "
                        f"{body_preview or '[no response body]'}"
                    )
                    if e.response.status_code in {400, 403, 422}:
                        if idx < len(query_variants):
                            continue
                        break
                    raise

        if data is None:
            if last_error:
                if isinstance(last_error, httpx.HTTPStatusError) and last_error.response.status_code in {400, 403, 422}:
                    return await self._search_trials_via_trialsmap(
                        conditions=conditions,
                        keywords=keywords or [],
                        page_size=min(page_size, 35),
                    )
                raise last_error
            raise RuntimeError("ClinicalTrials.gov request failed without a response")

        total_count = data.get("totalCount", 0)
        studies = data.get("studies", [])
        logger.info(f"ClinicalTrials.gov returned {len(studies)} studies (total: {total_count})")
        return {
            "studies": studies,
            "total_count": total_count,
            "next_page_token": data.get("nextPageToken"),
        }

    def parse_trial(self, raw_study: dict[str, Any]) -> ClinicalTrial | None:
        """
        Convert raw ClinicalTrials.gov API response into a clean ClinicalTrial object.

        The raw API response has deeply nested structure. This function:
        1. Extracts all relevant fields
        2. Strips HTML from text
        3. Parses eligibility criteria into structured lists
        4. Normalizes dates, statuses, and phases
        5. Returns None if trial data is incomplete/unusable
        """
        try:
            protocol = raw_study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            desc_module = protocol.get("descriptionModule", {})
            conditions_module = protocol.get("conditionsModule", {})
            design_module = protocol.get("designModule", {})
            eligibility_module = protocol.get("eligibilityModule", {})
            contacts_module = protocol.get("contactsLocationsModule", {})
            arms_module = protocol.get("armsInterventionsModule", {})
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})

            # Required fields — skip trial if missing
            nct_id = id_module.get("nctId")
            if not nct_id:
                return None

            # Parse status with fallback
            raw_status = status_module.get("overallStatus", "UNKNOWN").upper().replace(" ", "_")
            try:
                status = TrialStatus(raw_status)
            except ValueError:
                status = TrialStatus.UNKNOWN

            # Parse phase
            phases = design_module.get("phases", [])
            raw_phase = phases[0] if phases else "NA"
            phase_map = {
                "PHASE1": TrialPhase.PHASE1,
                "PHASE2": TrialPhase.PHASE2,
                "PHASE3": TrialPhase.PHASE3,
                "PHASE4": TrialPhase.PHASE4,
                "EARLY_PHASE1": TrialPhase.EARLY_PHASE1,
                "NA": TrialPhase.NA,
            }
            phase = phase_map.get(raw_phase.upper().replace(" ", ""), TrialPhase.NA)

            # Parse eligibility criteria
            eligibility = self._parse_eligibility(eligibility_module)

            # Parse interventions
            interventions = self._parse_interventions(arms_module)
            intervention_names = [i.name for i in interventions]

            # Parse locations
            locations = self._parse_locations(contacts_module)
            location_count = len(locations)
            countries = list(set(loc.country for loc in locations if loc.country))

            # Parse contacts
            contact_data = contacts_module.get("centralContacts", [{}])
            first_contact = contact_data[0] if contact_data else {}

            # Build title
            brief_title = id_module.get("briefTitle", "").strip()
            if not brief_title:
                return None  # Skip trials with no title

            return ClinicalTrial(
                nct_id=nct_id,
                brief_title=brief_title,
                official_title=id_module.get("officialTitle"),
                acronym=id_module.get("acronym"),
                status=status,
                phase=phase,
                study_type=design_module.get("studyType", "Interventional"),
                brief_summary=desc_module.get("briefSummary", "No description available."),
                detailed_description=desc_module.get("detailedDescription"),
                conditions=conditions_module.get("conditions", []),
                keywords=conditions_module.get("keywords", []),
                interventions=interventions,
                intervention_names=intervention_names,
                eligibility=eligibility,
                locations=locations,
                location_count=location_count,
                countries=countries,
                sponsor=sponsor_module.get("leadSponsor", {}).get("name"),
                collaborators=[c.get("name", "") for c in sponsor_module.get("collaborators", [])],
                start_date=status_module.get("startDateStruct", {}).get("date"),
                completion_date=status_module.get("completionDateStruct", {}).get("date"),
                primary_completion_date=status_module.get("primaryCompletionDateStruct", {}).get("date"),
                enrollment_count=design_module.get("enrollmentInfo", {}).get("count"),
                enrollment_type=design_module.get("enrollmentInfo", {}).get("type"),
                overall_contact_name=first_contact.get("name"),
                overall_contact_phone=first_contact.get("phone"),
                overall_contact_email=first_contact.get("email"),
                url=f"https://clinicaltrials.gov/study/{nct_id}",
            )

        except Exception as e:
            logger.warning(f"Failed to parse trial: {e}")
            return None

    def _parse_eligibility(self, module: dict) -> EligibilityCriteria:
        """
        Parse raw eligibility text into structured inclusion/exclusion lists.

        Raw text looks like:
          "Inclusion Criteria:\n- Age 18-65\n- HbA1c > 7.5%\nExclusion Criteria:\n- Pregnancy"

        We split on "Exclusion Criteria" and then parse each bullet point.
        """
        raw_text = module.get("eligibilityCriteria", "")

        inclusion = []
        exclusion = []

        if raw_text:
            # Split on exclusion criteria marker
            parts = re.split(r"exclusion criteria[:\s]*", raw_text, flags=re.IGNORECASE)
            incl_text = parts[0] if parts else raw_text
            excl_text = parts[1] if len(parts) > 1 else ""

            # Remove "Inclusion Criteria" header
            incl_text = re.sub(r"inclusion criteria[:\s]*", "", incl_text, flags=re.IGNORECASE)

            # Parse bullet points (lines starting with -, *, •, numbers)
            inclusion = self._parse_bullets(incl_text)
            exclusion = self._parse_bullets(excl_text)

        # Parse age limits
        min_age_str = module.get("minimumAge", "")
        max_age_str = module.get("maximumAge", "")
        min_age = self._parse_age_years(min_age_str)
        max_age = self._parse_age_years(max_age_str)

        # Sex eligibility
        sex_raw = module.get("sex", "All")
        sex_map = {"ALL": "All", "MALE": "Male", "FEMALE": "Female"}
        sex_eligible = sex_map.get(sex_raw.upper(), "All")

        return EligibilityCriteria(
            raw_text=raw_text,
            inclusion=inclusion,
            exclusion=exclusion,
            minimum_age=min_age,
            maximum_age=max_age,
            sex_eligible=sex_eligible,
            accepts_healthy_volunteers=self._parse_healthy_volunteers(module.get("healthyVolunteers")),
        )

    def _parse_healthy_volunteers(self, value: Any) -> bool:
        """Normalize the API's boolean-or-string healthyVolunteers field."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return "yes" in value.lower()
        return False

    def _parse_bullets(self, text: str) -> list[str]:
        """Parse bullet-pointed list text into a clean Python list."""
        if not text:
            return []
        # Split on common bullet patterns
        lines = re.split(r"\n+", text.strip())
        bullets = []
        for line in lines:
            # Remove bullet symbols and clean
            clean = re.sub(r"^[\s\-\*\•\d\.\)]+", "", line).strip()
            if clean and len(clean) > 5:  # Skip very short fragments
                bullets.append(clean)
        return bullets

    def _parse_age_years(self, age_str: str) -> int | None:
        """Convert '18 Years' -> 18, '6 Months' -> 0, 'N/A' -> None."""
        if not age_str or age_str.upper() in ("N/A", ""):
            return None
        match = re.search(r"(\d+)", age_str)
        if not match:
            return None
        value = int(match.group(1))
        if "month" in age_str.lower():
            return max(0, value // 12)
        if "week" in age_str.lower():
            return 0
        return value

    def _parse_interventions(self, module: dict) -> list[TrialIntervention]:
        """Parse intervention list from arms/interventions module."""
        interventions = []
        for item in module.get("interventions", []):
            interventions.append(
                TrialIntervention(
                    intervention_type=item.get("type", "Other"),
                    name=item.get("name", "Unknown"),
                    description=item.get("description"),
                    arm_group=", ".join(item.get("armGroupLabels", [])),
                )
            )
        return interventions

    def _parse_locations(self, module: dict) -> list[TrialLocation]:
        """Parse location list — limit to first 10 to avoid huge responses."""
        locations = []
        raw_locations = module.get("locations", [])[:10]
        for loc in raw_locations:
            locations.append(
                TrialLocation(
                    facility=loc.get("facility"),
                    city=loc.get("city"),
                    state=loc.get("state"),
                    country=loc.get("country", "United States"),
                    zip_code=loc.get("zip"),
                    status=loc.get("status"),
                    contact_name=loc.get("contacts", [{}])[0].get("name") if loc.get("contacts") else None,
                    contact_phone=loc.get("contacts", [{}])[0].get("phone") if loc.get("contacts") else None,
                    contact_email=loc.get("contacts", [{}])[0].get("email") if loc.get("contacts") else None,
                )
            )
        return locations


# ═══════════════════════════════════════════════════════════════════════════════
# OPENFDA CLIENT
# ═══════════════════════════════════════════════════════════════════════════════


class OpenFDAClient:
    """
    Client for OpenFDA Drug API.
    Documentation: https://open.fda.gov/apis/drug/

    Used to check:
    1. Drug-drug interactions
    2. Contraindications
    3. Adverse event history
    4. Drug warnings
    """

    BASE_URL = settings.openfda_base_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def get_drug_interactions(
        self,
        drug_name: str,
        patient_medications: list[str],
    ) -> list[DrugInteractionFlag]:
        """
        Check if a trial drug has known interactions with patient's medications.

        Queries the FDA drug label endpoint which contains:
        - drug_interactions field: known interactions
        - warnings field: serious safety warnings
        - contraindications field: absolute contraindications
        """
        flags = []

        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            try:
                # Search FDA drug labels
                response = await client.get(
                    f"{self.BASE_URL}/label.json",
                    params={
                        "search": f'openfda.generic_name:"{drug_name}"',
                        "limit": 1,
                    },
                )

                if response.status_code == 404:
                    logger.debug(f"OpenFDA: no label found for {drug_name}")
                    return []

                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])

                if not results:
                    return []

                label = results[0]

                # Check drug interactions section
                interactions_text = " ".join(label.get("drug_interactions", [])).lower()

                # Check contraindications
                contra_text = " ".join(label.get("contraindications", [])).lower()

                # Check each patient medication against the label
                for patient_med in patient_medications:
                    med_lower = patient_med.lower()

                    if med_lower in interactions_text:
                        # Extract relevant sentence for context
                        sentences = interactions_text.split(".")
                        relevant = [s for s in sentences if med_lower in s]
                        description = relevant[0].strip() if relevant else f"Interaction with {patient_med} documented."

                        flags.append(
                            DrugInteractionFlag(
                                patient_drug=patient_med,
                                trial_drug=drug_name,
                                interaction_description=description[:500],
                                severity=SafetyLevel.WARNING,
                                source="OpenFDA",
                                recommendation=(
                                    f"Review {patient_med} + {drug_name} combination with a pharmacist "
                                    "before enrollment."
                                ),
                            )
                        )

                    if med_lower in contra_text:
                        flags.append(
                            DrugInteractionFlag(
                                patient_drug=patient_med,
                                trial_drug=drug_name,
                                interaction_description=(
                                    f"Contraindication documented between {drug_name} and {patient_med}."
                                ),
                                severity=SafetyLevel.CRITICAL,
                                source="OpenFDA",
                                recommendation=(
                                    f"CRITICAL: {patient_med} is contraindicated with {drug_name}. "
                                    "Do not proceed without specialist review."
                                ),
                            )
                        )

            except httpx.HTTPStatusError as e:
                logger.warning(f"OpenFDA HTTP error for {drug_name}: {e.response.status_code}")
            except Exception as e:
                logger.warning(f"OpenFDA error for {drug_name}: {e}")

        return flags

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException,)),
    )
    async def get_adverse_events(self, drug_name: str, limit: int = 5) -> list[dict]:
        """
        Get top adverse events reported for a drug.
        Used to generate physician warnings.
        """
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/event.json",
                    params={
                        "search": f'patient.drug.medicinalproduct:"{drug_name}"',
                        "count": "patient.reaction.reactionmeddrapt.exact",
                        "limit": limit,
                    },
                )
                if response.status_code != 200:
                    return []
                data = response.json()
                return data.get("results", [])
            except Exception as e:
                logger.debug(f"Adverse events lookup failed for {drug_name}: {e}")
                return []


# ═══════════════════════════════════════════════════════════════════════════════
# RXNORM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════


class RxNormClient:
    """
    Client for NLM RxNorm API.
    Documentation: https://rxnav.nlm.nih.gov/RxNormAPIs.html

    RxNorm is the US standard for drug naming and coding.
    Used to:
    1. Normalize drug names (brand → generic)
    2. Get RxNorm codes for medications
    3. Find drug interaction data via drug classes

    All free. No API key required.
    """

    BASE_URL = settings.rxnorm_base_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def normalize_drug_name(self, drug_name: str) -> str | None:
        """
        Convert brand name to generic name and get RxNorm code.
        Example: "Tylenol" -> "acetaminophen"

        This is critical for consistent drug interaction checking.
        Brand names differ by country; generic names are universal.
        """
        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            try:
                # Search by approximate name
                response = await client.get(
                    f"{self.BASE_URL}/approximateTerm.json",
                    params={
                        "term": drug_name,
                        "maxEntries": 1,
                    },
                )
                if response.status_code != 200:
                    return drug_name.lower()

                data = response.json()
                candidates = data.get("approximateGroup", {}).get("candidate", [])
                if not candidates:
                    return drug_name.lower()

                rxcui = candidates[0].get("rxcui")
                if not rxcui:
                    return drug_name.lower()

                # Get the generic name for this RxCUI
                props_response = await client.get(f"{self.BASE_URL}/rxcui/{rxcui}/properties.json")
                if props_response.status_code != 200:
                    return drug_name.lower()

                props = props_response.json().get("properties", {})
                generic_name = props.get("name", drug_name).lower()
                logger.debug(f"RxNorm normalized '{drug_name}' -> '{generic_name}' (RxCUI: {rxcui})")
                return generic_name

            except Exception as e:
                logger.debug(f"RxNorm lookup failed for {drug_name}: {e}")
                return drug_name.lower()

    async def normalize_medications(self, drug_names: list[str]) -> list[str]:
        """
        Normalize a list of drug names concurrently.
        Uses asyncio.gather for parallel API calls.
        """
        tasks = [self.normalize_drug_name(name) for name in drug_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        normalized = []
        for original, result in zip(drug_names, results, strict=False):
            if isinstance(result, BaseException):
                normalized.append(original.lower())
            else:
                normalized.append(result or original.lower())
        return normalized

    async def get_interaction_list(self, rxcui_list: list[str]) -> list[dict]:
        """
        Check for interactions between multiple drugs using RxNorm Interaction API.
        More comprehensive than FDA label text matching.
        """
        if len(rxcui_list) < 2:
            return []

        async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/interaction/list.json", params={"rxcuis": "+".join(rxcui_list[:10])}
                )
                if response.status_code != 200:
                    return []
                data = response.json()
                return data.get("fullInteractionTypeGroup", [])
            except Exception as e:
                logger.debug(f"RxNorm interaction list failed: {e}")
                return []


# ── Singleton instances ────────────────────────────────────────────────────────
# These are created once and reused across requests

clinical_trials_client = ClinicalTrialsClient()
openfda_client = OpenFDAClient()
rxnorm_client = RxNormClient()
