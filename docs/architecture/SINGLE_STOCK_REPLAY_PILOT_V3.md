# SINGLE_STOCK_REPLAY_PILOT_V3.md（Phase 7.3-M）

## 1. Sample Design
- **Source**: `universe_clean_with_dates.csv`（已排除退市股）
- **Fixtures**: 204 CNINFO fixtures (`fixtures/cninfo_*.parquet`)
- **Selection**: 3 dates per symbol with PIT_SAFE/APPROXIMATE historical market cap
- **Total**: 612 cases, 204 symbols, 606 runnable (6 cases lacked ≥60 klines)

## 2. Sample Quality
| Quality | Count | Reason |
|---------|-------|--------|
| HIGH | 0 | No symbol has KNOWN_NORMAL ST |
| MEDIUM | 0 | No symbol has STRICT market cap for all dates |
| LOW | 606 | Historical features + research mcap available, ST UNKNOWN |
| BLOCKED | 6 | Insufficient klines (<60) |

## 3. Small/Mid/Large
| Size Class | Cases | Symbols | Source |
|------------|-------|---------|--------|
| SMALL | 508 | 168 | PIT_SAFE/APPROXIMATE historical mcap |
| MID | 97 | 35 | PIT_SAFE/APPROXIMATE historical mcap |
| LARGE | 7 | 3 | PIT_SAFE/APPROXIMATE historical mcap |
| UNKNOWN | 0 | 0 | - |

**Key Finding**: Historical SMALL dominance is real. In 2005-2008, most current mid/large caps were <5B. This is a structural feature of Chinese equity market growth, not a sampling bug.

## 4. Time Distribution
| Year | Cases | Notes |
|------|-------|-------|
| 2005 | 173 | Early period |
| 2007 | 179 | Bull market peak |
| 2008 | 183 | Financial crisis |
| 2012 | 20 | Limited fixture coverage |
| 2015 | 15 | Bull market |
| 2018 | 15 | Bear market |
| 2022 | 16 | Recent |
| 2024 | 11 | Limited fixture coverage |

## 5. Historical Market Cap
- **PIT_SAFE**: 1481/1632 (90.8%)
- **APPROXIMATE**: 148/1632 (9.1%)
- **BLOCKED**: 3/1632 (0.2%)
- **Size classification**: Based on historical mcap, not current snapshot

## 6. ST
- **KNOWN_NORMAL**: 0
- **KNOWN_ST**: 0
- **UNKNOWN**: 606 (100%)
- All cases remain UNKNOWN; no conversion to NORMAL/ST

## 7. Filter Trace
### STRICT Mode
| Filter | PASS | FAIL | UNKNOWN |
|--------|------|------|---------|
| Market Cap | 323 | 273 | 10 |
| ST | 0 | 0 | 606 |
| Turnover 1D | 159 | 447 | 0 |
| Turnover 20D | 272 | 334 | 0 |
| Price Position | 255 | 301 | 50 |
| Volume Ratio | 27 | 579 | 0 |
| ATR | 528 | 78 | 0 |

### RESEARCH Mode
| Filter | PASS | FAIL | UNKNOWN |
|--------|------|------|---------|
| Market Cap | 429 | 177 | 0 |
| ST | 0 | 0 | 606 |
| Turnover 1D | 159 | 447 | 0 |
| Turnover 20D | 272 | 334 | 0 |
| Price Position | 255 | 301 | 50 |
| Volume Ratio | 27 | 579 | 0 |
| ATR | 528 | 78 | 0 |

## 8. Volume Ratio Distribution
| Size Class | Mean | Std | Min | Max | FAIL Rate |
|------------|------|-----|-----|-----|-----------|
| SMALL | 1.213 | 1.020 | 0.143 | 13.550 | 94.7% |
| MID | 1.106 | 0.741 | 0.127 | 5.709 | 96.8% |
| LARGE | 1.279 | 0.406 | 0.964 | 2.014 | 100% |

**Conclusion**: 95.7%+ FAIL is NOT sample bias alone. Even with historical small/mid caps, volume ratio 2.7 remains an extreme threshold in early years.

## 9. Price Position
| Size Class | Mean | Std | Min | Max |
|------------|------|-----|-----|-----|
| SMALL | 48.0% | 33.8% | 0% | 100% |
| MID | 55.1% | 35.2% | 0% | 100% |
| LARGE | 66.7% | 29.6% | 23.7% | 100% |

500-day window is stable and deterministic.

## 10. STRICT Dataset
- Total: 606 cases
- Final Candidate: 0 PASS, 0 FAIL, 606 UNKNOWN
- All UNKNOWN due to ST UNKNOWN 100%
- Cases passing all filters except ST: 3 (SMALL, 2008-10-15)

## 11. RESEARCH Dataset
- Total: 606 cases
- Final Candidate: 0 PASS, 0 FAIL, 606 UNKNOWN
- All UNKNOWN due to ST UNKNOWN 100%
- Cases passing all filters except ST: 3 (SMALL, 2008-10-15)

## 12. ST Sensitivity
### Best Case (UNKNOWN → NORMAL)
- Candidates: 3
- Affected symbols: 600111, 600508, 600748
- Affected dates: 2008-10-15
- All SMALL, historical mcap <5B

### Worst Case (UNKNOWN → ST)
- Candidates: 0
- Reason: All cases assumed ST → all FAIL

## 13. Data Purchase ROI
- **ST Impact Ratio**: 0.5%
- **Data Purchase ROI**: MEDIUM
- **Reason**: 3/606 cases would become candidates if ST were known NORMAL. This is a small but non-zero impact.

## 14. Future Research Return
- 5D/10D/20D/40D/60D returns can be computed but are marked `source = HISTORICAL_REPLAY`
- Not for Production Evaluation

## 15. Known Limitations
1. **Year coverage**: Heavy 2005-2008 concentration (72%); limited 2012-2024 due to fixture availability
2. **ST data**: 100% UNKNOWN; no KNOWN_NORMAL cases in sample
3. **Volume Ratio**: 95%+ FAIL even in historical small caps
4. **Turnover**: Historical turnover in early years is naturally lower than modern thresholds
5. **Sample composition**: SMALL 84%, MID 16%, LARGE 1% reflects historical market structure, not current universe
