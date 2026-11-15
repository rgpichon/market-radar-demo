# Phase 5 & 6: Quality Assurance & Maintenance Report

**Generated**: 2026-01-26 18:26:06

---

## Phase 5: Quality Assurance

### ❌ Sources with 0 Events (RED FLAG)

These sources are active but extracting 0 events. Selectors may be broken.

| Source | Adapter | Action |
|--------|---------|--------|
| FIA (fia_events) | playwright | `python scripts/test_source.py fia_events 5` |

### Past Events Check

⚠️ Found 20 past events in database

Note: Past events should be filtered by the pipeline. This may be expected if events were added before filtering was implemented.

### Duplicate Events Check

⚠️ Found 20 potential duplicate events (same title from same firm)

Top duplicates:

- **Oxford Said Business School**: "mba one-to-one meetings in london" (7 times)
- **CEPR**: "adrien auclert - virtual seminar on monetary economics (vsme" (6 times)
- **CEPR**: "entertainment" or "slant"? media demand and the effects of c" (5 times)
- **BIS IFC**: "data science in central banking" (4 times)
- **CEPR**: "gernot müller - virtual seminar on monetary economics (vsme)" (4 times)
- **CFR**: "a conversation with jay bhattacharya of the national institu" (4 times)
- **CFR**: "a conversation with joão cravinho, eu special representative" (4 times)
- **CFR**: "academic webinar: the geopolitics of oil" (4 times)
- **CFR**: "forecasting humanitarian risk in 2026: a conversation with d" (4 times)
- **CFR**: "martin s. indyk memorial lecture: a conversation with presid" (4 times)

Note: Some duplicates may be legitimate (e.g., recurring events with same title)

---

## Phase 6: Maintenance

### Monthly Re-test Checklist

Total active sources to monitor: 22

**Recommended**: Re-test all sources monthly to catch broken selectors early.

| # | Source | Adapter | Test Command |
|---|--------|---------|---------------|
| 1 | Brookings Institution (brookings_events) | html_list | `python scripts/test_source.py brookings_events 5` |
| 2 | CEPR (cepr_events) | html_list | `python scripts/test_source.py cepr_events 5` |
| 3 | CSIS (csis_events) | html_list | `python scripts/test_source.py csis_events 5` |
| 4 | Bruegel (bruegel_events) | html_list | `python scripts/test_source.py bruegel_events 5` |
| 5 | LSE (lse_events) | html_list | `python scripts/test_source.py lse_events 5` |
| 6 | Wilson Center (wilson_events) | html_list | `python scripts/test_source.py wilson_events 5` |
| 7 | NBER (nber_events) | json_api | `python scripts/test_source.py nber_events 5` |
| 8 | ICMA (icma_events) | html_list | `python scripts/test_source.py icma_events 5` |
| 9 | ISDA (isda_events) | rss | `python scripts/test_source.py isda_events 5` |
| 10 | IIF (iif_events) | html_list | `python scripts/test_source.py iif_events 5` |
| 11 | AFME (afme_events) | html_list | `python scripts/test_source.py afme_events 5` |
| 12 | BIS IFC (bis_ifc_events) | html_list | `python scripts/test_source.py bis_ifc_events 5` |
| 13 | ECB (ecb_conferences) | html_list | `python scripts/test_source.py ecb_conferences 5` |
| 14 | FIA (fia_events) | playwright | `python scripts/test_source.py fia_events 5` |
| 15 | CFR (cfr_events) | html_list | `python scripts/test_source.py cfr_events 5` |
| 16 | MIT Sloan (mit_sloan_events) | html_list | `python scripts/test_source.py mit_sloan_events 5` |
| 17 | Milken Institute (milken_events) | html_list | `python scripts/test_source.py milken_events 5` |
| 18 | Stanford GSB (stanford_gsb_events) | html_list | `python scripts/test_source.py stanford_gsb_events 5` |
| 19 | Oxford Said Business School (oxford_said_events) | html_list | `python scripts/test_source.py oxford_said_events 5` |
| 20 | Carnegie Endowment (carnegie_events) | html_list | `python scripts/test_source.py carnegie_events 5` |

... and 2 more sources

### Weekly Tasks

- Check source health report: `python scripts/report_sources.py`
- Review this monitoring report

### Monthly Tasks

- Re-test sources with 0 events
- Re-test sources with declining event counts
- Review and update selectors if needed

### Quarterly Tasks

- Review all sources with <10 events
- Update selectors for sources with declining event counts
- Check for new adapter types or methods
