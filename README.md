# notagain-data

**Not Again (Stock Market Déjà Vu)** 앱의 데이터 저장소.

매일 1회 GitHub Actions가 `crawl.py`를 실행해 "지금 증시 차트가 과거 어느 시기와
가장 닮았는지"를 계산하고 `dejavu.json`을 갱신합니다. 앱이 raw URL로 직접 fetch.

| 파일 | 내용 |
|---|---|
| `sp_monthly.json` | 장기 S&P 월간 (1871~, Shiller/Yale 공개, 정적) |
| `dejavu.json` | 오늘의 아날로그 · 유사도 · 추적률 · 결과 · 겹침차트 시계열 |

## 데이터 출처 (무료·공개)
- 장기: [Robert Shiller (Yale)](http://www.econ.yale.edu/~shiller/data.htm) 월간 S&P
- 최근: [FRED](https://fred.stlouisfed.org) SP500

> 과거 시장 데이터의 패턴 유사도 정보이며, 미래 예측이나 투자 자문이 아닙니다.
