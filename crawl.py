# -*- coding: utf-8 -*-
"""
Not Again (역사적 데자뷰) — 프로덕션 크롤러.
정적 Shiller 월간(1871~) + FRED 최근 → 아날로그 매칭 + 추적률 + D-day + 겹침차트 시계열 → dejavu.json

출력 dejavu.json (앱이 raw fetch):
  analog(닮은 과거 구간·유사도·이후12개월수익률·결과라벨) / tracking(최근 추적률) / dday(경로상 다음 큰 이벤트) /
  distribution(상위매칭 상승·하락 분포) / series_now·series_analog·series_ghost(겹침 오버레이, rebased 100) / alternatives

의존성: curl(FRED). xlrd는 정적 JSON 생성 때만(크론 불필요).
⚠️ FRED = curl 기본 UA만(=-A 금지), cosd 기간제한.
"""
import io, json, math, os, subprocess, sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "sp_monthly.json")
OUT_DIR = BASE
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(BASE, "dejavu.json")

W = 18            # 비교 창(개월)
GHOST = 12        # 이후 경로 개월수
RECENT = 4        # 최근 추적 개월
HYST = 2.0        # 히스테리시스(%p) — 새 후보가 이만큼 높아야 챔피언 교체


def curl(url):
    r = subprocess.run(["curl", "-s", "--max-time", "60", url], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout


def mi_label(mi):
    return f"{mi // 12}-{mi % 12 + 1:02d}"


def load_series():
    """정적 히스토리 + FRED 최근월 → [(mi, price)] 오름차순, 완료월만."""
    data = json.load(open(STATIC, encoding="utf-8"))["series"]
    series = [(int(mi), float(p)) for mi, p in data]
    last = series[-1][0]
    csv = curl("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500&cosd=2024-01-01")
    monthly = {}
    for line in csv.strip().splitlines()[1:]:
        d, _, v = line.partition(",")
        v = v.strip()
        if v and v != ".":
            y, m, _ = d.split("-")
            monthly[int(y) * 12 + (int(m) - 1)] = float(v)   # 월 마지막값=월말근사
    for mi in sorted(monthly):
        if mi > last:
            series.append((mi, monthly[mi]))
    # 진행 중(당월)은 선정에서 제외 → 완료월만. 당월 = 현재 실시간
    now_mi = datetime.now(timezone.utc).year * 12 + (datetime.now(timezone.utc).month - 1)
    completed = [(mi, p) for mi, p in series if mi < now_mi]
    return completed


def rebased(vals):
    b = vals[0]
    return [round(v / b * 100, 2) for v in vals]


def zscore(vals):
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals)) or 1
    return [(v - m) / sd for v in vals]


def corr(a, b):
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a)); db = math.sqrt(sum((x - mb) ** 2 for x in b))
    return num / (da * db) if da and db else 0


def outcome_label(r):
    if r <= -12: return "crash"
    if r >= 12: return "boom"
    return "flat"


