# HISTORICAL_ST_SOURCE_POC.md（Phase 7.3-N）

## 1. Sources
| Source | Type | Coverage | PIT Safe | Status |
|--------|------|----------|----------|--------|
| akshare `stock_zh_a_st_em` | Current ST board snapshot | Current only | NO | UNKNOWN |
| akshare `stock_individual_notice_report` | Announcements | Current/recent | NO | UNKNOWN |
| akshare `stock_info_change_name` | Name change history | Partial, SSL unstable | NO | UNKNOWN |
| akshare `stock_info_sz_change_name` | SZ name change | Failed (KeyError) | NO | UNKNOWN |
| CNINFO share change | Already integrated for shares | N/A for ST | N/A | N/A |

## 2. Schema
No source provides the required fields:
- `status` (KNOWN_NORMAL / KNOWN_ST)
- `status_type` (ST / *ST / SST / etc.)
- `announcement_date`
- `event_date`
- `effective_date`
- `source_timestamp`
- `source_version`
- `historical_coverage`

## 3. Event Model
Not available from tested sources. East Money ST board is current-only. Announcement APIs lack structured ST state transitions with effective dates.

## 4. Effective Date
Cannot be determined. No source provides announcement date + effective date + next-trading-day rule.

## 5. PIT Semantics
UNKNOWN for all tested sources. No source can answer "was this stock ST at close on date T?"

## 6. Coverage
- Years: UNKNOWN (no historical coverage confirmed)
- Symbols: UNKNOWN (current snapshot only for ST board)
- Transitions: UNKNOWN

## 7. Strict / Research
Not applicable. No source meets STRICT or RESEARCH thresholds.

## 8. Sensitivity
Not applicable. Cannot build hypotheticals without base data.

## 9. Fixture
No historical ST fixtures created in this PoC.

## 10. Stability
Sources tested either return current-only data or fail on historical queries.

## 11. Purchase ROI
`DATA_INSUFFICIENT`

## 12. Replay Impact
Pilot impact remains 0.5% (3/606). Generalization status: `INSUFFICIENT`.

## 13. Known Limitations
1. Only free/public sources tested (akshare, East Money, CNINFO, SSE/SZSE)
2. No professional data providers tested (Wind, Choice, iFinD)
3. Announcement text parsing would be required for any source-based approach
4. Effective date semantics remain unresolved

## 14. Conclusion
`HISTORICAL_ST = BLOCKED / DATA_INSUFFICIENT`

Do not continue searching low-quality proxies.