def dday_on_ghost(ghost_prices):
    """아날로그 이후 경로에서 최대 급락(또는 급등) 시작 시점(개월). 앞에서부터 최저점까지의 낙폭 기준."""
    if len(ghost_prices) < 3:
        return None
    base = ghost_prices[0]
    lo_i = min(range(len(ghost_prices)), key=lambda i: ghost_prices[i])
    hi_i = max(range(len(ghost_prices)), key=lambda i: ghost_prices[i])
    draw = (ghost_prices[lo_i] - base) / base
    rally = (ghost_prices[hi_i] - base) / base
    if draw <= -0.10 and lo_i > 0:
        # 하락 '시작' = 직전 고점 이후. 단순화: 시작을 base 이후 첫 하락 전환점~ 여기선 최저점까지의 개월 절반 지점
        start = max(1, lo_i // 2)
        return {"months": start, "event": "drop", "magnitude": round(draw * 100, 1)}
    if rally >= 0.12 and hi_i > 0:
        start = max(1, hi_i // 2)
        return {"months": start, "event": "surge", "magnitude": round(rally * 100, 1)}
    return None


def main():
    series = load_series()
    prices = [p for _, p in series]
    idxs = [mi for mi, _ in series]
    print(f"완료월 시계열: {len(series)}개  {mi_label(idxs[0])}~{mi_label(idxs[-1])}")

    cur_z = zscore(rebased(prices[-W:]))
    cur_start = idxs[-W]

    # 후보 슬라이딩
    cands = []
    for s in range(0, len(prices) - W - GHOST):
        if idxs[s] > cur_start - 6:
            break
        c = corr(cur_z, zscore(rebased(prices[s:s + W])))
        cands.append((c, s))
    cands.sort(reverse=True)

    # 중복 제거(3년 이내)
    picked = []
    for c, s in cands:
        if any(abs(idxs[s] - idxs[o]) < 36 for _, o in picked):
            continue
        picked.append((c, s))
        if len(picked) >= 6:
            break

    # 히스테리시스: 이전 챔피언 유지 조건
    prev = None
    if os.path.exists(OUT):
        prev = json.load(open(OUT, encoding="utf-8"))
    best_c, best_s = picked[0]
    if prev and "analog" in prev:
        prev_start_mi = prev["analog"].get("start_mi")
        cur_for_prev = next(((c, s) for c, s in cands if idxs[s] == prev_start_mi), None)
        if cur_for_prev and best_c - cur_for_prev[0] < HYST / 100.0:
            best_c, best_s = cur_for_prev  # 유지
            print(f"히스테리시스: 이전 챔피언 유지 ({mi_label(prev_start_mi)})")

    s = best_s
    analog_end = s + W - 1
    outcome_12m = (prices[analog_end + GHOST] / prices[analog_end] - 1) * 100

    # 겹침 차트 시계열 (전부 rebased 100 기준: 현재창 시작 & 아날로그창 시작 각각 100)
    series_now = rebased(prices[-W:])
    series_analog = rebased(prices[s:s + W])
    # 아날로그 끝점 포함 → 이후 경로. rebased series_analog 끝값에 이어붙게 재정규화(ghost[0]=analog 끝값)
    ghost_raw = prices[s + W - 1: s + W - 1 + GHOST + 1]
    series_ghost = [round(series_analog[-1] * (v / ghost_raw[0]), 2) for v in ghost_raw]

    # 최근 추적률 (최근 RECENT개월 형태 근접도)
    tr = corr(zscore(series_now[-RECENT:]), zscore(series_analog[-RECENT:]))
    tracking_pct = max(0, round(tr * 100))

    # 결과 분포
    ups = downs = 0
    alts = []
    for c, si in picked:
        ae = si + W - 1
        r12 = (prices[ae + GHOST] / prices[ae] - 1) * 100
        if r12 >= 0: ups += 1
        else: downs += 1
        alts.append({
            "start_label": mi_label(idxs[si]), "end_label": mi_label(idxs[ae]),
            "similarity": round(c * 100, 1), "outcome_12m": round(r12, 1),
            "label": outcome_label(r12),
        })

    dday = dday_on_ghost(prices[s + W - 1: s + W - 1 + GHOST + 1])

    out = {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_months": W,
        "analog": {
            "start_mi": idxs[s], "start_label": mi_label(idxs[s]), "end_label": mi_label(idxs[analog_end]),
            "similarity": round(best_c * 100, 1),
            "outcome_12m": round(outcome_12m, 1), "outcome_label": outcome_label(outcome_12m),
        },
        "tracking": {"pct": tracking_pct},
        "dday": dday,
        "distribution": {"total": len(picked), "up": ups, "down": downs},
        "series_now": series_now,
        "series_analog": series_analog,
        "series_ghost": series_ghost,
        "alternatives": alts,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    a = out["analog"]
    print(f"챔피언: {a['start_label']}~{a['end_label']} 유사도 {a['similarity']}% → 이후12M {a['outcome_12m']:+}% ({a['outcome_label']})")
    print(f"추적률 {tracking_pct}% / 분포 상승{ups}·하락{downs} / D-day {dday}")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
