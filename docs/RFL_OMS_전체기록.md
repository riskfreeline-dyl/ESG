# RFL OMS 전체 기록 — WinEdge 분석부터 1~4단계 구현과 전체 소스코드까지

- 작성일: 2026-11-27
- 저장소: `riskfreeline-dyl/ESG`, 브랜치 `claude/festive-newton-9f091h`
- 상태: 1~4단계 완료, 테스트 73개 통과, 브라우저에서 전 탭·전 역할 동작 확인, 웹 배포 https://rfl-oms.netlify.app
- 성격: **시뮬레이션 프로토타입**입니다. 시세와 체결은 모두 가상이며 실제 거래소·증권사와 연결되어 있지 않습니다.

## 목차

1. 배경과 진행 원칙
2. WinEdge 공개 페이지 분석
3. WinEdge 기능 ↔ RFL OMS 구현 대응표
4. 단계별 구현 내역 (1~4단계)
5. 시스템 구조
6. 실행·테스트 방법
7. 가정값, 한계, 다음 단계
8. 작업 이력 (커밋)
9. 부록: 전체 소스코드

---

## 1. 배경과 진행 원칙

**최초 요청:** 위니웨이(Winway)의 WinEdge 제품 페이지(https://winway.co.kr/product-winedge.html)를 리버스 엔지니어링해 소스코드를 확보하고, 100% 동일한 플랫폼을 RFL 솔루션으로 제작.

**결정:** 리버스 엔지니어링으로 비공개 소스코드를 확보하는 것과 화면·문구·구조를 그대로 복제하는 것은 진행하지 않았습니다. 상용 소프트웨어의 저작권·영업비밀 침해, 이용약관 위반, 부정경쟁 소지가 있어 RFL에 법적 위험이 되기 때문입니다.

**대신 진행한 방식:**

1. 공개 제품 페이지에서 **기능 목록만** 파악 (기능 아이디어 자체는 보호 대상이 아님)
2. 그 기능 범위를 바탕으로 RFL 요구사항을 정의
3. UI·데이터 모델·코드를 **처음부터 독자적으로** 설계·구현
4. 실제 거래 연동 없이 동작을 검증할 수 있도록 시장·체결은 시뮬레이션으로 구성

**진행 순서:** 공개 페이지 분석 → 1단계(OMS·사전 리스크) → 2단계(바스켓·알고 주문) → 3단계(지수 차익거래·리스크 대시보드) → 4단계(DB 저장·로그인과 권한·거래비용과 헤지 증거금 상계). 기술 스택은 사용자 선택에 따라 Python + Streamlit.

---

## 2. WinEdge 공개 페이지 분석

공개 제품 페이지에 적힌 내용만 요약했습니다. 페이지에 없는 내용은 추측하지 않았습니다. (분석 시 세션 네트워크 허용 목록에 `winway.co.kr`, `www.winway.co.kr`을 추가해 접속)

### 2.1 개요

- **분류:** 거래 시스템. 전자거래 플랫폼 겸 OMS(주문관리시스템)
- **대상:** 전문 트레이더와 기관 (증권사, 운용사, 마켓메이커, 유동성 공급자)
- **자산군:** 주식, 선물, 옵션, 채권, 외환, 금(KRX 금 포함)

### 2.2 기능 목록

1. **리스크 관리**
   - 포지션·노출 실시간 모니터링
   - 주문 전 리스크 점검과 증거금 산출
   - 사용자가 정하는 알림과 한도
   - 컴플라이언스 점검
2. **주문 라이프사이클 관리 (OMS)**
   - 주문 생성 → 검증 → 보강 → 라우팅 → 정정·취소 → 체결 처리를 하나의 워크플로우로
   - 전략과 운영 요건에 맞춘 워크플로우 구성
3. **바스켓 주문**
   - 엑셀 업로드·템플릿으로 구성, 종목 수·비중·목표 명목금액 기준 설정
   - 자주 쓰는 구성 저장·재호출
   - 원클릭으로 바스켓 전체 동시 실행
   - 체결률·잔량·평균 체결가 요약, 바스켓별 실시간 체결 상태·시세·손익
   - 실행 중 정정·취소, 실패 주문 자동 재전송 또는 즉시 알림, 부분 체결·실패 주문 복원 후 재실행
4. **차익거래**
   - 현물/선물 차익거래 (주식, 통화, 채권, 금)
   - 바스켓 차익거래 (지수선물 또는 ETF ↔ 기초 포트폴리오)
   - 페어 트레이딩, 실시간 모니터링·자동 실행·리스크 통제
5. **알고리즘 주문:** TWAP, VWAP, POV, 고객별 맞춤 알고리즘
6. **마켓메이킹·유동성 공급:** 외환, 국고채, KRX 금 호가 제시와 유동성 관리
7. **아키텍처 (페이지 주장):** 마이크로초 단위 tick-to-trade 지연, 락프리 인메모리 구조, C 코드, 초당 수백만 메시지, 수평 확장, 높은 가동률, 기존 시스템·데이터 피드·API 연동

### 2.3 페이지에 없는 정보

가격, 배포 방식(클라우드·구축형), 연동 증권사·거래소 목록, UI 화면, 상세 기술 사양은 공개되어 있지 않습니다.

### 2.4 같은 회사의 관련 제품 (페이지 표기)

스텔스윈, FX윈, 윈GDTS, 윈KDTS, 윈겟츠, 윈핏츠, 윈CFD, 윈골드

---

## 3. WinEdge 기능 ↔ RFL OMS 구현 대응표

| WinEdge 공개 기능 | RFL OMS 구현 | 단계 | 상태 |
|---|---|---|---|
| 포지션·노출 실시간 모니터링 | 포지션·손익 탭, 한도 사용률, 자산군별 노출 차트 | 1·3 | 구현 |
| 사전 리스크 점검·증거금 산출 | 10개 항목 사전 점검, 최악 노출 기준 증거금, 지수선물↔구성종목 헤지 상계 | 1·4 | 구현 |
| 맞춤 알림·한도 | 한도 설정, 경고/위험 알림, 가격 알림 | 1 | 구현 |
| 컴플라이언스 점검 | 거래 제한 종목, 킬 스위치, 행위자가 기록되는 감사 로그, 역할별 권한·업무 분리 | 1·4 | 일부 (규정 엔진은 없음) |
| 주문 라이프사이클 (생성~체결) | 생성→검증→보강→라우팅→체결, 정정·취소, IOC | 1 | 구현 |
| 워크플로우 구성 | 전략 태그, 실행 방식 선택 | 1·2 | 일부 |
| 바스켓 구성 (엑셀·템플릿·비중·명목) | 표 편집, 엑셀/CSV 업로드, 수량/비중 방식, 템플릿 | 2 | 구현 |
| 원클릭 실행·체결 요약·실시간 손익 | 원클릭 실행, 바스켓 모니터 | 2 | 구현 |
| 실행 중 정정·취소, 자동 재전송, 재실행 | 일괄 정정·취소, 자동 재전송(최대 3회), 잔량 재실행 | 2 | 구현 |
| TWAP / VWAP / POV | 알고 엔진, 스케줄 차트, 슬리피지 | 2 | 구현 |
| 맞춤 알고리즘 | — | — | 미구현 |
| 지수선물 ↔ 바스켓 차익거래 | 차익 모니터, 수동·자동 진입/청산, 헤지 잔차 | 3 | 구현 |
| 통화·채권·금 현물/선물 차익, ETF 차익, 페어 트레이딩 | — | — | 미구현 |
| 마켓메이킹·유동성 공급 | — | — | 미구현 |
| 옵션 자산군 | — | — | 미구현 |
| 마이크로초 저지연 C 엔진 | 해당 없음 (Python 시뮬레이션) | — | 범위 밖 |
| 외부 시스템·데이터 피드 연동 | 엔진을 UI와 분리해 교체 가능한 구조 | — | 미구현 |

---

## 4. 단계별 구현 내역

### 4.1 1단계 — 모의 체결 OMS와 사전 리스크 점검

| 영역 | 내용 |
|---|---|
| 주문 라이프사이클 | 생성 → 형식 검증 → 사전 리스크 점검 → 보강(라우팅 대상·예상 명목·증거금) → 라우팅 → 부분/전량 체결, 정정·취소, IOC·시장가 잔량 자동 취소. 단계마다 시각과 함께 기록 |
| 주문 유형 | 지정가 / 시장가, 유효조건 DAY / IOC, 전략 태그 |
| 사전 리스크 점검 10항목 | 킬 스위치, 거래 제한 종목, 주문당 수량 한도, 주문당 명목 한도, 가격 괴리율, 종목별 포지션 한도, 총 노출 한도, 증거금, 일일 손실 한도 (+ 형식 검증: 종목·수량·호가단위) |
| 리스크 원칙 | 노출은 미체결 주문이 모두 체결되는 최악의 경우로 계산. 위험을 줄이는 주문(청산)은 한도 초과 상태에서도 허용. "사전 점검" 버튼으로 주문 없이 결과만 미리보기 |
| 포지션·손익 | 평균단가 방식, 선물 계약승수 반영, 실현/미실현 손익, 포지션 방향 전환 처리 |
| 알림 | 한도 사용률 경고(기본 80%)·위험(100%), 단계 상승 시에만 발생(중복 방지), 주문 거부 알림, 사용자 가격 알림 |
| 거래 통제 | 킬 스위치: 미체결 전체 취소 + 신규 주문 차단 |
| 감사 | 주문별 이벤트 기록, 감사 로그·주문 내역 CSV 내보내기 |
| 시장 시뮬레이터 | 랜덤워크 시세, 5단계 호가, 틱 내 잔량 소진. 삼성전자, SK하이닉스, 코스피200 선물, 미국달러 선물, 3년 국채선물, KRX 금 |
| 화면 | 주문 입력, 주문 블로터, 포지션·손익, 리스크, 알림, 감사 로그 탭 + 사이드바 한도 설정·시장 진행 |

### 4.2 2단계 — 바스켓 주문과 알고리즘 주문

| 영역 | 내용 |
|---|---|
| 바스켓 구성 | 표 직접 입력·편집, 엑셀/CSV 업로드(양식 제공), 수량 방식 또는 비중(%) + 목표 명목금액 방식, 템플릿 저장·불러오기 |
| 실행 전 점검 | 종목별 수량·예상 명목·사전 리스크 점검 결과, 매수/매도 명목 합계 |
| 원클릭 실행 | 시장가, 지정가(상대호가 / 자기호가 ± n틱), TWAP, VWAP, POV 중 선택해 전 종목 동시 전송 |
| 바스켓 모니터 | 수량·금액 체결률(금액은 현재가 기준으로 가격 변동 효과 제거), 완료 종목, 체결 금액, 잔량, 종목별 평균체결가·평가손익·상태 |
| 실행 중 제어 | 미체결 전체 취소, 현재 호가로 일괄 정정, 잔량 재실행, 시장가 잔량 자동 재전송(최대 3회). 리스크 거부는 자동 재전송하지 않고 즉시 알림 |
| 알고리즘 | TWAP(시간 균등), VWAP(장중 U자형 거래량 비례), POV(직전 틱 시장 거래량의 일정 비율). 제한가, 일시정지·재개·취소 |
| 알고 리스크 | 시작 시 전체 수량으로 사전 점검, 아직 내지 않은 잔량도 노출·증거금에 포함, 자식 주문도 개별 점검, 거부 시 알고 중단 + 위험 알림, 킬 스위치 시 알고 취소 |
| 실행 품질 | 목표 스케줄 대비 누적 체결 차트, 도착가 대비·구간 시장 VWAP 대비 슬리피지(bp) |
| 시장 확장 | 주식 6종 추가(현대차, 기아, NAVER, KB금융, POSCO홀딩스, 셀트리온), 틱별 시장 거래량(1거래일 = 120틱) |

### 4.3 3단계 — 지수 차익거래와 리스크 대시보드

| 영역 | 내용 |
|---|---|
| 시뮬레이션 지수 | 주식 8종으로 만든 'RFL 시뮬 지수'. 제수 = 선물 승수(250,000)이므로 지수 1단위가 선물 1계약의 현물 복제 바스켓 |
| 선물 가격 | 보유비용 이론가 F* = S × (1 + (r − d) × T/365) 주변에서 평균회귀 괴리(표준편차 약 0.5pt). 주식은 시장 공통요인으로 상관 |
| 차익 모니터 | 지수·선물·이론가·괴리(pt, bp), 비용 차감 후 매도/매수차익 순수익, 괴리 추이와 진입선 차트, 진입·청산 표시 |
| 비용 모형 | 주식 수수료, 매도세, 선물 수수료, 슬리피지를 지수 포인트로 환산 (모두 조정 가능한 가정값) |
| 진입·청산 | 매도차익(선물 매도 + 현물 매수), 매수차익(선물 매수 + 현물 매도). 두 레그 모두 사전 점검 통과 시에만 전송, 한쪽 실패 시 '레그 불일치' 위험 알림 |
| 자동 차익 | 순수익이 진입 기준을 넘으면 자동 진입, 괴리가 청산 기준 안으로 돌아오면 자동 청산, 최대 동시 포지션 제한 |
| 포지션 | 포지션별 손익(비용 전), 선물·현물 명목과 헤지 잔차, 개별·전체 청산 |
| 리스크 대시보드 | 1일 VaR(과거 시뮬레이션·모수, 95/99%), 주가 방향 순노출, 남은 손실 여력, 손익 추이, 자산군별 매수/매도/순노출, 스트레스 테스트 7종, 상위 집중 포지션 |

### 4.4 4단계 — 사용 기반: DB 저장, 로그인·권한, 거래비용·헤지 증거금 상계

| 영역 | 내용 |
|---|---|
| DB 저장 | SQLite. 조회용 장부 테이블(users, auth_log, orders, fills, positions, audit, alerts)과 엔진 스냅샷(state)을 하나의 트랜잭션으로 저장. 새로고침·서버 재시작 후 알고·바스켓·차익·시장까지 그대로 이어서 동작 |
| 공유 장부 | 모든 브라우저 세션이 하나의 엔진·DB를 공유하고, 동시 수정은 잠금으로 직렬화. 화면을 그릴 때마다 변경분 저장(주문은 변경된 것만, 체결·감사·알림은 추가분만) |
| 로그인 | 비밀번호 PBKDF2-HMAC-SHA256(솔트, 20만 회) 해시 저장. 기본 계정·기본 비밀번호 없음(첫 실행 시 관리자 생성). 8자 이상·문자+숫자. 연속 5회 실패 시 15분 잠금. 로그인·실패·잠금·계정 변경 기록 |
| 역할·권한 | 트레이더: 주문 실행, 자기 주문·알고·바스켓만 정정·취소. 리스크 관리자: 한도 변경, 킬 스위치, 모든 주문 취소, 수수료 설정(주문 불가). 관리자: 사용자 관리, 수수료 설정, 킬 스위치, 시스템 초기화(주문 불가). 마지막 관리자는 해제 불가 |
| 행위자 기록 | 모든 주문·이벤트에 사용자 기록. 알고 자식 주문·바스켓 재전송은 시작한 사용자, 자동 차익은 켠 사용자 이름(자동)으로 기록. 한도·수수료 변경, 킬 스위치는 변경 전후 값과 함께 시스템 이벤트로 기록 |
| 거래비용 | 체결마다 수수료·세금 계산(주식 수수료 1bp, 매도세 15bp, 금 2bp, 선물 0.3bp — 모두 조정 가능한 가정값). 일일 손익·평가자산·손실 한도는 비용 차감 후 순손익 기준. 차익 포지션도 비용·순손익 표시 |
| 헤지 증거금 상계 | 지수선물과 지수 구성종목 순노출이 반대 방향이면 헤지된 금액만큼 선물 증거금을 감면(기본 70%). 미체결 주문이 헤지를 깰 수 있으면 상계를 인정하지 않는 보수적 계산. 리스크 관리자가 사용 여부·감면율 설정 |
| 관리 탭 | 사용자 추가·역할 변경·비활성화·비밀번호 재설정·잠금 해제, 역할별 권한표, 수수료 설정, DB 현황, 로그인 기록, 거래 데이터 초기화(사용자 유지, '초기화' 입력 확인) |

### 4.5 웹 배포 — Netlify (서버 없이 브라우저에서 실행)

| 항목 | 내용 |
|---|---|
| 주소 | https://rfl-oms.netlify.app |
| 방식 | stlite 1.12.2(내장 Streamlit 1.65, Pyodide)로 같은 `app.py`·엔진을 브라우저 안에서 실행. `tools/build_web.py`가 `web/`을 만들고 Netlify가 배포 시 자동 실행 |
| 저장 | 브라우저 IndexedDB(/mnt)에 SQLite 파일 저장 → 새로고침 후에도 유지. 접속자·브라우저마다 독립 장부 |
| 호환 처리 | 브라우저 Python에는 OpenSSL 기반 `pbkdf2_hmac`이 없어 같은 결과를 내는 순수 파이썬 PBKDF2 사용(테스트로 일치 검증), SQLite WAL 미지원 시 기본 모드 |
| 검증 | 실제 배포 주소에서 관리자 생성 → 사용자 추가 → 트레이더 주문·바스켓·차익 → 새로고침 후 데이터 유지 확인 |

---

## 5. 시스템 구조

```
app.py                Streamlit 메인 화면 (사이드바, 공통 지표, 탭 구성)
rfl_oms/              주문 처리 엔진 (Streamlit에 의존하지 않음)
  models.py           주문·체결·포지션·알림 모델
  market.py           시장 시뮬레이터 (시세, 호가, 거래량, 지수-선물 연결)
  risk.py             리스크 한도와 사전 점검
  engine.py           OMS 엔진 (라이프사이클, 체결, 손익, 알림, 틱 처리)
  algo.py             TWAP · VWAP · POV 실행 알고리즘
  basket.py           바스켓 구성·실행·모니터링
  index.py            시뮬레이션 지수와 선물 이론가
  arbitrage.py        지수 차익거래 엔진
  analytics.py        VaR, 스트레스 테스트, 노출 분해
  fees.py             거래비용 (수수료·세금)
  auth.py             역할·권한, 비밀번호 해시·정책
  storage.py          SQLite 저장소 (장부 테이블 + 엔진 스냅샷, 사용자·로그인 기록)
views/                화면 구성 요소 (로그인, 관리, 바스켓, 알고, 차익, 리스크, 공유 런타임, 공용 도우미)
tests/                단위 테스트 73개
tools/build_web.py    Netlify용 웹 버전(web/) 생성기
netlify.toml          Netlify 배포 설정
tools/build_record.py 이 기록 문서를 다시 만드는 스크립트
data/rfl_oms.db       실행 시 생기는 DB 파일 (저장소에는 올리지 않음)
```

**틱 처리 순서:** 시장 1틱 진행 → 미체결 주문 매칭 → 알고 엔진 → 바스켓 자동 재전송 → 차익 엔진 → 가격 알림 → 한도 알림 → 손익 기록

**화면 한 번 그릴 때:** 로그인 확인(DB에서 계정 재조회) → 공유 잠금 획득 → 행위자 지정 → 처리 → DB 저장 → 잠금 해제

**설계 원칙:** 엔진(`rfl_oms/`)과 화면(`app.py`, `views/`)을 분리해, 이후 API 서버나 실제 주문 게이트웨이(FIX, 증권사 API)로 옮길 때 시장·체결 계층만 교체하면 되도록 했습니다.

---

## 6. 실행·테스트 방법

```bash
pip install -r requirements.txt
streamlit run app.py          # 브라우저에서 http://localhost:8501
# DB 위치 변경: RFL_OMS_DB=/경로/rfl_oms.db streamlit run app.py

pip install pytest
python -m pytest -q           # 73 passed

python tools/build_record.py  # 이 기록 문서 다시 만들기
```

사용 흐름: 첫 실행 시 관리자 계정을 만들고, 관리 탭에서 트레이더·리스크 관리자 계정을 추가합니다. 사이드바에서 "1틱/10틱 진행" 또는 "자동 진행"으로 시장을 움직이며 각 탭에서 주문·바스켓·알고·차익을 실행합니다.

---

## 7. 가정값, 한계, 다음 단계

### 7.1 주요 가정값 (모두 시뮬레이션용, 화면에서 조정 가능)

- 계좌 자본 10억 원, 주문당 최대 1만 주·5억 원, 가격 괴리 10%, 종목별 포지션 10억 원, 총 노출 30억 원, 일일 손실 5천만 원, 경고 기준 80%
- 체결 비용(4단계): 주식 수수료 1bp, 주식 매도세 15bp, 금 현물 2bp, 선물 0.3bp (관리 탭에서 변경)
- 차익 진입 판단용 비용: 주식 수수료 편도 1bp, 주식 매도세 15bp, 선물 수수료 편도 0.3bp, 슬리피지 편도 2bp (실제 세율·수수료로 바꿔야 함)
- 헤지 증거금 상계: 지수 구성종목만 대상, 헤지된 선물 증거금 70% 감면
- 이론가: 무위험 금리 3.5%, 배당수익률 1.5%, 만기까지 30일
- 종목 시작 가격은 시뮬레이션 값이며 실제 시세가 아님

### 7.2 한계

- 엔진 스냅샷은 pickle 형식이라 이 프로그램이 만든 DB 파일만 사용해야 함. 엔진 구조가 바뀌면(STATE_VERSION) 이전 스냅샷은 복원하지 않고 새로 시작 (장부 테이블은 남음)
- 모든 사용자가 하나의 계좌 장부를 공유하고 요청을 직렬로 처리 → 소규모 팀용. 대규모 동시 사용은 웹 서비스 전환 필요
- 헤지 상계는 지수선물↔구성종목 한 쌍만, 바스켓과 지수의 구성 차이(베이시스 위험)는 반영하지 않음
- 매수차익의 현물 매도는 대차 가능 가정, 차익 진입 판단 비용은 실제 체결 비용과 별도 설정
- 실제 시세·주문 연동 없음. 시장 시뮬레이션 진행 버튼은 모든 역할이 사용 가능
- HTTPS·SSO·비밀번호 만료 등 운영 보안은 배포 단계에서 추가 필요
- 마이크로초급 저지연은 C/C++ 전용 엔진과 코로케이션 인프라가 필요해 이 구조의 범위 밖
- 실제 운용 전 금융투자업 인가, 전자금융 관련 의무, 거래소·증권사 연결 승인 등 법률·컴플라이언스 검토 필요

### 7.3 다음 단계 후보 (권장 순서)

1. (완료) 데이터베이스 저장, 로그인·권한, 증거금 상계·비용 반영
2. 증권사 Open API 모의투자 계좌로 실시간 시세·주문 연동
3. 마켓메이킹·유동성 공급, 페어 트레이딩, 통화·채권·금 차익, 옵션
4. 다중 사용자 웹 서비스(FastAPI + React) 전환, Docker 패키징·배포

---

## 8. 작업 이력 (커밋)

| 커밋 | 날짜 | 내용 |
|---|---|---|
| (이번) | 2026-11-27 | 4단계: DB 저장, 로그인·권한, 거래비용·헤지 증거금 상계 |
| adba50d | 2026-11-27 | 전체 기록 문서 추가 |
| 47d2713 | 2026-11-27 | 3단계: 지수 차익거래 모니터와 리스크 대시보드 |
| 533930c | 2026-11-26 | 2단계: 바스켓 주문과 TWAP/VWAP/POV 알고 |
| 8e019a9 | 2026-11-26 | 1단계: 모의 체결 OMS와 사전 리스크 점검 |
| 7b7e6ef | 2026-05-01 | (기존) 기본 Streamlit 앱 |
| 6798c4a | 2026-05-01 | (기존) requirements.txt |
| ad6e6b3 | 2026-05-01 | (기존) stockbasic 파일 |

---

## 9. 부록: 전체 소스코드

저장소에서 추적하는 모든 파일을 그대로 수록했습니다. 아래 내용만으로 프로젝트 전체를 다시 만들 수 있습니다.


### 수록 파일 목록

- `.gitignore` (9줄)
- `.netlify/state.json` (3줄)
- `README.md` (118줄)
- `app.py` (565줄)
- `netlify.toml` (8줄)
- `requirements.txt` (8줄)
- `rfl_oms/__init__.py` (27줄)
- `rfl_oms/algo.py` (253줄)
- `rfl_oms/analytics.py` (134줄)
- `rfl_oms/arbitrage.py` (311줄)
- `rfl_oms/auth.py` (123줄)
- `rfl_oms/basket.py` (387줄)
- `rfl_oms/engine.py` (483줄)
- `rfl_oms/fees.py` (28줄)
- `rfl_oms/index.py` (54줄)
- `rfl_oms/market.py` (201줄)
- `rfl_oms/models.py` (176줄)
- `rfl_oms/risk.py` (172줄)
- `rfl_oms/storage.py` (301줄)
- `run.sh` (8줄)
- `run_windows.bat` (7줄)
- `stockbasic` (1줄)
- `tests/test_engine.py` (180줄)
- `tests/test_phase2.py` (186줄)
- `tests/test_phase3.py` (155줄)
- `tests/test_phase4.py` (257줄)
- `tools/build_record.py` (65줄)
- `tools/build_web.py` (89줄)
- `views/__init__.py` (1줄)
- `views/admin_view.py` (145줄)
- `views/algo_view.py` (165줄)
- `views/arb_view.py` (201줄)
- `views/auth_view.py` (91줄)
- `views/basket_view.py` (214줄)
- `views/common.py` (59줄)
- `views/risk_view.py` (136줄)
- `views/runtime.py` (52줄)

### `.gitignore`

```
__pycache__/
*.pyc
.pytest_cache/
.streamlit/secrets.toml
data/
*.db
*.db-wal
*.db-shm
web/
```

### `.netlify/state.json`

```
{
  "siteId": "4d837020-690e-4a49-819b-7d02c2920245"
}
```

### `README.md`

````markdown
# RFL OMS — 1~4단계 (모의 체결)

기관·전문 트레이더용 주문관리시스템(OMS) 프로토타입입니다.
**시세와 체결은 모두 시뮬레이션**이며 실제 거래소나 증권사와 연결되지 않습니다.

## 실행

```bash
./run.sh                 # macOS / Linux (가상환경 생성 + 설치 + 실행)
run_windows.bat          # Windows (더블클릭)
# 또는 직접: pip install -r requirements.txt && streamlit run app.py
```

- 첫 실행 시 **관리자 계정을 직접 만듭니다** (기본 계정·기본 비밀번호 없음). 이후 관리 탭에서 트레이더·리스크 관리자 계정을 추가하세요.
- 상태는 SQLite `data/rfl_oms.db`에 저장되어 새로고침·재시작 후에도 유지됩니다. 위치 변경: `RFL_OMS_DB=/경로/파일.db streamlit run app.py`
- 테스트: `pip install pytest && python -m pytest -q`
- 전체 기록 문서 재생성: `python tools/build_record.py`

## 웹 버전 (설치 없이 브라우저에서 바로 사용)

- 주소: **https://rfl-oms.netlify.app**
- stlite(브라우저 안에서 Python·Streamlit을 실행하는 기술)로 같은 코드를 서버 없이 실행합니다. 처음 접속 시 준비에 20초~1분 걸립니다.
- 데이터는 **접속한 브라우저 안(IndexedDB)에만** 저장됩니다. 사람마다·브라우저마다 별도 장부이며 서로 공유되지 않습니다. 브라우저 데이터를 지우면 함께 지워집니다.
- 처음 접속하면 그 브라우저용 관리자 계정을 만듭니다(다른 사람의 데이터에는 접근할 수 없음).
- 다시 만들기: `python tools/build_web.py` → `web/` 폴더 생성(Netlify가 배포 때 자동 실행, 설정은 `netlify.toml`)
- 팀이 하나의 장부를 함께 쓰려면 서버 버전(`streamlit run app.py`)을 서버에 띄워야 합니다.

## 1단계 범위

| 영역 | 내용 |
|---|---|
| 주문 라이프사이클 | 생성 → 형식 검증 → 사전 리스크 점검 → 보강(라우팅 대상·예상 명목·증거금) → 라우팅 → 부분/전량 체결, 정정·취소, IOC·시장가 잔량 자동 취소 |
| 주문 유형 | 지정가 / 시장가, 유효조건 DAY / IOC, 전략 태그 |
| 사전 리스크 점검 | 킬 스위치, 거래 제한 종목, 주문당 수량·명목 한도, 가격 괴리율, 종목별 포지션 한도, 총 노출 한도, 증거금, 일일 손실 한도 |
| 리스크 원칙 | 노출은 미체결 주문이 모두 체결되는 최악의 경우로 계산. 위험을 줄이는 주문(청산)은 한도 초과 상태에서도 허용 |
| 포지션·손익 | 평균단가 방식, 선물 계약승수 반영, 실현/미실현 손익, 포지션 방향 전환 처리 |
| 알림 | 한도 사용률 경고(기본 80%)·위험(100%) 알림(단계 상승 시에만 발생), 주문 거부 알림, 사용자 가격 알림 |
| 감사 | 주문별 이벤트 기록, 감사 로그·주문 내역 CSV 내보내기 |
| 시장 시뮬레이터 | 주식 8종, 코스피200·달러·3년 국채 선물, 금 현물. 랜덤워크 시세, 5단계 호가, 틱 내 잔량 소진, 장중 U자형 거래량(1거래일 = 120틱) |

## 2단계 범위

| 영역 | 내용 |
|---|---|
| 바스켓 구성 | 표에서 직접 입력·편집, 엑셀/CSV 업로드(양식 제공), 수량 방식 또는 비중(%) + 목표 명목금액 방식, 템플릿 저장·불러오기 |
| 실행 전 점검 | 종목별 수량·예상 명목·사전 리스크 점검 결과, 매수/매도 명목 합계 |
| 원클릭 실행 | 시장가, 지정가(상대호가 / 자기호가 ± n틱), TWAP, VWAP, POV 중 선택해 전 종목 동시 전송 |
| 바스켓 모니터 | 수량·금액 체결률, 완료 종목, 체결 금액, 잔량, 종목별 평균체결가·평가손익·상태 |
| 실행 중 제어 | 미체결 전체 취소, 현재 호가로 일괄 정정, 잔량 재실행, 시장가 잔량 자동 재전송(최대 3회). 리스크 거부는 자동 재전송하지 않고 즉시 알림 |
| 알고리즘 주문 | TWAP(시간 균등), VWAP(거래량 패턴 비례), POV(시장 거래량의 일정 비율). 제한가, 일시정지·재개·취소 |
| 알고 리스크 | 시작 시 전체 수량으로 사전 점검, 아직 내지 않은 잔량도 노출·증거금에 포함, 자식 주문도 개별 점검, 거부 시 알고 중단 + 위험 알림 |
| 실행 품질 | 목표 스케줄 대비 누적 체결 차트, 도착가 대비·구간 시장 VWAP 대비 슬리피지(bp) |

## 3단계 범위

| 영역 | 내용 |
|---|---|
| 시뮬레이션 지수 | 주식 8종으로 만든 'RFL 시뮬 지수'. 제수 = 선물 승수이므로 지수 1단위가 곧 선물 1계약의 현물 복제 바스켓 |
| 선물 가격 | 지수선물이 보유비용 이론가 F* = S × (1 + (r − d) × T/365) 주변에서 평균회귀 괴리를 두고 움직임. 주식은 시장 공통요인으로 상관됨 |
| 차익 모니터 | 지수·선물·이론가·괴리(pt, bp), 비용 차감 후 매도/매수차익 순수익, 괴리 추이와 진입선 차트, 진입·청산 표시 |
| 비용 모형 | 주식 수수료, 매도세, 선물 수수료, 슬리피지를 지수 포인트로 환산 (모두 조정 가능한 가정값) |
| 진입·청산 | 매도차익(선물 매도 + 현물 매수), 매수차익(선물 매수 + 현물 매도). 두 레그 모두 사전 점검 통과 시에만 전송, 한쪽 실패 시 '레그 불일치' 위험 알림 |
| 자동 차익 | 순수익이 진입 기준을 넘으면 자동 진입, 괴리가 청산 기준 안으로 돌아오면 자동 청산, 최대 동시 포지션 제한 |
| 포지션 | 포지션별 손익(비용 전), 선물·현물 명목과 헤지 잔차, 개별·전체 청산 |
| 리스크 대시보드 | 1일 VaR(과거 시뮬레이션·모수, 95/99%), 주가 방향 순노출, 남은 손실 여력, 손익 추이, 자산군별 매수/매도/순노출, 스트레스 테스트 7종, 상위 집중 포지션 |

## 4단계 범위 (사용 기반)

| 영역 | 내용 |
|---|---|
| DB 저장 | 주문·체결·포지션·감사로그·알림·사용자·로그인 기록을 SQLite 테이블로 저장. 엔진 스냅샷도 함께 저장해 알고·바스켓·차익·시장까지 그대로 복원 |
| 공유 장부 | 모든 사용자가 하나의 계좌 장부를 공유, 동시 수정은 잠금으로 직렬화 |
| 로그인 | PBKDF2 해시(솔트, 20만 회), 8자 이상·문자+숫자, 5회 실패 시 15분 잠금, 로그인 기록 |
| 역할 | 트레이더(주문, 자기 주문 정정·취소) / 리스크 관리자(한도, 킬 스위치, 모든 주문 취소, 수수료) / 관리자(사용자 관리, 수수료, 킬 스위치, 초기화). 트레이더 외에는 주문 불가 |
| 감사 | 모든 주문·이벤트에 행위자 기록, 한도·수수료 변경과 킬 스위치는 전후 값과 함께 기록 |
| 거래비용 | 체결마다 수수료·세금 계산, 일일 손익·손실 한도는 비용 차감 후 순손익 기준 |
| 헤지 증거금 상계 | 지수선물 ↔ 구성종목 반대 포지션의 선물 증거금 감면(기본 70%), 미체결이 헤지를 깨면 미인정 |

| 권한 | 트레이더 | 리스크 관리자 | 관리자 |
|---|:-:|:-:|:-:|
| 조회 | ✅ | ✅ | ✅ |
| 주문 실행 (일반·바스켓·알고·차익) | ✅ | | |
| 자기 주문 정정·취소 | ✅ | | |
| 모든 주문 취소 | | ✅ | |
| 리스크 한도·헤지 상계 설정 | | ✅ | |
| 킬 스위치 | | ✅ | ✅ |
| 수수료 설정 | | ✅ | ✅ |
| 사용자 관리 | | | ✅ |
| 거래 데이터 초기화 | | | ✅ |

## 구조

```
app.py               Streamlit 화면 (UI만 담당)
rfl_oms/models.py    주문·체결·포지션·알림 모델
rfl_oms/market.py    시장 시뮬레이터
rfl_oms/risk.py      리스크 한도와 사전 점검
rfl_oms/engine.py    OMS 엔진 (라이프사이클, 체결, 손익, 알림)
rfl_oms/algo.py      TWAP · VWAP · POV 실행 알고리즘
rfl_oms/basket.py    바스켓 구성·실행·모니터링
rfl_oms/index.py     시뮬레이션 지수와 선물 이론가
rfl_oms/arbitrage.py 지수 차익거래 엔진
rfl_oms/analytics.py VaR, 스트레스 테스트, 노출 분해
rfl_oms/fees.py      거래비용
rfl_oms/auth.py      역할·권한, 비밀번호 해시
rfl_oms/storage.py   SQLite 저장소
views/               로그인·관리·바스켓·알고·차익·리스크 화면, 공유 런타임
tools/               기록 문서 생성기
tests/               엔진 단위 테스트
```

엔진은 Streamlit에 의존하지 않으므로, 2단계 이후 API 서버나 실제 주문 게이트웨이(FIX 등)로 옮길 수 있습니다.

## 한계와 다음 단계 후보

- 엔진 스냅샷은 pickle 형식 → 이 프로그램이 만든 DB 파일만 사용할 것
- 하나의 공유 장부를 직렬 처리하는 소규모 팀용 구조, HTTPS·SSO 등 운영 보안은 배포 단계에서 추가
- 실제 시세·주문 연동(FIX, 증권사 API)은 엔진(`rfl_oms/`)을 그대로 두고 시장·체결 계층만 교체하는 구조
````

### `app.py`

```python
"""RFL OMS — Streamlit 화면.

실행: streamlit run app.py
모든 시세와 체결은 시뮬레이션이며 실제 시장과 연결되어 있지 않습니다.
상태는 SQLite(기본 data/rfl_oms.db, 환경변수 RFL_OMS_DB로 변경)에 저장되어 새로고침·재시작 후에도 유지됩니다.
"""

from __future__ import annotations

import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, AlertLevel, OrderType, RiskLimits, Side, TimeInForce
from rfl_oms.auth import Perm
from views.admin_view import admin_view
from views.algo_view import algo_view
from views.arb_view import arb_view
from views.auth_view import account_sidebar, require_login
from views.basket_view import basket_view
from views.common import NUM, can, can_manage, current_user, fmt_price, krw, need
from views.risk_view import risk_view
from views.runtime import engine, runtime

st.set_page_config(page_title="RFL OMS", page_icon="📈", layout="wide")

LEVEL_ICON = {AlertLevel.INFO: "🔵", AlertLevel.WARNING: "🟠", AlertLevel.CRITICAL: "🔴"}


# ============================== 사이드바 ==============================
def sidebar(oms: OMS) -> tuple[bool, float]:
    st.sidebar.title("RFL OMS")
    st.sidebar.caption("모의 체결 환경")
    account_sidebar(current_user())

    st.sidebar.subheader("시장 시뮬레이션")
    c1, c2 = st.sidebar.columns(2)
    if c1.button("1틱 진행", width="stretch"):
        oms.step(1)
    if c2.button("10틱 진행", width="stretch"):
        oms.step(10)
    auto = st.sidebar.toggle("자동 진행", value=False)
    interval = st.sidebar.slider("진행 간격(초)", 0.5, 5.0, 1.0, 0.5, disabled=not auto)
    st.sidebar.caption(f"현재 틱: {oms.market.tick_no:,}")

    st.sidebar.subheader("거래 통제")
    kill = st.sidebar.toggle(
        "킬 스위치 (거래 중지)",
        value=oms.kill_switch,
        disabled=not can(Perm.KILL_SWITCH),
        help="켜면 미체결 주문을 모두 취소하고 신규 주문을 막습니다." if can(Perm.KILL_SWITCH) else need(Perm.KILL_SWITCH),
    )
    if kill != oms.kill_switch and can(Perm.KILL_SWITCH):
        oms.set_kill_switch(kill)
    if st.sidebar.button(
        "미체결·알고 전체 취소", width="stretch", disabled=not can(Perm.CANCEL_ANY), help=None if can(Perm.CANCEL_ANY) else need(Perm.CANCEL_ANY)
    ):
        a = oms.algos.cancel_all("전체 취소")
        n = oms.cancel_all()
        st.sidebar.success(f"주문 {n}건 · 알고 {a}건 취소")

    st.sidebar.subheader("리스크 한도")
    lim = oms.limits
    if not can(Perm.SET_LIMITS):
        st.sidebar.caption(need(Perm.SET_LIMITS) + ". 현재 한도는 리스크 탭에서 볼 수 있습니다.")
        return auto, interval
    with st.sidebar.form("limits"):
        capital = st.number_input("계좌 자본(원)", min_value=0.0, value=float(lim.capital), step=1e8, format="%.0f")
        max_qty = st.number_input("주문당 최대 수량", min_value=1, value=int(lim.max_order_qty), step=100)
        max_notional = st.number_input(
            "주문당 최대 명목(원)", min_value=0.0, value=float(lim.max_order_notional), step=1e7, format="%.0f"
        )
        band = st.number_input("가격 괴리 허용(%)", min_value=0.1, value=float(lim.price_band_pct), step=0.5)
        max_pos = st.number_input(
            "종목별 포지션 한도(원)", min_value=0.0, value=float(lim.max_position_notional), step=1e8, format="%.0f"
        )
        max_gross = st.number_input(
            "총 노출 한도(원)", min_value=0.0, value=float(lim.max_gross_exposure), step=1e8, format="%.0f"
        )
        max_loss = st.number_input(
            "일일 손실 한도(원)", min_value=0.0, value=float(lim.max_daily_loss), step=1e6, format="%.0f"
        )
        warn = st.slider("경고 알림 기준(한도 대비)", 0.5, 0.99, float(lim.warn_ratio), 0.01)
        restricted = st.multiselect(
            "거래 제한 종목",
            options=list(oms.instruments),
            default=sorted(lim.restricted_symbols),
            format_func=lambda s: f"{s} {oms.instruments[s].name}",
        )
        offset_on = st.checkbox("헤지 증거금 상계 (지수선물 ↔ 구성종목)", value=lim.margin_offset_enabled)
        offset_pct = st.slider("헤지된 선물 증거금 감면율(%)", 0, 100, int(lim.margin_offset_pct), 5)
        if st.form_submit_button("한도 적용", width="stretch"):
            oms.set_limits(RiskLimits(
                capital=capital,
                max_order_qty=int(max_qty),
                max_order_notional=max_notional,
                price_band_pct=band,
                max_position_notional=max_pos,
                max_gross_exposure=max_gross,
                max_daily_loss=max_loss,
                warn_ratio=warn,
                restricted_symbols=frozenset(restricted),
                margin_offset_enabled=offset_on,
                margin_offset_pct=float(offset_pct),
            ))
            st.success("한도를 적용했습니다")
    return auto, interval


# ============================== 본문 ==============================
def header_metrics(oms: OMS) -> None:
    pnl = oms.daily_pnl()
    exp = oms.exposure()
    cols = st.columns(6)
    cols[0].metric("평가자산", krw(oms.equity()))
    cols[1].metric(
        "일일 순손익", krw(pnl), delta=f"{pnl / oms.limits.capital:.2%}" if oms.limits.capital else None,
        help="실현 + 미실현 − 수수료·세금",
    )
    cols[2].metric("수수료·세금", krw(oms.total_fees()))
    mb = oms.margin_breakdown()
    cols[3].metric(
        "순증거금(체결 기준)", krw(mb["순증거금"]),
        help=f"상계 전 {mb['상계 전']:,.0f} − 헤지 상계 {mb['헤지 상계']:,.0f}",
    )
    cols[4].metric("총 노출(미체결 포함)", krw(exp.gross))
    n_algos = sum(1 for a in oms.algos.algos.values() if a.status.is_active)
    cols[5].metric("미체결 · 실행중 알고", f"{len(oms.open_orders())} · {n_algos}")
    n_alerts = sum(1 for a in oms.alerts if a.level is not AlertLevel.INFO)
    if n_alerts:
        st.caption(f"경고·위험 알림 {n_alerts}건 — 알림 탭에서 확인하세요")
    if oms.kill_switch:
        st.error("킬 스위치가 켜져 있습니다. 신규 주문이 차단됩니다.", icon="⛔")


def market_watch(oms: OMS) -> None:
    rows = []
    for s, inst in oms.instruments.items():
        q = oms.market.quote(s)
        rows.append(
            {
                "종목코드": s,
                "종목명": inst.name,
                "자산군": inst.asset_class,
                "매수호가": q.bid,
                "매도호가": q.ask,
                "기준가": q.mid,
                "등락률(%)": round(q.change_pct, 2),
                "승수": inst.multiplier,
                "증거금률": inst.margin_rate,
                "보유": oms.positions[s].qty,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            **{k: NUM for k in ["매수호가", "매도호가", "기준가", "승수", "보유"]},
            "증거금률": st.column_config.NumberColumn(format="percent"),
        },
    )


def price_chart(oms: OMS, symbol: str) -> None:
    hist = oms.market.history[symbol]
    df = pd.DataFrame(hist, columns=["tick", "price"])
    fig = go.Figure(go.Scatter(x=df["tick"], y=df["price"], mode="lines", line=dict(width=1.6)))
    for o in oms.open_orders():
        if o.symbol == symbol and o.limit_price is not None:
            fig.add_hline(
                y=o.limit_price,
                line_dash="dot",
                line_color="#2e7d32" if o.side is Side.BUY else "#c62828",
                annotation_text=f"{o.order_id} {o.side.value} {o.leaves_qty:,}",
            )
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="틱", yaxis_title=None)
    st.plotly_chart(fig, width="stretch")


def order_book(oms: OMS, symbol: str) -> None:
    b = oms.market.book(symbol)
    asks = list(reversed(b["asks"]))
    rows = [{"매도잔량": f"{v:,}", "가격": fmt_price(oms, symbol, p), "매수잔량": ""} for p, v in asks]
    rows += [{"매도잔량": "", "가격": fmt_price(oms, symbol, p), "매수잔량": f"{v:,}"} for p, v in b["bids"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=388)


def show_checks(checks) -> None:
    df = pd.DataFrame(
        [
            {
                "결과": "✅" if c.passed else "❌",
                "점검 항목": c.name,
                "내용": c.detail,
                "사용률": min(c.usage, 9.99) if c.usage is not None else None,
            }
            for c in checks
        ]
    )
    st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        column_config={"사용률": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")},
    )


def order_entry(oms: OMS) -> None:
    left, mid, right = st.columns([1.1, 1.6, 1.0])
    with left:
        symbol = st.selectbox(
            "종목",
            list(oms.instruments),
            format_func=lambda s: f"{s} · {oms.instruments[s].name}",
            key="entry_symbol",
        )
        inst = oms.instruments[symbol]
        q = oms.market.quote(symbol)
        with st.form("order_form"):
            side = st.radio("구분", [Side.BUY, Side.SELL], format_func=lambda x: x.value, horizontal=True)
            otype = st.radio("유형", [OrderType.LIMIT, OrderType.MARKET], format_func=lambda x: x.value, horizontal=True)
            qty = st.number_input("수량", min_value=1, value=10, step=1)
            price = st.number_input(
                f"지정가 (호가단위 {inst.tick_size:g})",
                min_value=float(inst.tick_size),
                value=float(q.bid),
                step=float(inst.tick_size),
                format=f"%.{inst.price_decimals}f",
                key=f"px_{symbol}",
            )
            tif = st.radio("유효조건", [TimeInForce.DAY, TimeInForce.IOC], format_func=lambda x: x.value, horizontal=True)
            tag = st.text_input("전략 태그 (선택)", "")
            b1, b2 = st.columns(2)
            do_preview = b1.form_submit_button("사전 점검", width="stretch")
            do_submit = b2.form_submit_button(
                "주문 제출", type="primary", width="stretch", disabled=not can(Perm.TRADE),
                help=None if can(Perm.TRADE) else need(Perm.TRADE),
            )

        limit_px = inst.round_to_tick(price) if otype is OrderType.LIMIT else None
        if do_preview:
            st.session_state.last_checks = ("미리보기", oms.preview(symbol, side, otype, int(qty), limit_px, tif))
        if do_submit and can(Perm.TRADE):
            checks = oms.preview(symbol, side, otype, int(qty), limit_px, tif)
            order = oms.submit(symbol, side, otype, int(qty), limit_px, tif, strategy_tag=tag)
            st.session_state.last_checks = (f"{order.order_id} → {order.status.value}", checks)
            if order.reject_reason:
                st.error(f"{order.order_id} 거부: {order.reject_reason}")
            else:
                st.success(
                    f"{order.order_id} {order.status.value} · 체결 {order.filled_qty:,}/{order.qty:,}"
                    + (f" @ {order.avg_fill_price:,.4g}" if order.filled_qty else "")
                )
    with mid:
        st.markdown(f"**{inst.name}** 시세")
        price_chart(oms, symbol)
        if "last_checks" in st.session_state:
            title, checks = st.session_state.last_checks
            if checks:
                st.markdown(f"**사전 리스크 점검** · {title}")
                show_checks(checks)
    with right:
        st.markdown("**호가 (5단계)**")
        order_book(oms, symbol)


def orders_frame(oms: OMS, orders) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "주문번호": o.order_id,
                "시각": o.created_at.strftime("%H:%M:%S"),
                "종목": f"{o.symbol} {oms.instruments[o.symbol].name}",
                "구분": o.side.value,
                "유형": o.order_type.value,
                "조건": o.tif.value,
                "가격": fmt_price(oms, o.symbol, o.limit_price),
                "수량": o.qty,
                "체결": o.filled_qty,
                "잔량": o.leaves_qty,
                "평균체결가": round(o.avg_fill_price, 4) if o.filled_qty else None,
                "상태": o.status.value,
                "전략": o.strategy_tag,
                "주문자": o.trader,
                "거부 사유": o.reject_reason,
            }
            for o in reversed(list(orders))
        ]
    )


def blotter(oms: OMS) -> None:
    c1, c2 = st.columns([3, 1])
    status_filter = c1.segmented_control(
        "보기", ["전체", "미체결", "체결", "취소/거부"], default="전체", key="blotter_filter"
    )
    hide_children = c2.checkbox("알고 자식주문 숨기기", value=True, help="TWAP/VWAP/POV가 낸 분할 주문을 목록에서 감춥니다")
    orders = list(oms.orders.values())
    if hide_children:
        orders = [o for o in orders if o.strategy_tag not in oms.algos.algos]
    if status_filter == "미체결":
        orders = [o for o in orders if o.status.is_open]
    elif status_filter == "체결":
        orders = [o for o in orders if o.filled_qty > 0]
    elif status_filter == "취소/거부":
        orders = [o for o in orders if o.status.value in ("취소", "거부")]
    if orders:
        st.dataframe(
            orders_frame(oms, orders),
            hide_index=True,
            width="stretch",
            column_config={"수량": NUM, "체결": NUM, "잔량": NUM},
        )
    else:
        st.info("표시할 주문이 없습니다.")

    st.markdown("#### 정정 · 취소")
    open_orders = [o for o in oms.open_orders() if can_manage(o.trader)]
    if not open_orders:
        st.caption(
            "정정·취소할 수 있는 미체결 주문이 없습니다."
            + ("" if can(Perm.CANCEL_ANY) else " (트레이더는 자기 주문만, 리스크 관리자는 모든 주문을 취소할 수 있습니다)")
        )
    else:
        oid = st.selectbox(
            "대상 주문",
            [o.order_id for o in open_orders],
            format_func=lambda i: (
                f"{i} · {oms.orders[i].symbol} {oms.orders[i].side.value} "
                f"{oms.orders[i].leaves_qty:,} @ {fmt_price(oms, oms.orders[i].symbol, oms.orders[i].limit_price)}"
            ),
        )
        o = oms.orders[oid]
        inst = oms.instruments[o.symbol]
        c1, c2, c3, c4 = st.columns([1, 1, 0.6, 0.6])
        new_qty = c1.number_input("정정 수량(총)", min_value=o.filled_qty + 1, value=o.qty, step=1, key=f"aq_{oid}")
        new_px = c2.number_input(
            "정정 가격",
            min_value=float(inst.tick_size),
            value=float(o.limit_price or oms.market.mark(o.symbol)),
            step=float(inst.tick_size),
            format=f"%.{inst.price_decimals}f",
            key=f"ap_{oid}",
            disabled=o.order_type is not OrderType.LIMIT,
        )
        c3.write("")
        c4.write("")
        if c3.button(
            "정정", width="stretch", disabled=not (can(Perm.TRADE) and o.trader == current_user().username),
            help="정정은 주문을 낸 트레이더만 할 수 있습니다",
        ):
            ok, res = oms.amend(oid, int(new_qty), inst.round_to_tick(new_px))
            if ok:
                st.success(f"{oid} 정정 완료 ({o.status.value})")
            else:
                st.error(res if isinstance(res, str) else "정정 거부: " + "; ".join(c.name for c in res if not c.passed))
        if c4.button("취소", width="stretch"):
            oms.cancel(oid)
            st.success(f"{oid} 취소")

    st.markdown("#### 주문 라이프사이클")
    if oms.orders:
        sel = st.selectbox("주문 선택", list(reversed(oms.orders)), key="lifecycle_sel")
        events = oms.orders[sel].events
        st.dataframe(
            pd.DataFrame(
                [{"시각": e.ts.strftime("%H:%M:%S.%f")[:-3], "단계": e.event, "내용": e.detail, "행위자": e.actor} for e in events]
            ),
            hide_index=True,
            width="stretch",
        )


def positions_view(oms: OMS) -> None:
    rows = []
    for s, p in oms.positions.items():
        if p.qty == 0 and p.realized_pnl == 0 and p.fees == 0:
            continue
        inst = oms.instruments[s]
        mark = oms.market.mark(s)
        notional = abs(p.qty) * mark * inst.multiplier
        rows.append(
            {
                "종목": f"{s} {inst.name}",
                "수량": p.qty,
                "평균단가": round(p.avg_price, 4),
                "기준가": mark,
                "평가금액": notional,
                "미실현손익": round(oms.unrealized_pnl(s)),
                "실현손익": round(p.realized_pnl),
                "수수료·세금": round(p.fees),
                "순손익": round(p.realized_pnl + oms.unrealized_pnl(s) - p.fees),
                "증거금(상계 전)": round(notional * inst.margin_rate),
            }
        )
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config={k: NUM for k in ["수량", "평가금액", "미실현손익", "실현손익", "수수료·세금", "순손익", "증거금(상계 전)"]},
        )
    else:
        st.info("보유 포지션이 없습니다.")

    st.markdown("#### 체결 내역")
    if oms.fills:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "시각": f.ts.strftime("%H:%M:%S"),
                        "주문번호": f.order_id,
                        "종목": f.symbol,
                        "구분": f.side.value,
                        "수량": f.qty,
                        "가격": f.price,
                        "비용": round(f.fee),
                    }
                    for f in reversed(oms.fills)
                ]
            ),
            hide_index=True,
            width="stretch",
            column_config={"수량": NUM, "비용": NUM},
        )
    else:
        st.caption("체결 내역이 없습니다.")


def alerts_view(oms: OMS) -> None:
    c1, c2 = st.columns([2, 1])
    with c1:
        levels = st.multiselect(
            "등급", list(AlertLevel), default=list(AlertLevel), format_func=lambda x: f"{LEVEL_ICON[x]} {x.value}"
        )
        alerts = [a for a in reversed(oms.alerts) if a.level in levels]
        if alerts:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시각": a.ts.strftime("%H:%M:%S"),
                            "등급": f"{LEVEL_ICON[a.level]} {a.level.value}",
                            "분류": a.category,
                            "내용": a.message,
                        }
                        for a in alerts
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("알림이 없습니다.")
    with c2:
        st.markdown("**가격 알림 추가**")
        with st.form("price_rule"):
            sym = st.selectbox("종목", list(oms.instruments), format_func=lambda s: f"{s} {oms.instruments[s].name}")
            cond = st.radio("조건", ["이상", "이하"], horizontal=True)
            px = st.number_input("가격", min_value=0.0, value=float(oms.market.mark(sym)), format="%.4f")
            if st.form_submit_button("추가", width="stretch"):
                r = oms.add_price_rule(sym, cond, px)
                st.success(f"{r.rule_id} 등록")
        if oms.price_rules:
            st.dataframe(
                pd.DataFrame(
                    [
                        {"규칙": r.rule_id, "종목": r.symbol, "조건": f"{r.price:,} {r.condition}", "상태": "대기" if r.active else "발생"}
                        for r in oms.price_rules
                    ]
                ),
                hide_index=True,
                width="stretch",
            )


def audit_view(oms: OMS) -> None:
    df = pd.DataFrame(
        [
            {
                "시각": e.ts.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "주문번호": e.order_id,
                "단계": e.event,
                "내용": e.detail,
                "행위자": e.actor,
            }
            for e in reversed(oms.audit)
        ]
    )
    if df.empty:
        st.info("기록된 이벤트가 없습니다.")
        return
    c1, c2 = st.columns(2)
    actors = c1.multiselect("행위자", sorted(df["행위자"].unique()))
    sys_only = c2.checkbox("시스템 이벤트만 (한도·수수료 변경, 킬 스위치)")
    view = df
    if actors:
        view = view[view["행위자"].isin(actors)]
    if sys_only:
        view = view[view["주문번호"] == "-"]
    st.dataframe(view, hide_index=True, width="stretch")
    st.caption("감사 로그는 DB의 audit 테이블에 추가만 되며 화면에서 수정·삭제할 수 없습니다. 로그인 기록은 관리 탭에 있습니다.")
    c1, c2 = st.columns(2)
    c1.download_button(
        "감사 로그 CSV", df.to_csv(index=False).encode("utf-8-sig"), "rfl_oms_audit.csv", "text/csv", width="stretch"
    )
    c2.download_button(
        "주문 내역 CSV",
        orders_frame(oms, oms.orders.values()).to_csv(index=False).encode("utf-8-sig"),
        "rfl_oms_orders.csv",
        "text/csv",
        width="stretch",
    )


def main_view(auto: bool, interval: float) -> None:
    user = current_user()
    rt = runtime()
    with engine(user.username) as oms:
        if auto and time.time() - rt.last_auto_step >= interval * 0.9:
            oms.step(1)
            rt.last_auto_step = time.time()
        _main_body(oms)


def _main_body(oms: OMS) -> None:
    st.title("RFL OMS")
    st.caption("주문관리 · 사전 리스크 점검 · 한도 알림 — 시세와 체결은 모두 시뮬레이션입니다.")
    header_metrics(oms)
    market_watch(oms)

    names = ["주문 입력", "바스켓", "알고리즘", "차익거래", "주문 블로터", "포지션·손익", "리스크", "알림", "감사 로그"]
    show_admin = can(Perm.MANAGE_USERS) or can(Perm.SET_FEES)
    tabs = st.tabs(names + (["관리"] if show_admin else []))
    with tabs[0]:
        order_entry(oms)
    with tabs[1]:
        basket_view(oms)
    with tabs[2]:
        algo_view(oms)
    with tabs[3]:
        arb_view(oms)
    with tabs[4]:
        blotter(oms)
    with tabs[5]:
        positions_view(oms)
    with tabs[6]:
        risk_view(oms)
    with tabs[7]:
        alerts_view(oms)
    with tabs[8]:
        audit_view(oms)
    if show_admin:
        with tabs[9]:
            admin_view(oms)


_user = require_login()
with engine(_user.username) as _oms:
    auto, interval = sidebar(_oms)
st.fragment(main_view, run_every=interval if auto else None)(auto, interval)
```

### `netlify.toml`

```
[build]
  publish = "web"
  command = "python3 tools/build_web.py"

[[headers]]
  for = "/app/*"
  [headers.values]
    Cache-Control = "no-cache"
```

### `requirements.txt`

```text
streamlit
pandas
numpy
matplotlib
scikit-learn
scipy
plotly
openpyxl
```

### `rfl_oms/__init__.py`

```python
"""RFL OMS — 기관용 주문관리시스템 1단계 (모의 체결)."""

from .algo import AlgoStatus, AlgoType
from .arbitrage import ArbDirection, ArbStatus
from .basket import ExecMode, ExecParams
from .engine import OMS
from .market import DEFAULT_INSTRUMENTS, MarketSim
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce
from .risk import RiskLimits

__all__ = [
    "OMS",
    "MarketSim",
    "DEFAULT_INSTRUMENTS",
    "RiskLimits",
    "Side",
    "OrderType",
    "OrderStatus",
    "TimeInForce",
    "AlertLevel",
    "AlgoType",
    "AlgoStatus",
    "ExecMode",
    "ExecParams",
    "ArbDirection",
    "ArbStatus",
]
```

### `rfl_oms/algo.py`

```python
"""실행 알고리즘: TWAP, VWAP, POV.

부모(알고) 주문은 매 틱 목표 누적 수량을 계산하고, 부족분을 자식 주문(IOC 지정가,
상대 1호가)으로 낸다. 자식 주문은 일반 주문과 똑같이 사전 리스크 점검을 거친다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .market import volume_profile
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce

if TYPE_CHECKING:
    from .engine import OMS


class AlgoType(str, Enum):
    TWAP = "TWAP"
    VWAP = "VWAP"
    POV = "POV"


class AlgoStatus(str, Enum):
    RUNNING = "실행중"
    PAUSED = "일시정지"
    DONE = "완료"
    EXPIRED = "기간종료"
    CANCELED = "취소"
    HALTED = "중단"

    @property
    def is_active(self) -> bool:
        return self in (AlgoStatus.RUNNING, AlgoStatus.PAUSED)


ALGO_DESCRIPTIONS = {
    AlgoType.TWAP: "기간 동안 시간에 비례해 균등하게 나눠 체결",
    AlgoType.VWAP: "장중 거래량 패턴(U자형)에 비례해 나눠 체결",
    AlgoType.POV: "직전 틱 시장 거래량의 일정 비율만큼 체결",
}


@dataclass
class AlgoOrder:
    algo_id: str
    symbol: str
    side: Side
    qty: int
    algo_type: AlgoType
    start_tick: int
    duration: int  # 틱 (POV는 최대 실행 기간)
    participation: float  # POV 참여율 (0~1)
    limit_price: float | None
    arrival_price: float
    strategy_tag: str = ""
    actor: str = ""  # 알고를 시작한 사용자 (자식 주문의 행위자)
    status: AlgoStatus = AlgoStatus.RUNNING
    halt_reason: str = ""
    child_ids: list[str] = field(default_factory=list)
    in_flight: int = 0  # 자식 주문 점검 중인 수량 (노출 중복 계산 방지)
    progress: list[tuple[int, int, int]] = field(default_factory=list)  # (틱, 누적체결, 목표)
    mkt_notional: float = 0.0  # 실행 구간 시장 VWAP 계산용
    mkt_volume: int = 0
    _target_pov: float = 0.0


class AlgoEngine:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.algos: dict[str, AlgoOrder] = {}
        self._seq = 0

    # ---------------- 조회 ----------------
    def children(self, algo: AlgoOrder):
        return [self.oms.orders[i] for i in algo.child_ids]

    def filled(self, algo: AlgoOrder) -> int:
        return sum(o.filled_qty for o in self.children(algo))

    def avg_price(self, algo: AlgoOrder) -> float:
        kids = [o for o in self.children(algo) if o.filled_qty]
        q = sum(o.filled_qty for o in kids)
        return sum(o.avg_fill_price * o.filled_qty for o in kids) / q if q else 0.0

    def market_vwap(self, algo: AlgoOrder) -> float:
        return algo.mkt_notional / algo.mkt_volume if algo.mkt_volume else 0.0

    def slippage_bps(self, algo: AlgoOrder, benchmark: float) -> float | None:
        """양수 = 불리한 체결 (매수는 비싸게, 매도는 싸게)."""
        avg = self.avg_price(algo)
        if not avg or not benchmark:
            return None
        return (avg / benchmark - 1) * 1e4 * algo.side.sign

    def reserved(self) -> tuple[dict[str, int], dict[str, int]]:
        """아직 자식 주문으로 나가지 않은 알고 잔량 (리스크 노출 계산용)."""
        buys: dict[str, int] = {}
        sells: dict[str, int] = {}
        for a in self.algos.values():
            if not a.status.is_active:
                continue
            rest = max(a.qty - self.filled(a) - a.in_flight, 0)
            book = buys if a.side is Side.BUY else sells
            book[a.symbol] = book.get(a.symbol, 0) + rest
        return buys, sells

    def target(self, algo: AlgoOrder, tick: int) -> int:
        elapsed = tick - algo.start_tick
        if elapsed <= 0:
            return 0
        if algo.algo_type is AlgoType.TWAP:
            frac = min(elapsed / algo.duration, 1.0)
        elif algo.algo_type is AlgoType.VWAP:
            weights = [volume_profile(algo.start_tick + k) for k in range(1, algo.duration + 1)]
            frac = sum(weights[: min(elapsed, algo.duration)]) / sum(weights)
        else:  # POV: 누적 시장 거래량 × 참여율
            return min(int(algo._target_pov), algo.qty)
        return min(int(algo.qty * frac + 1e-9), algo.qty)

    # ---------------- 제어 ----------------
    def start(
        self,
        symbol: str,
        side: Side,
        qty: int,
        algo_type: AlgoType,
        duration: int = 30,
        participation: float = 0.1,
        limit_price: float | None = None,
        strategy_tag: str = "",
    ) -> AlgoOrder:
        self._seq += 1
        algo = AlgoOrder(
            algo_id=f"A{self._seq:04d}",
            symbol=symbol,
            side=side,
            qty=int(qty),
            algo_type=algo_type,
            start_tick=self.oms.market.tick_no,
            duration=max(int(duration), 1),
            participation=float(participation),
            limit_price=limit_price,
            arrival_price=self.oms.market.mark(symbol),
            strategy_tag=strategy_tag,
            actor=self.oms.actor,
        )
        # 부모 주문 전체 수량으로 사전 점검 (시장가로 전량 체결된다고 가정)
        checks = self.oms.preview(symbol, side, OrderType.MARKET, int(qty))
        failed = [c for c in checks if not c.passed]
        if failed:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self.oms._alert(AlertLevel.WARNING, "알고 거부", f"{algo.algo_id} {symbol} — {algo.halt_reason}")
        elif algo.algo_type is AlgoType.POV and not 0 < algo.participation <= 1:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = "참여율은 0% 초과 100% 이하여야 합니다"
        self.algos[algo.algo_id] = algo
        algo.progress.append((algo.start_tick, 0, 0))
        return algo

    def pause(self, algo_id: str) -> None:
        a = self.algos[algo_id]
        if a.status is AlgoStatus.RUNNING:
            a.status = AlgoStatus.PAUSED

    def resume(self, algo_id: str) -> None:
        a = self.algos[algo_id]
        if a.status is AlgoStatus.PAUSED:
            a.status = AlgoStatus.RUNNING

    def cancel(self, algo_id: str, reason: str = "사용자 취소") -> None:
        a = self.algos[algo_id]
        if not a.status.is_active:
            return
        for o in self.children(a):
            if o.status.is_open:
                self.oms.cancel(o.order_id, reason)
        a.status = AlgoStatus.CANCELED
        a.halt_reason = reason

    def cancel_all(self, reason: str) -> int:
        active = [a.algo_id for a in self.algos.values() if a.status.is_active]
        for i in active:
            self.cancel(i, reason)
        return len(active)

    # ---------------- 틱 처리 ----------------
    def on_tick(self) -> None:
        tick = self.oms.market.tick_no
        for algo in list(self.algos.values()):
            if not algo.status.is_active:
                continue
            vol = self.oms.market.volume[algo.symbol]
            algo.mkt_volume += vol
            algo.mkt_notional += vol * self.oms.market.mark(algo.symbol)
            if algo.algo_type is AlgoType.POV:
                algo._target_pov += vol * algo.participation
            if algo.status is AlgoStatus.RUNNING:
                self._work(algo, tick)
            filled = self.filled(algo)
            algo.progress.append((tick, filled, self.target(algo, tick)))
            if filled >= algo.qty:
                algo.status = AlgoStatus.DONE
                self.oms._alert(AlertLevel.INFO, "알고 완료", self._summary(algo))
            elif tick - algo.start_tick >= algo.duration and algo.status is AlgoStatus.RUNNING:
                algo.status = AlgoStatus.EXPIRED
                self.oms._alert(
                    AlertLevel.WARNING, "알고 기간종료", f"{self._summary(algo)} · 미체결 {algo.qty - filled:,}"
                )
            del algo.progress[:-500]

    def _summary(self, algo: AlgoOrder) -> str:
        slip = self.slippage_bps(algo, algo.arrival_price)
        slip_txt = f", 도착가 대비 {slip:+.1f}bp" if slip is not None else ""
        return (
            f"{algo.algo_id} {algo.algo_type.value} {algo.symbol} {algo.side.value} "
            f"{self.filled(algo):,}/{algo.qty:,} 평균 {self.avg_price(algo):,.4g}{slip_txt}"
        )

    def _work(self, algo: AlgoOrder, tick: int) -> None:
        want = self.target(algo, tick) - self.filled(algo)
        if tick - algo.start_tick >= algo.duration and algo.algo_type is not AlgoType.POV:
            want = algo.qty - self.filled(algo)  # 마지막 틱: 남은 수량 전부 시도
        if want <= 0:
            return
        q = self.oms.market.quote(algo.symbol)
        price = q.ask if algo.side is Side.BUY else q.bid
        if algo.limit_price is not None:
            if algo.side is Side.BUY and price > algo.limit_price:
                return  # 제한가 위: 이번 틱은 대기
            if algo.side is Side.SELL and price < algo.limit_price:
                return
        algo.in_flight = want
        with self.oms.acting(algo.actor):
            child = self.oms.submit(
                algo.symbol,
                algo.side,
                OrderType.LIMIT,
                want,
                price,
                TimeInForce.IOC,
                strategy_tag=algo.algo_id,
            )
        algo.in_flight = 0
        algo.child_ids.append(child.order_id)
        if child.status is OrderStatus.REJECTED:
            algo.status = AlgoStatus.HALTED
            algo.halt_reason = child.reject_reason
            self.oms._alert(AlertLevel.CRITICAL, "알고 중단", f"{algo.algo_id} 자식 주문 거부 — {child.reject_reason}")
```

### `rfl_oms/analytics.py`

```python
"""리스크 분석: 노출 분해, 집중도, VaR, 스트레스 테스트.

모든 계산은 체결된 포지션 기준이다 (미체결 주문은 한도 점검에서 따로 반영).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .market import SESSION_TICKS

if TYPE_CHECKING:
    from .engine import OMS

Z = {0.95: 1.6449, 0.99: 2.3263}


def position_frame(oms: "OMS") -> pd.DataFrame:
    rows = []
    for s, p in oms.positions.items():
        if p.qty == 0:
            continue
        inst = oms.instruments[s]
        n = p.qty * oms.market.mark(s) * inst.multiplier
        rows.append(
            {
                "종목": s,
                "종목명": inst.name,
                "자산군": inst.asset_class,
                "수량": p.qty,
                "순명목": n,
                "총명목": abs(n),
                "증거금": abs(n) * inst.margin_rate,
            }
        )
    return pd.DataFrame(rows, columns=["종목", "종목명", "자산군", "수량", "순명목", "총명목", "증거금"])


def exposure_by_asset_class(oms: "OMS") -> pd.DataFrame:
    df = position_frame(oms)
    if df.empty:
        return pd.DataFrame(columns=["자산군", "매수", "매도", "순노출", "총노출"])
    df["매수"] = df["순명목"].clip(lower=0)
    df["매도"] = df["순명목"].clip(upper=0)
    out = df.groupby("자산군", as_index=False)[["매수", "매도", "순명목", "총명목"]].sum()
    return out.rename(columns={"순명목": "순노출", "총명목": "총노출"}).sort_values("총노출", ascending=False)


def concentration(oms: "OMS", top: int = 5) -> pd.DataFrame:
    df = position_frame(oms)
    if df.empty:
        return df
    gross = df["총명목"].sum()
    df = df.sort_values("총명목", ascending=False).head(top).copy()
    df["비중"] = df["총명목"] / gross
    return df[["종목", "종목명", "수량", "순명목", "비중"]]


def equity_beta_exposure(oms: "OMS") -> float:
    """주식 + 지수선물 순노출 (지수 방향 위험, 베타 1 가정)."""
    df = position_frame(oms)
    if df.empty:
        return 0.0
    return float(df.loc[df["자산군"].isin(["주식", "주가지수선물"]), "순명목"].sum())


@dataclass
class VarResult:
    historical: float | None  # 1거래일, 손실 금액(양수)
    parametric: float | None
    observations: int
    confidence: float


def value_at_risk(oms: "OMS", confidence: float = 0.99, lookback: int = 250) -> VarResult:
    """과거 틱 수익률로 현재 포트폴리오의 손익 분포를 만들고 1거래일로 환산(√120)."""
    pos = {s: p.qty for s, p in oms.positions.items() if p.qty}
    if not pos:
        return VarResult(0.0, 0.0, 0, confidence)
    series = {}
    for s in pos:
        hist = oms.market.history[s][-(lookback + 1):]
        series[s] = pd.Series({t: px for t, px in hist})
    prices = pd.DataFrame(series).sort_index().dropna()
    rets = prices.pct_change().dropna()
    if len(rets) < 20:
        return VarResult(None, None, len(rets), confidence)
    notional = np.array(
        [pos[s] * oms.market.mark(s) * oms.instruments[s].multiplier for s in rets.columns]
    )
    pnl = rets.values @ notional
    scale = math.sqrt(SESSION_TICKS)
    hist_var = -np.quantile(pnl, 1 - confidence) * scale
    param_var = Z.get(confidence, 2.3263) * pnl.std(ddof=1) * scale
    return VarResult(max(hist_var, 0.0), max(param_var, 0.0), len(rets), confidence)


# 자산군 또는 종목코드 → 가격 변화율
DEFAULT_SCENARIOS: dict[str, dict[str, float]] = {
    "주가 급락 (−5%)": {"주식": -0.05, "주가지수선물": -0.05},
    "주가 급등 (+5%)": {"주식": 0.05, "주가지수선물": 0.05},
    "원/달러 급등 (+3%)": {"통화선물": 0.03},
    "금리 +50bp (국채선물 −1.3%)": {"금리선물": -0.013},
    "금 급락 (−5%)": {"금 현물": -0.05},
    "선물 베이시스 확대 (선물 −1%)": {"주가지수선물": -0.01},
    "복합 위기": {"주식": -0.08, "주가지수선물": -0.09, "통화선물": 0.05, "금리선물": 0.008, "금 현물": 0.03},
}


def stress_test(oms: "OMS", scenarios: dict[str, dict[str, float]] | None = None) -> pd.DataFrame:
    scenarios = scenarios or DEFAULT_SCENARIOS
    df = position_frame(oms)
    equity = oms.equity()
    rows = []
    for name, shocks in scenarios.items():
        pnl = 0.0
        for _, r in df.iterrows():
            shock = shocks.get(r["종목"], shocks.get(r["자산군"], 0.0))
            pnl += r["순명목"] * shock
        rows.append(
            {
                "시나리오": name,
                "충격": ", ".join(f"{k} {v:+.1%}" for k, v in shocks.items()),
                "예상 손익": round(pnl),
                "평가자산 대비": pnl / equity if equity else None,
                "손실한도 대비": -pnl / oms.limits.max_daily_loss if pnl < 0 and oms.limits.max_daily_loss else 0.0,
            }
        )
    return pd.DataFrame(rows)
```

### `rfl_oms/arbitrage.py`

```python
"""지수 차익거래: 지수선물 ↔ 현물 바스켓.

- 매도차익: 선물이 이론가보다 비쌀 때 선물 매도 + 현물 바스켓 매수
- 매수차익: 선물이 이론가보다 쌀 때 선물 매수 + 현물 바스켓 매도(대차 매도 가정)

거래비용(수수료·세금·슬리피지)을 지수 포인트로 환산해 뺀 '순 기대수익(edge)'이
진입 기준을 넘으면 진입하고, 괴리가 청산 기준 안으로 돌아오면 청산한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .basket import BasketLine, ExecMode, ExecParams
from .models import AlertLevel, OrderStatus, OrderType, Side

if TYPE_CHECKING:
    from .engine import OMS


class ArbDirection(str, Enum):
    SELL_ARB = "매도차익"  # 선물 매도 + 현물 매수
    BUY_ARB = "매수차익"  # 선물 매수 + 현물 매도

    @property
    def futures_side(self) -> Side:
        return Side.SELL if self is ArbDirection.SELL_ARB else Side.BUY

    @property
    def stock_side(self) -> Side:
        return Side.BUY if self is ArbDirection.SELL_ARB else Side.SELL


class ArbStatus(str, Enum):
    OPEN = "보유"
    CLOSED = "청산"
    LEG_ERROR = "레그 불일치"


@dataclass
class ArbCosts:
    commission_bps: float = 1.0  # 주식 매매수수료 (편도)
    sell_tax_bps: float = 15.0  # 주식 매도 시 거래세 (시뮬레이션 가정값, 조정 가능)
    futures_bps: float = 0.3  # 선물 수수료 (편도)
    slippage_bps: float = 2.0  # 체결 슬리피지 (편도)

    def round_trip_bps(self) -> float:
        return 2 * self.commission_bps + self.sell_tax_bps + 2 * self.futures_bps + 2 * self.slippage_bps


@dataclass
class ArbSettings:
    entry_edge_pts: float = 0.10  # 비용 차감 후 이 포인트 이상이면 진입
    exit_mispricing_pts: float = 0.0  # 괴리가 이 값 안쪽으로 돌아오면 청산
    contracts: int = 1
    stock_mode: ExecMode = ExecMode.MARKET
    auto: bool = False
    auto_owner: str = "자동차익"  # 자동 차익을 켠 사용자 (자동 주문의 행위자)
    max_open: int = 3


@dataclass
class ArbSnapshot:
    tick: int
    index: float
    fut_bid: float
    fut_ask: float
    fair: float
    cost_pts: float

    @property
    def fut_mid(self) -> float:
        return (self.fut_bid + self.fut_ask) / 2

    @property
    def basis(self) -> float:
        return self.fut_mid - self.index

    @property
    def theo_basis(self) -> float:
        return self.fair - self.index

    @property
    def mispricing(self) -> float:
        """선물 중간가 − 이론가 (양수 = 선물 고평가)."""
        return self.fut_mid - self.fair

    @property
    def mispricing_bps(self) -> float:
        return self.mispricing / self.index * 1e4

    @property
    def sell_edge(self) -> float:
        """매도차익 순 기대수익: 선물 매수호가에 팔 때."""
        return self.fut_bid - self.fair - self.cost_pts

    @property
    def buy_edge(self) -> float:
        """매수차익 순 기대수익: 선물 매도호가에 살 때."""
        return self.fair - self.fut_ask - self.cost_pts


@dataclass
class ArbPosition:
    arb_id: str
    direction: ArbDirection
    contracts: int
    opened_tick: int
    entry: ArbSnapshot
    futures_order_ids: list[str] = field(default_factory=list)
    basket_ids: list[str] = field(default_factory=list)
    status: ArbStatus = ArbStatus.OPEN
    closed_tick: int | None = None
    exit: ArbSnapshot | None = None
    note: str = ""
    owner: str = ""  # 진입한 사용자


class ArbEngine:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.costs = ArbCosts()
        self.settings = ArbSettings()
        self.positions: dict[str, ArbPosition] = {}
        self.history: list[ArbSnapshot] = []
        self._seq = 0
        if self.available:
            self.history.append(self.snapshot())

    @property
    def index_def(self):
        return self.oms.market.index_def

    @property
    def available(self) -> bool:
        return self.index_def is not None

    # ---------------- 시세 ----------------
    def snapshot(self) -> ArbSnapshot:
        m = self.oms.market
        idx = m.index_value()
        q = m.quote(self.index_def.futures_symbol)
        return ArbSnapshot(
            tick=m.tick_no,
            index=idx,
            fut_bid=q.bid,
            fut_ask=q.ask,
            fair=self.index_def.fair_futures(idx),
            cost_pts=idx * self.costs.round_trip_bps() / 1e4,
        )

    def unit_lines(self, side: Side, units: int) -> list[BasketLine]:
        return [BasketLine(s, side, q * units) for s, q in self.index_def.constituents.items()]

    # ---------------- 포지션 평가 ----------------
    def _orders(self, pos: ArbPosition):
        orders = [self.oms.orders[i] for i in pos.futures_order_ids]
        for bid in pos.basket_ids:
            for ln in self.oms.baskets.baskets[bid].lines:
                orders += self.oms.baskets.line_orders(ln)
        return orders

    def net_holdings(self, pos: ArbPosition) -> dict[str, int]:
        net: dict[str, int] = {}
        for o in self._orders(pos):
            net[o.symbol] = net.get(o.symbol, 0) + o.side.sign * o.filled_qty
        return net

    def pnl(self, pos: ArbPosition) -> float:
        """현금흐름 + 남은 보유분 평가 (진입·청산 모두 포함, 비용 제외)."""
        total = 0.0
        for o in self._orders(pos):
            mult = self.oms.instruments[o.symbol].multiplier
            total -= o.side.sign * o.filled_qty * o.avg_fill_price * mult
        for sym, q in self.net_holdings(pos).items():
            total += q * self.oms.market.mark(sym) * self.oms.instruments[sym].multiplier
        return total

    def fees(self, pos: ArbPosition) -> float:
        ids = {o.order_id for o in self._orders(pos)}
        return sum(f.fee for f in self.oms.fills if f.order_id in ids)

    def pnl_net(self, pos: ArbPosition) -> float:
        """비용 차감 후 손익."""
        return self.pnl(pos) - self.fees(pos)

    def hedge(self, pos: ArbPosition) -> tuple[float, float]:
        """(선물 명목, 현물 명목) — 부호 포함. 합이 0에 가까울수록 완전 헤지."""
        fsym = self.index_def.futures_symbol
        fut = stock = 0.0
        for sym, q in self.net_holdings(pos).items():
            n = q * self.oms.market.mark(sym) * self.oms.instruments[sym].multiplier
            if sym == fsym:
                fut += n
            else:
                stock += n
        return fut, stock

    def open_positions(self) -> list[ArbPosition]:
        return [p for p in self.positions.values() if p.status is not ArbStatus.CLOSED]

    # ---------------- 진입·청산 ----------------
    def pre_check(self, direction: ArbDirection, contracts: int) -> list[str]:
        """두 레그 모두 사전 점검을 통과해야 진입한다 (한쪽만 체결되는 위험 방지)."""
        problems = []
        fsym = self.index_def.futures_symbol
        for c in self.oms.preview(fsym, direction.futures_side, OrderType.MARKET, contracts):
            if not c.passed:
                problems.append(f"선물 {c.name}: {c.detail}")
        for ln in self.unit_lines(direction.stock_side, contracts):
            for c in self.oms.preview(ln.symbol, ln.side, OrderType.MARKET, ln.qty):
                if not c.passed:
                    problems.append(f"{ln.symbol} {c.name}: {c.detail}")
        return problems

    def enter(self, direction: ArbDirection, contracts: int | None = None) -> tuple[ArbPosition | None, list[str]]:
        contracts = int(contracts or self.settings.contracts)
        problems = self.pre_check(direction, contracts)
        if problems:
            self.oms._alert(AlertLevel.WARNING, "차익 진입 거부", f"{direction.value} {contracts}계약 — {problems[0]}")
            return None, problems
        self._seq += 1
        snap = self.snapshot()
        pos = ArbPosition(f"X{self._seq:03d}", direction, contracts, snap.tick, snap, owner=self.oms.actor)
        self.positions[pos.arb_id] = pos
        fsym = self.index_def.futures_symbol
        fut = self.oms.submit(fsym, direction.futures_side, OrderType.MARKET, contracts, strategy_tag=pos.arb_id)
        pos.futures_order_ids.append(fut.order_id)
        basket = self.oms.baskets.execute(
            f"{pos.arb_id} {direction.value} 현물",
            self.unit_lines(direction.stock_side, contracts),
            ExecParams(mode=self.settings.stock_mode, duration=10),
        )
        pos.basket_ids.append(basket.basket_id)
        self._check_legs(pos, fut.status is OrderStatus.REJECTED or fut.filled_qty < contracts, basket)
        self.oms._alert(
            AlertLevel.INFO,
            "차익 진입",
            f"{pos.arb_id} {direction.value} {contracts}계약 · 괴리 {snap.mispricing:+.2f}pt "
            f"({snap.mispricing_bps:+.1f}bp) · 비용 {snap.cost_pts:.2f}pt",
        )
        return pos, []

    def close(self, arb_id: str, reason: str = "수동 청산") -> bool:
        pos = self.positions.get(arb_id)
        if pos is None or pos.status is ArbStatus.CLOSED:
            return False
        fsym = self.index_def.futures_symbol
        net = self.net_holdings(pos)
        fq = net.pop(fsym, 0)
        if fq:
            side = Side.SELL if fq > 0 else Side.BUY
            o = self.oms.submit(fsym, side, OrderType.MARKET, abs(fq), strategy_tag=pos.arb_id)
            pos.futures_order_ids.append(o.order_id)
        lines = [BasketLine(s, Side.SELL if q > 0 else Side.BUY, abs(q)) for s, q in net.items() if q]
        if lines:
            b = self.oms.baskets.execute(
                f"{pos.arb_id} 청산 현물", lines, ExecParams(mode=self.settings.stock_mode, duration=10)
            )
            pos.basket_ids.append(b.basket_id)
        pos.exit = self.snapshot()
        pos.closed_tick = pos.exit.tick
        pos.status = ArbStatus.CLOSED
        pos.note = reason
        self.oms._alert(
            AlertLevel.INFO,
            "차익 청산",
            f"{pos.arb_id} {reason} · 괴리 {pos.entry.mispricing:+.2f} → {pos.exit.mispricing:+.2f}pt",
        )
        return True

    def _check_legs(self, pos: ArbPosition, futures_failed: bool, basket) -> None:
        stock_failed = any(ln.error for ln in basket.lines)
        if futures_failed or stock_failed:
            pos.status = ArbStatus.LEG_ERROR
            pos.note = "선물 레그 실패" if futures_failed else "현물 레그 일부 실패"
            self.oms._alert(
                AlertLevel.CRITICAL,
                "차익 레그 불일치",
                f"{pos.arb_id} {pos.note} — 헤지가 깨졌습니다. 청산하거나 잔량을 재실행하세요",
            )

    # ---------------- 틱 처리 ----------------
    def on_tick(self) -> None:
        if not self.available:
            return
        snap = self.snapshot()
        self.history.append(snap)
        del self.history[:-500]
        if not self.settings.auto or self.oms.kill_switch:
            return
        with self.oms.acting(f"{self.settings.auto_owner}(자동)"):
            self._auto(snap)

    def _auto(self, snap: ArbSnapshot) -> None:
        exit_band = self.settings.exit_mispricing_pts
        for pos in self.open_positions():
            if pos.status is not ArbStatus.OPEN:
                continue
            if pos.direction is ArbDirection.SELL_ARB and snap.mispricing <= exit_band:
                self.close(pos.arb_id, "자동 청산(괴리 수렴)")
            elif pos.direction is ArbDirection.BUY_ARB and snap.mispricing >= -exit_band:
                self.close(pos.arb_id, "자동 청산(괴리 수렴)")
        if len(self.open_positions()) >= self.settings.max_open:
            return
        if snap.sell_edge >= self.settings.entry_edge_pts:
            self.enter(ArbDirection.SELL_ARB)
        elif snap.buy_edge >= self.settings.entry_edge_pts:
            self.enter(ArbDirection.BUY_ARB)
```

### `rfl_oms/auth.py`

```python
"""사용자·역할·권한.

- 비밀번호는 PBKDF2-HMAC-SHA256(솔트, 20만 회)으로 해시해 저장하고 평문은 저장하지 않는다.
- 기본 계정·기본 비밀번호는 없다. 사용자가 없으면 첫 관리자 계정을 만들게 한다.
- 로그인 연속 5회 실패 시 15분 잠금.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Role(str, Enum):
    TRADER = "트레이더"
    RISK = "리스크 관리자"
    ADMIN = "관리자"


class Perm(str, Enum):
    VIEW = "조회"
    TRADE = "주문 실행"
    CANCEL_ANY = "모든 주문 취소·정정"
    SET_LIMITS = "리스크 한도 변경"
    KILL_SWITCH = "킬 스위치"
    MANAGE_USERS = "사용자 관리"
    SET_FEES = "수수료 설정"
    RESET_SYSTEM = "시스템 초기화"


# 업무 분리: 주문을 내는 사람(트레이더)과 한도를 정하는 사람(리스크 관리자)을 나눈다.
ROLE_PERMS: dict[Role, frozenset[Perm]] = {
    Role.TRADER: frozenset({Perm.VIEW, Perm.TRADE}),
    Role.RISK: frozenset({Perm.VIEW, Perm.CANCEL_ANY, Perm.SET_LIMITS, Perm.KILL_SWITCH, Perm.SET_FEES}),
    Role.ADMIN: frozenset({Perm.VIEW, Perm.MANAGE_USERS, Perm.SET_FEES, Perm.KILL_SWITCH, Perm.RESET_SYSTEM}),
}

PBKDF2_ITERATIONS = 200_000
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD_LEN = 8


@dataclass
class User:
    username: str
    display_name: str
    role: Role
    active: bool = True

    def can(self, perm: Perm) -> bool:
        return self.active and perm in ROLE_PERMS[self.role]

    @property
    def label(self) -> str:
        return f"{self.display_name}({self.username})"


class AuthError(Exception):
    pass


def _pbkdf2_sha256_pure(password: bytes, salt: bytes, iterations: int) -> bytes:
    """hashlib.pbkdf2_hmac('sha256', ...)와 같은 결과를 내는 순수 파이썬 구현.

    브라우저 실행(Pyodide)처럼 OpenSSL 기반 pbkdf2_hmac이 없는 환경에서 쓴다 (RFC 8018, 출력 32바이트 1블록).
    """
    block = 64
    if len(password) > block:
        password = hashlib.sha256(password).digest()
    password = password.ljust(block, b"\0")
    inner = hashlib.sha256(password.translate(bytes(x ^ 0x36 for x in range(256))))
    outer = hashlib.sha256(password.translate(bytes(x ^ 0x5C for x in range(256))))

    def prf(msg: bytes) -> bytes:
        i, o = inner.copy(), outer.copy()
        i.update(msg)
        o.update(i.digest())
        return o.digest()

    u = prf(salt + (1).to_bytes(4, "big"))
    acc = int.from_bytes(u, "big")
    for _ in range(iterations - 1):
        u = prf(u)
        acc ^= int.from_bytes(u, "big")
    return acc.to_bytes(32, "big")


def _pbkdf2(password: bytes, salt: bytes, iterations: int) -> bytes:
    if hasattr(hashlib, "pbkdf2_hmac"):
        return hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
    return _pbkdf2_sha256_pure(password, salt, iterations)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = _pbkdf2(password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, pw_hash: str, salt_hex: str) -> bool:
    digest, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, pw_hash)


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다")
    if password.isdigit() or password.isalpha():
        raise AuthError("비밀번호에 문자와 숫자를 함께 사용하세요")


def validate_username(username: str) -> None:
    if not username or not username.replace("_", "").replace(".", "").isalnum() or len(username) > 32:
        raise AuthError("아이디는 영문·숫자·밑줄·마침표로 32자 이내여야 합니다")


def lock_until(now: datetime | None = None) -> datetime:
    return (now or datetime.now()) + timedelta(minutes=LOCK_MINUTES)
```

### `rfl_oms/basket.py`

```python
"""바스켓 주문: 구성(수량·비중·파일), 템플릿, 원클릭 실행, 모니터링, 재실행."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

import pandas as pd

from .algo import AlgoType
from .models import AlertLevel, OrderStatus, OrderType, Side, TimeInForce

if TYPE_CHECKING:
    from .engine import OMS


class ExecMode(str, Enum):
    MARKET = "시장가"
    AGGRESSIVE = "지정가 · 상대호가"  # 매수는 매도호가(+n틱), 매도는 매수호가(-n틱)
    PASSIVE = "지정가 · 자기호가"  # 매수는 매수호가(-n틱), 매도는 매도호가(+n틱)
    TWAP = "TWAP"
    VWAP = "VWAP"
    POV = "POV"

    @property
    def algo_type(self) -> AlgoType | None:
        return {ExecMode.TWAP: AlgoType.TWAP, ExecMode.VWAP: AlgoType.VWAP, ExecMode.POV: AlgoType.POV}.get(self)


@dataclass
class ExecParams:
    mode: ExecMode = ExecMode.MARKET
    offset_ticks: int = 0
    duration: int = 30
    participation: float = 0.1
    auto_retry: bool = True  # 유동성 부족으로 남은 수량을 다음 틱에 자동 재전송
    max_retries: int = 3


@dataclass
class BasketLine:
    symbol: str
    side: Side
    qty: int
    order_ids: list[str] = field(default_factory=list)
    algo_ids: list[str] = field(default_factory=list)
    retries: int = 0
    error: str = ""


@dataclass
class Basket:
    basket_id: str
    name: str
    lines: list[BasketLine]
    params: ExecParams
    created_at: datetime
    canceled: bool = False
    actor: str = ""  # 바스켓을 실행한 사용자


SIDE_ALIASES = {
    "매수": Side.BUY, "BUY": Side.BUY, "B": Side.BUY, "LONG": Side.BUY, "1": Side.BUY,
    "매도": Side.SELL, "SELL": Side.SELL, "S": Side.SELL, "SHORT": Side.SELL, "-1": Side.SELL,
}


def parse_side(value) -> Side:
    key = str(value).strip().upper()
    if key not in SIDE_ALIASES:
        raise ValueError(f"구분 값 '{value}'을(를) 알 수 없습니다 (매수/매도, BUY/SELL, B/S)")
    return SIDE_ALIASES[key]


def normalize_symbol(value) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() else text.upper()


class BasketManager:
    def __init__(self, oms: "OMS"):
        self.oms = oms
        self.baskets: dict[str, Basket] = {}
        self.templates: dict[str, pd.DataFrame] = {}
        self._seq = 0

    # ================= 구성 =================
    def build_lines(
        self, df: pd.DataFrame, by: str = "수량", target_notional: float | None = None
    ) -> tuple[list[BasketLine], list[str]]:
        """표(DataFrame)를 바스켓 라인으로 변환한다.

        필수 열: 종목코드, 구분, 그리고 by="수량"이면 수량 열, by="비중"이면 비중(%) 열.
        비중 방식은 target_notional(목표 명목금액)을 비중대로 나눠 수량을 계산한다(소수점 이하 버림).
        """
        errors: list[str] = []
        cols = {c.strip(): c for c in df.columns.astype(str)}
        for need in ("종목코드", "구분"):
            if need not in cols:
                return [], [f"'{need}' 열이 없습니다"]
        weight_col = next((cols[c] for c in ("비중(%)", "비중") if c in cols), None)
        qty_col = cols.get("수량")
        use_weight = by == "비중"
        if use_weight and weight_col is None:
            return [], ["비중 방식에는 '비중(%)' 열이 필요합니다"]
        if not use_weight and qty_col is None:
            return [], ["수량 방식에는 '수량' 열이 필요합니다"]
        if use_weight and not target_notional:
            return [], ["비중 방식은 목표 명목금액이 필요합니다"]

        rows = df.dropna(subset=[cols["종목코드"]])
        total_w = 0.0
        if use_weight:
            total_w = pd.to_numeric(rows[weight_col], errors="coerce").fillna(0).clip(lower=0).sum()
            if total_w <= 0:
                return [], ["비중 합계가 0입니다"]

        lines: list[BasketLine] = []
        for i, row in rows.iterrows():
            label = f"{i + 1}행"
            symbol = normalize_symbol(row[cols["종목코드"]])
            if symbol not in self.oms.instruments:
                errors.append(f"{label}: 알 수 없는 종목 {symbol}")
                continue
            try:
                side = parse_side(row[cols["구분"]])
            except ValueError as e:
                errors.append(f"{label}: {e}")
                continue
            inst = self.oms.instruments[symbol]
            if use_weight:
                w = float(pd.to_numeric(row[weight_col], errors="coerce") or 0)
                unit = self.oms.market.mark(symbol) * inst.multiplier
                qty = math.floor(target_notional * w / total_w / unit)
                if qty <= 0:
                    errors.append(f"{label}: {symbol} 배정 금액이 1주(계약) 가격보다 작습니다")
                    continue
            else:
                q = pd.to_numeric(row[qty_col], errors="coerce")
                if pd.isna(q) or q <= 0 or q != int(q):
                    errors.append(f"{label}: 수량은 1 이상의 정수여야 합니다")
                    continue
                qty = int(q)
            lines.append(BasketLine(symbol, side, qty))
        return lines, errors

    def preview_frame(self, lines: list[BasketLine]) -> pd.DataFrame:
        rows = []
        for ln in lines:
            inst = self.oms.instruments[ln.symbol]
            mark = self.oms.market.mark(ln.symbol)
            checks = self.oms.preview(ln.symbol, ln.side, OrderType.MARKET, ln.qty)
            failed = [c.name for c in checks if not c.passed]
            rows.append(
                {
                    "종목코드": ln.symbol,
                    "종목명": inst.name,
                    "구분": ln.side.value,
                    "수량": ln.qty,
                    "기준가": mark,
                    "예상 명목": ln.qty * mark * inst.multiplier,
                    "사전 점검": "통과" if not failed else "실패: " + ", ".join(failed),
                }
            )
        return pd.DataFrame(rows)

    # ================= 템플릿 =================
    def save_template(self, name: str, df: pd.DataFrame) -> None:
        self.templates[name] = df.copy()

    def load_template(self, name: str) -> pd.DataFrame:
        return self.templates[name].copy()

    # ================= 실행 =================
    def execute(self, name: str, lines: list[BasketLine], params: ExecParams) -> Basket:
        self._seq += 1
        basket = Basket(
            f"B{self._seq:04d}", name or f"바스켓 {self._seq}", lines, params, datetime.now(), actor=self.oms.actor
        )
        self.baskets[basket.basket_id] = basket
        for ln in lines:
            self._send(basket, ln, ln.qty)
        failed = [ln for ln in lines if ln.error]
        level = AlertLevel.WARNING if failed else AlertLevel.INFO
        self.oms._alert(
            level,
            "바스켓 실행",
            f"{basket.basket_id} {basket.name}: {len(lines)}종목 전송, 거부 {len(failed)}건",
        )
        return basket

    def _price_for(self, line: BasketLine, params: ExecParams) -> float:
        inst = self.oms.instruments[line.symbol]
        q = self.oms.market.quote(line.symbol)
        off = params.offset_ticks * inst.tick_size
        if params.mode is ExecMode.AGGRESSIVE:
            px = q.ask + off if line.side is Side.BUY else q.bid - off
        else:  # PASSIVE
            px = q.bid - off if line.side is Side.BUY else q.ask + off
        return inst.round_to_tick(max(px, inst.tick_size))

    def _send(self, basket: Basket, line: BasketLine, qty: int) -> None:
        params = basket.params
        tag = basket.basket_id
        line.error = ""
        if params.mode.algo_type is not None:
            algo = self.oms.algos.start(
                line.symbol, line.side, qty, params.mode.algo_type, params.duration, params.participation,
                strategy_tag=tag,
            )
            line.algo_ids.append(algo.algo_id)
            if algo.halt_reason:
                line.error = algo.halt_reason
            return
        if params.mode is ExecMode.MARKET:
            order = self.oms.submit(line.symbol, line.side, OrderType.MARKET, qty, strategy_tag=tag)
        else:
            px = self._price_for(line, params)
            order = self.oms.submit(line.symbol, line.side, OrderType.LIMIT, qty, px, TimeInForce.DAY, strategy_tag=tag)
        line.order_ids.append(order.order_id)
        if order.status is OrderStatus.REJECTED:
            line.error = order.reject_reason

    # ================= 상태 =================
    def line_orders(self, line: BasketLine):
        orders = [self.oms.orders[i] for i in line.order_ids]
        for aid in line.algo_ids:
            orders += self.oms.algos.children(self.oms.algos.algos[aid])
        return orders

    def line_filled(self, line: BasketLine) -> tuple[int, float]:
        orders = [o for o in self.line_orders(line) if o.filled_qty]
        q = sum(o.filled_qty for o in orders)
        avg = sum(o.avg_fill_price * o.filled_qty for o in orders) / q if q else 0.0
        return q, avg

    def line_working(self, line: BasketLine) -> int:
        working = sum(o.leaves_qty for o in self.line_orders(line) if o.status.is_open)
        for aid in line.algo_ids:
            a = self.oms.algos.algos[aid]
            if a.status.is_active:
                working += max(a.qty - self.oms.algos.filled(a), 0)
        return working

    def line_status(self, line: BasketLine) -> str:
        filled, _ = self.line_filled(line)
        if filled >= line.qty:
            return "완료"
        if self.line_working(line):
            return "진행중" if not filled else "부분체결"
        if line.error:
            return "거부" if not filled else "부분체결·거부"
        return "미체결 잔량" if filled else "미체결"

    def lines_frame(self, basket: Basket) -> pd.DataFrame:
        rows = []
        for ln in basket.lines:
            inst = self.oms.instruments[ln.symbol]
            filled, avg = self.line_filled(ln)
            mark = self.oms.market.mark(ln.symbol)
            pnl = (mark - avg) * filled * ln.side.sign * inst.multiplier if filled else 0.0
            rows.append(
                {
                    "종목코드": ln.symbol,
                    "종목명": inst.name,
                    "구분": ln.side.value,
                    "목표": ln.qty,
                    "체결": filled,
                    "진행 중": self.line_working(ln),
                    "체결률": filled / ln.qty,
                    "평균체결가": round(avg, 4) if filled else None,
                    "현재가": mark,
                    "평가손익": round(pnl),
                    "상태": self.line_status(ln),
                    "재전송": ln.retries,
                    "주문": ", ".join(ln.order_ids + ln.algo_ids),
                    "오류": ln.error,
                }
            )
        return pd.DataFrame(rows)

    def summary(self, basket: Basket) -> dict:
        target_n = filled_n = filled_at_mark = pnl = 0.0
        target_q = filled_q = working = 0
        for ln in basket.lines:
            inst = self.oms.instruments[ln.symbol]
            mark = self.oms.market.mark(ln.symbol)
            filled, avg = self.line_filled(ln)
            target_n += ln.qty * mark * inst.multiplier
            filled_n += filled * avg * inst.multiplier
            filled_at_mark += filled * mark * inst.multiplier
            pnl += (mark - avg) * filled * ln.side.sign * inst.multiplier if filled else 0.0
            target_q += ln.qty
            filled_q += filled
            working += self.line_working(ln)
        done = sum(self.line_status(ln) == "완료" for ln in basket.lines)
        return {
            "종목 수": len(basket.lines),
            "완료 종목": done,
            "수량 체결률": filled_q / target_q if target_q else 0.0,
            # 금액 체결률은 목표와 체결을 같은 현재가로 평가해 가격 변동 효과를 뺀다
            "금액 체결률": filled_at_mark / target_n if target_n else 0.0,
            "목표 명목": target_n,
            "체결 금액": filled_n,
            "진행 중 수량": working,
            "잔량": target_q - filled_q,
            "평가손익": pnl,
            "거부 종목": sum(bool(ln.error) for ln in basket.lines),
        }

    # ================= 제어 =================
    def cancel(self, basket_id: str) -> int:
        b = self.baskets[basket_id]
        b.canceled = True
        n = 0
        for ln in b.lines:
            for aid in ln.algo_ids:
                if self.oms.algos.algos[aid].status.is_active:
                    self.oms.algos.cancel(aid, f"{basket_id} 바스켓 취소")
                    n += 1
            for oid in ln.order_ids:
                n += self.oms.cancel(oid, f"{basket_id} 바스켓 취소")
        return n

    def retry(self, basket_id: str) -> int:
        """체결되지 않고 진행 중이지도 않은 잔량을 같은 실행 방식으로 다시 보낸다."""
        b = self.baskets[basket_id]
        b.canceled = False
        sent = 0
        for ln in b.lines:
            filled, _ = self.line_filled(ln)
            rest = ln.qty - filled - self.line_working(ln)
            if rest > 0:
                ln.retries += 1
                self._send(b, ln, rest)
                sent += 1
        return sent

    def reprice(self, basket_id: str) -> int:
        """지정가 미체결 주문을 현재 호가 기준(실행 설정의 n틱)으로 정정한다."""
        b = self.baskets[basket_id]
        if b.params.mode not in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE):
            return 0
        n = 0
        for ln in b.lines:
            px = self._price_for(ln, b.params)
            for oid in ln.order_ids:
                o = self.oms.orders[oid]
                if o.status.is_open and o.limit_price != px:
                    ok, _ = self.oms.amend(oid, new_limit_price=px)
                    n += ok
        return n

    def on_tick(self) -> None:
        """자동 재전송: 리스크 거부가 아닌 이유(유동성 부족 등)로 남은 수량을 다시 보낸다."""
        for b in self.baskets.values():
            if b.canceled or not b.params.auto_retry or b.params.mode is not ExecMode.MARKET:
                continue
            for ln in b.lines:
                if ln.error or ln.retries >= b.params.max_retries:
                    continue
                filled, _ = self.line_filled(ln)
                rest = ln.qty - filled - self.line_working(ln)
                if rest > 0:
                    ln.retries += 1
                    with self.oms.acting(b.actor):
                        self._send(b, ln, rest)
                    if ln.error:
                        self.oms._alert(
                            AlertLevel.WARNING, "바스켓 재전송 거부", f"{b.basket_id} {ln.symbol} — {ln.error}"
                        )


def sample_template() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "종목코드": ["005930", "000660", "005380", "035420", "105560"],
            "구분": ["매수"] * 5,
            "수량": [500, 100, 80, 100, 300],
            "비중(%)": [30, 25, 15, 15, 15],
        }
    )
```

### `rfl_oms/engine.py`

```python
"""RFL OMS 엔진: 주문 라이프사이클, 모의 체결, 포지션·손익, 한도 알림.

주문 흐름: 생성 → 형식 검증 → 보강(라우팅 대상·명목금액·증거금) → 사전 리스크 점검
→ 라우팅(접수) → 체결/부분체결 → (정정·취소·IOC 잔량 취소)
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime

from .algo import AlgoEngine
from .arbitrage import ArbEngine
from .basket import BasketManager
from .fees import FeeSchedule
from .market import MarketSim
from .models import (
    Alert,
    AlertLevel,
    Fill,
    Order,
    OrderEvent,
    OrderStatus,
    OrderType,
    Position,
    PriceAlertRule,
    Side,
    TimeInForce,
)
from .risk import CheckResult, Exposure, RiskLimits, pre_trade_checks, static_checks


class OMS:
    def __init__(
        self,
        market: MarketSim | None = None,
        limits: RiskLimits | None = None,
        account: str = "RFL-001",
    ):
        self.market = market or MarketSim()
        self.limits = limits or RiskLimits()
        self.fees = FeeSchedule()
        self.account = account
        self.actor = ""  # 현재 행위자 (acting() 문맥으로 지정)
        self._dirty_orders: set[str] = set()  # 저장소에 아직 반영하지 않은 주문
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.positions: dict[str, Position] = {s: Position(s) for s in self.market.instruments}
        self.audit: list[OrderEvent] = []
        self.alerts: list[Alert] = []
        self.price_rules: list[PriceAlertRule] = []
        self.kill_switch = False
        self._seq = 0
        self._rule_seq = 0
        self._alert_state: dict[str, AlertLevel] = {}
        self.algos = AlgoEngine(self)
        self.baskets = BasketManager(self)
        self.arb = ArbEngine(self)
        # 시장이 한 틱 진행된 뒤, 미체결 주문 매칭 다음에 호출되는 처리기
        self.tick_hooks = [self.algos.on_tick, self.baskets.on_tick, self.arb.on_tick]
        # (틱, 실현손익, 미실현손익, 평가자산, 총노출)
        self.pnl_history: list[tuple[int, float, float, float, float]] = []
        self._record_pnl()

    # ================= 조회·지표 =================
    @property
    def instruments(self):
        return self.market.instruments

    def open_orders(self) -> list[Order]:
        return [o for o in self.orders.values() if o.status.is_open]

    def unrealized_pnl(self, symbol: str) -> float:
        pos = self.positions[symbol]
        if pos.qty == 0:
            return 0.0
        inst = self.instruments[symbol]
        return (self.market.mark(symbol) - pos.avg_price) * pos.qty * inst.multiplier

    def realized_pnl(self) -> float:
        """실현손익 (비용 차감 전)."""
        return sum(p.realized_pnl for p in self.positions.values())

    def total_fees(self) -> float:
        return sum(p.fees for p in self.positions.values())

    def daily_pnl(self) -> float:
        """순손익 = 실현 + 미실현 − 수수료·세금. 손실 한도와 평가자산의 기준."""
        return self.realized_pnl() + sum(self.unrealized_pnl(s) for s in self.positions) - self.total_fees()

    # ================= 행위자·시스템 이벤트 =================
    @contextmanager
    def acting(self, actor: str):
        """이 문맥 안에서 생긴 주문·이벤트에 행위자를 기록한다."""
        prev, self.actor = self.actor, actor
        try:
            yield self
        finally:
            self.actor = prev

    def system_event(self, event: str, detail: str = "") -> None:
        self.audit.append(OrderEvent(datetime.now(), "-", event, detail, self.actor))

    def set_limits(self, limits: RiskLimits) -> None:
        old, self.limits = self.limits, limits
        changes = [
            f"{k}: {getattr(old, k)} → {getattr(limits, k)}"
            for k in limits.__dataclass_fields__
            if getattr(old, k) != getattr(limits, k)
        ]
        if changes:
            self.system_event("한도 변경", "; ".join(changes))
        self._evaluate_alerts()

    def set_fees(self, fees: FeeSchedule) -> None:
        old, self.fees = self.fees, fees
        changes = [
            f"{k}: {getattr(old, k)} → {getattr(fees, k)}"
            for k in fees.__dataclass_fields__
            if getattr(old, k) != getattr(fees, k)
        ]
        if changes:
            self.system_event("수수료 변경", "; ".join(changes))

    def equity(self) -> float:
        return self.limits.capital + self.daily_pnl()

    def exposure(self, extra: Order | None = None, exclude_id: str | None = None) -> Exposure:
        """현재 포지션 + 미체결 주문 + 알고 잔량(+ 신규 주문)이 모두 체결될 때의 최악 노출."""
        buys = {s: 0 for s in self.instruments}
        sells = {s: 0 for s in self.instruments}
        algo_buys, algo_sells = self.algos.reserved()
        for s, q in algo_buys.items():
            buys[s] += q
        for s, q in algo_sells.items():
            sells[s] += q
        candidates = [o for o in self.open_orders() if o.order_id != exclude_id]
        if extra is not None:
            candidates.append(extra)
        for o in candidates:
            leaves = o.qty - o.filled_qty
            (buys if o.side is Side.BUY else sells)[o.symbol] += leaves
        qty, notional = {}, {}
        gross = margin = 0.0
        for s, inst in self.instruments.items():
            pos = self.positions[s].qty
            worst = max(abs(pos + buys[s]), abs(pos - sells[s]))
            n = worst * self.market.mark(s) * inst.multiplier
            qty[s], notional[s] = worst, n
            gross += n
            margin += n * inst.margin_rate
        # 헤지 상계는 보수적으로: 현재 포지션, 매수 전량 체결, 매도 전량 체결 중 가장 작은 상계만 인정
        pos_now = {s: p.qty for s, p in self.positions.items()}
        all_buys = {s: pos_now[s] + buys[s] for s in pos_now}
        all_sells = {s: pos_now[s] - sells[s] for s in pos_now}
        credit = min(self.hedge_credit(pos_now), self.hedge_credit(all_buys), self.hedge_credit(all_sells))
        return Exposure(qty, notional, gross, margin - credit, margin, credit)

    def hedge_credit(self, signed_qty: dict[str, int]) -> float:
        """지수선물과 구성종목 순노출이 반대 방향이면, 헤지된 금액만큼 선물 증거금을 감면한다."""
        idx = self.market.index_def
        if idx is None or not self.limits.margin_offset_enabled:
            return 0.0
        fsym = idx.futures_symbol
        finst = self.instruments[fsym]
        fut = signed_qty.get(fsym, 0) * self.market.mark(fsym) * finst.multiplier
        stock = sum(signed_qty.get(s, 0) * self.market.mark(s) for s in idx.constituents)
        if fut * stock >= 0:
            return 0.0
        hedged = min(abs(fut), abs(stock))
        return hedged * finst.margin_rate * self.limits.margin_offset_pct / 100

    def margin_breakdown(self) -> dict[str, float]:
        """체결된 포지션 기준 증거금: 상계 전, 상계액, 순증거금."""
        gross = sum(
            abs(p.qty) * self.market.mark(s) * self.instruments[s].multiplier * self.instruments[s].margin_rate
            for s, p in self.positions.items()
        )
        credit = self.hedge_credit({s: p.qty for s, p in self.positions.items()})
        return {"상계 전": gross, "헤지 상계": credit, "순증거금": gross - credit}

    def margin_used(self) -> float:
        """체결된 포지션 기준 순증거금 (헤지 상계 반영)."""
        return self.margin_breakdown()["순증거금"]

    def utilization(self) -> list[dict]:
        """한도별 사용률 (알림과 대시보드 공용)."""
        exp = self.exposure()
        lim = self.limits
        equity = self.equity()
        rows = [
            {"key": "margin", "항목": "증거금 (미체결 포함)", "사용": exp.margin, "한도": equity},
            {"key": "gross", "항목": "총 노출 (미체결 포함)", "사용": exp.gross, "한도": lim.max_gross_exposure},
            {"key": "loss", "항목": "일일 손실", "사용": max(-self.daily_pnl(), 0.0) + 0.0, "한도": lim.max_daily_loss},
        ]
        for s, n in exp.symbol_notional.items():
            if n > 0:
                rows.append(
                    {
                        "key": f"pos:{s}",
                        "항목": f"포지션 · {self.instruments[s].name}",
                        "사용": n,
                        "한도": lim.max_position_notional,
                    }
                )
        for r in rows:
            r["사용률"] = r["사용"] / r["한도"] if r["한도"] > 0 else float("inf")
        return rows

    # ================= 주문 =================
    def _log(self, order: Order, event: str, detail: str = "") -> None:
        ev = OrderEvent(datetime.now(), order.order_id, event, detail, self.actor)
        order.events.append(ev)
        self.audit.append(ev)
        self._dirty_orders.add(order.order_id)

    def _alert(self, level: AlertLevel, category: str, message: str) -> None:
        self.alerts.append(Alert(datetime.now(), level, category, message))

    def _px(self, symbol: str, price: float | None) -> str:
        if price is None:
            return "시장가"
        return f"{price:,.{self.instruments[symbol].price_decimals}f}"

    def _ref_price(self, order: Order) -> float:
        if order.order_type is OrderType.LIMIT and order.limit_price:
            return order.limit_price
        q = self.market.quote(order.symbol)
        return q.ask if order.side is Side.BUY else q.bid

    def _new_order(self, symbol, side, order_type, qty, limit_price, tif, strategy_tag="") -> Order:
        self._seq += 1
        if order_type is OrderType.MARKET:
            limit_price = None
        return Order(
            order_id=f"O{self._seq:06d}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=int(qty),
            limit_price=float(limit_price) if limit_price is not None else None,
            account=self.account,
            tif=TimeInForce.IOC if order_type is OrderType.MARKET else tif,
            created_at=datetime.now(),
            strategy_tag=strategy_tag,
            trader=self.actor,
        )

    def _enrich(self, order: Order) -> None:
        inst = self.instruments[order.symbol]
        order.venue = inst.venue
        order.est_notional = order.qty * self._ref_price(order) * inst.multiplier
        order.est_margin = order.est_notional * inst.margin_rate

    def run_checks(self, order: Order, exclude_id: str | None = None) -> list[CheckResult]:
        inst = self.instruments.get(order.symbol)
        results = static_checks(order, inst)
        if not all(r.passed for r in results):
            return results
        before = self.exposure()
        after = self.exposure(extra=order, exclude_id=exclude_id)
        return results + pre_trade_checks(
            order,
            inst,
            mark=self.market.mark(order.symbol),
            ref_price=self._ref_price(order),
            limits=self.limits,
            before=before,
            after=after,
            equity=self.equity(),
            daily_pnl=self.daily_pnl(),
            kill_switch=self.kill_switch,
        )

    def preview(
        self, symbol, side, order_type, qty, limit_price=None, tif=TimeInForce.DAY
    ) -> list[CheckResult]:
        """주문을 내지 않고 사전 점검 결과만 본다 (주문번호를 소비하지 않음)."""
        draft = self._new_order(symbol, side, order_type, qty, limit_price, tif)
        self._seq -= 1
        return self.run_checks(draft)

    def submit(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        qty: int,
        limit_price: float | None = None,
        tif: TimeInForce = TimeInForce.DAY,
        strategy_tag: str = "",
    ) -> Order:
        order = self._new_order(symbol, side, order_type, qty, limit_price, tif, strategy_tag)
        self.orders[order.order_id] = order
        self._log(
            order,
            "생성",
            f"{symbol} {side.value} {order.qty:,} @{self._px(symbol, order.limit_price)} {order.tif.value}",
        )

        checks = self.run_checks(order)
        failed = [c for c in checks if not c.passed]
        if failed:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self._log(order, "거부", order.reject_reason)
            self._alert(AlertLevel.WARNING, "주문 거부", f"{order.order_id} {symbol} — {order.reject_reason}")
            return order

        order.status = OrderStatus.VALIDATED
        self._log(order, "검증 통과", f"사전 점검 {len(checks)}건 통과")
        self._enrich(order)
        self._log(
            order,
            "보강",
            f"라우팅 {order.venue}, 예상 명목 {order.est_notional:,.0f}, 예상 증거금 {order.est_margin:,.0f}",
        )
        order.status = OrderStatus.WORKING
        self._log(order, "라우팅", f"{order.venue} 접수")

        self._match(order)
        self._expire_if_ioc(order)
        self._evaluate_alerts()
        return order

    def amend(
        self, order_id: str, new_qty: int | None = None, new_limit_price: float | None = None
    ) -> tuple[bool, list[CheckResult] | str]:
        order = self.orders.get(order_id)
        if order is None or not order.status.is_open:
            return False, "미체결 상태의 주문만 정정할 수 있습니다"
        if order.order_type is not OrderType.LIMIT:
            return False, "지정가 주문만 정정할 수 있습니다"
        qty = order.qty if new_qty is None else int(new_qty)
        price = order.limit_price if new_limit_price is None else float(new_limit_price)
        if qty == order.qty and price == order.limit_price:
            return False, "변경된 내용이 없습니다"
        if qty <= order.filled_qty:
            msg = f"정정 수량은 체결 수량({order.filled_qty:,})보다 커야 합니다"
            self._log(order, "정정 거부", msg)
            return False, msg

        draft = copy.copy(order)
        draft.events = []
        draft.qty, draft.limit_price = qty, price
        checks = self.run_checks(draft, exclude_id=order.order_id)
        failed = [c for c in checks if not c.passed]
        if failed:
            msg = "; ".join(f"{c.name}: {c.detail}" for c in failed)
            self._log(order, "정정 거부", msg)
            self._alert(AlertLevel.WARNING, "정정 거부", f"{order.order_id} — {msg}")
            return False, checks

        old = f"{order.qty:,}@{self._px(order.symbol, order.limit_price)}"
        order.qty, order.limit_price = qty, price
        self._enrich(order)
        self._log(order, "정정", f"{old} → {qty:,}@{self._px(order.symbol, price)}")
        self._match(order)
        self._evaluate_alerts()
        return True, checks

    def cancel(self, order_id: str, reason: str = "사용자 취소") -> bool:
        order = self.orders.get(order_id)
        if order is None or not order.status.is_open:
            return False
        leaves = order.qty - order.filled_qty
        order.status = OrderStatus.CANCELED
        self._log(order, "취소", f"{reason} (잔량 {leaves:,})")
        self._evaluate_alerts()
        return True

    def cancel_all(self, reason: str = "전체 취소") -> int:
        return sum(self.cancel(o.order_id, reason) for o in self.open_orders())

    def set_kill_switch(self, on: bool) -> None:
        if on == self.kill_switch:
            return
        self.kill_switch = on
        self.system_event("킬 스위치", "켜짐 (거래 중지)" if on else "꺼짐 (거래 재개)")
        if on:
            a = self.algos.cancel_all("킬 스위치")
            n = self.cancel_all("킬 스위치")
            self._alert(
                AlertLevel.CRITICAL, "킬 스위치", f"거래 중지: 신규 주문 차단, 미체결 {n}건·알고 {a}건 취소"
            )
        else:
            self._alert(AlertLevel.INFO, "킬 스위치", "거래 재개")

    # ================= 체결 =================
    def _match(self, order: Order) -> None:
        if not order.status.is_open:
            return
        leaves = order.qty - order.filled_qty
        cap = order.limit_price if order.order_type is OrderType.LIMIT else None
        for price, qty in self.market.take_liquidity(order.symbol, order.side, leaves, cap):
            self._fill(order, qty, price)

    def _fill(self, order: Order, qty: int, price: float) -> None:
        inst = self.instruments[order.symbol]
        order.apply_fill(qty, price)
        pos = self.positions[order.symbol]
        realized = pos.apply_fill(order.side, qty, price, inst.multiplier)
        fee = self.fees.fee(inst, order.side, qty, price)
        pos.fees += fee
        fill = Fill(order.order_id, order.symbol, order.side, qty, price, datetime.now(), fee)
        self.fills.append(fill)
        label = "전량체결" if order.status is OrderStatus.FILLED else "부분체결"
        extra = f", 실현손익 {realized:,.0f}" if realized else ""
        extra += f", 비용 {fee:,.0f}" if fee else ""
        self._log(order, label, f"{qty:,}@{self._px(order.symbol, price)} (누적 {order.filled_qty:,}/{order.qty:,}){extra}")

    def _expire_if_ioc(self, order: Order) -> None:
        if order.status.is_open and order.tif is TimeInForce.IOC:
            reason = "시장가 잔량 취소" if order.order_type is OrderType.MARKET else "IOC 잔량 취소"
            self.cancel(order.order_id, reason)

    def step(self, n: int = 1) -> None:
        """시장을 n틱 진행하고 미체결 주문을 시간 우선 순서로 체결한다."""
        for _ in range(n):
            self.market.step()
            for order in self.open_orders():
                self._match(order)
            for hook in self.tick_hooks:
                hook()
            self._check_price_rules()
            self._evaluate_alerts()
            self._record_pnl()

    def _record_pnl(self) -> None:
        realized = self.realized_pnl() - self.total_fees()  # 비용 차감 후 실현
        unrealized = sum(self.unrealized_pnl(s) for s in self.positions)
        gross = sum(
            abs(p.qty) * self.market.mark(s) * self.instruments[s].multiplier for s, p in self.positions.items()
        )
        self.pnl_history.append(
            (self.market.tick_no, realized, unrealized, self.limits.capital + realized + unrealized, gross)
        )
        del self.pnl_history[:-1000]

    # ================= 알림 =================
    def add_price_rule(self, symbol: str, condition: str, price: float) -> PriceAlertRule:
        self._rule_seq += 1
        rule = PriceAlertRule(f"R{self._rule_seq:03d}", symbol, condition, float(price))
        self.price_rules.append(rule)
        return rule

    def _check_price_rules(self) -> None:
        for rule in self.price_rules:
            if not rule.active:
                continue
            mark = self.market.mark(rule.symbol)
            hit = mark >= rule.price if rule.condition == "이상" else mark <= rule.price
            if hit:
                rule.active = False
                name = self.instruments[rule.symbol].name
                self._alert(
                    AlertLevel.INFO,
                    "가격 알림",
                    f"{name} 현재가 {mark:,.4g}가 {rule.price:,} {rule.condition}에 도달",
                )

    def _evaluate_alerts(self) -> None:
        """한도 사용률이 경고/위험 구간에 새로 들어갈 때만 알림을 만든다."""
        for row in self.utilization():
            ratio = row["사용률"]
            if ratio >= 1:
                level = AlertLevel.CRITICAL
            elif ratio >= self.limits.warn_ratio:
                level = AlertLevel.WARNING
            else:
                self._alert_state.pop(row["key"], None)
                continue
            prev = self._alert_state.get(row["key"])
            rank = {AlertLevel.WARNING: 1, AlertLevel.CRITICAL: 2}
            if prev is None or rank[level] > rank[prev]:
                suffix = " — 신규 위험증가 주문 차단" if row["key"] == "loss" and ratio >= 1 else ""
                self._alert(
                    level,
                    "한도",
                    f"{row['항목']} 사용률 {ratio:.0%} ({row['사용']:,.0f} / {row['한도']:,.0f}){suffix}",
                )
            self._alert_state[row["key"]] = level
```

### `rfl_oms/fees.py`

```python
"""거래비용: 체결마다 수수료와 세금을 계산한다 (모두 조정 가능한 가정값)."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Instrument, Side


@dataclass
class FeeSchedule:
    enabled: bool = True
    equity_commission_bps: float = 1.0  # 주식 매매수수료 (매수·매도 각각)
    equity_sell_tax_bps: float = 15.0  # 주식 매도 거래세 (시뮬레이션 가정값)
    gold_commission_bps: float = 2.0  # 금 현물 수수료
    futures_commission_bps: float = 0.3  # 선물 수수료

    def rate_bps(self, inst: Instrument, side: Side) -> float:
        if inst.asset_class == "주식":
            return self.equity_commission_bps + (self.equity_sell_tax_bps if side is Side.SELL else 0.0)
        if inst.asset_class == "금 현물":
            return self.gold_commission_bps
        return self.futures_commission_bps

    def fee(self, inst: Instrument, side: Side, qty: int, price: float) -> float:
        if not self.enabled:
            return 0.0
        return qty * price * inst.multiplier * self.rate_bps(inst, side) / 1e4
```

### `rfl_oms/index.py`

```python
"""시뮬레이션 주가지수와 지수선물 이론가.

지수 = Σ(구성종목 주식수 × 가격) / 제수. 제수를 선물 승수와 같게 두면
지수 1단위(구성종목 주식수 그대로)가 선물 1계약의 현물 복제 바스켓이 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DEFAULT_WEIGHTS = {
    "005930": 0.30,
    "000660": 0.20,
    "005380": 0.10,
    "000270": 0.08,
    "035420": 0.08,
    "105560": 0.08,
    "005490": 0.08,
    "068270": 0.08,
}


@dataclass
class IndexDef:
    name: str
    futures_symbol: str
    constituents: dict[str, int]  # 종목 → 선물 1계약당 주식 수
    divisor: float
    rate: float = 0.035  # 무위험 금리 (연)
    dividend_yield: float = 0.015  # 배당수익률 (연)
    days_to_expiry: int = 30

    def value(self, price: Callable[[str], float]) -> float:
        return sum(q * price(s) for s, q in self.constituents.items()) / self.divisor

    @property
    def carry(self) -> float:
        return (self.rate - self.dividend_yield) * self.days_to_expiry / 365

    def fair_futures(self, index_value: float) -> float:
        """보유비용 모형: F* = S × (1 + (r − d) × T/365)."""
        return index_value * (1 + self.carry)


def build_default_index(start_prices: dict[str, float], futures_symbol: str, futures_price: float, multiplier: float) -> IndexDef:
    """시작 가격 기준으로 선물 이론가가 futures_price가 되도록 구성종목 주식 수를 정한다."""
    idx = IndexDef("RFL 시뮬 지수", futures_symbol, {}, divisor=multiplier)
    target_index = futures_price / (1 + idx.carry)
    unit_value = target_index * multiplier
    idx.constituents = {
        s: max(round(unit_value * w / start_prices[s]), 1) for s, w in DEFAULT_WEIGHTS.items() if s in start_prices
    }
    return idx
```

### `rfl_oms/market.py`

```python
"""시뮬레이션 시장: 종목 유니버스, 랜덤워크 시세, 5단계 호가와 잔량 소진."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .index import IndexDef, build_default_index
from .models import Instrument, Side

DEFAULT_INSTRUMENTS: tuple[Instrument, ...] = (
    Instrument("005930", "삼성전자", "주식", 100, 1, 1.0, "KRX-SIM", 72_000, 0.0015, 3_000),
    Instrument("000660", "SK하이닉스", "주식", 500, 1, 1.0, "KRX-SIM", 180_000, 0.0020, 1_500),
    Instrument("K200F", "코스피200 선물", "주가지수선물", 0.05, 250_000, 0.10, "KRX-SIM", 350.00, 0.0010, 80),
    Instrument("USDF", "미국달러 선물", "통화선물", 0.1, 10_000, 0.05, "KRX-SIM", 1_380.0, 0.0004, 400),
    Instrument("KTBF", "3년 국채선물", "금리선물", 0.01, 1_000_000, 0.02, "KRX-SIM", 105.50, 0.0002, 300),
    Instrument("GOLD", "KRX 금 (1g)", "금 현물", 10, 1, 1.0, "KRX-SIM", 150_000, 0.0008, 2_000),
    # 바스켓 구성용 주식 (가격은 시뮬레이션 시작값일 뿐 실제 시세가 아님)
    Instrument("005380", "현대차", "주식", 500, 1, 1.0, "KRX-SIM", 240_000, 0.0018, 800),
    Instrument("000270", "기아", "주식", 100, 1, 1.0, "KRX-SIM", 98_000, 0.0018, 1_200),
    Instrument("035420", "NAVER", "주식", 100, 1, 1.0, "KRX-SIM", 190_000, 0.0020, 700),
    Instrument("105560", "KB금융", "주식", 100, 1, 1.0, "KRX-SIM", 82_000, 0.0014, 1_200),
    Instrument("005490", "POSCO홀딩스", "주식", 500, 1, 1.0, "KRX-SIM", 380_000, 0.0018, 400),
    Instrument("068270", "셀트리온", "주식", 100, 1, 1.0, "KRX-SIM", 175_000, 0.0020, 600),
)

BOOK_LEVELS = 5
EQUITY_MARKET_CORR = 0.6  # 주식 수익률 중 시장 공통요인 비중(상관계수 근사)
BASIS_MEAN_REVERSION = 0.85  # 선물 괴리의 틱당 잔존 비율
BASIS_VOL = 0.30  # 선물 괴리 충격 (지수 포인트)
SESSION_TICKS = 120  # 시뮬레이션 1거래일 = 120틱


def volume_profile(tick: int) -> float:
    """장중 거래량 U자형 패턴 (장 시작·마감에 많고 점심에 적음). 평균 약 1."""
    x = (tick % SESSION_TICKS) / (SESSION_TICKS - 1)
    return 0.5 + 2.0 * (x - 0.5) ** 2 * 3


@dataclass
class Quote:
    bid: float
    ask: float
    last: float
    prev_close: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def change_pct(self) -> float:
        return (self.last / self.prev_close - 1) * 100


class MarketSim:
    """틱 단위로 진행하는 결정적(seed 고정 가능) 시장 시뮬레이터.

    - 매수 1호가 = 기준가, 매도 1호가 = 기준가 + 1틱
    - 각 호가 단계의 잔량은 틱마다 새로 생성되고, 같은 틱 안에서는 체결로 소진된다.
    """

    def __init__(
        self,
        instruments=DEFAULT_INSTRUMENTS,
        seed: int | None = 7,
        index_def: IndexDef | None = None,
        futures_symbol: str = "K200F",
    ):
        self.instruments: dict[str, Instrument] = {i.symbol: i for i in instruments}
        self.rng = np.random.default_rng(seed)
        self.tick_no = 0
        self._price = {s: i.start_price for s, i in self.instruments.items()}
        # 지수선물을 구성종목 지수의 이론가 + 평균회귀 괴리로 움직인다
        if index_def is None and futures_symbol in self.instruments:
            fut = self.instruments[futures_symbol]
            index_def = build_default_index(self._price, futures_symbol, fut.start_price, fut.multiplier)
        self.index_def = index_def if index_def and index_def.constituents else None
        self.basis_dev = 0.0  # 선물가 − 이론가 (포인트)
        self._prev_close = dict(self._price)
        if self.index_def:
            self._link_futures()
        self._prev_close = dict(self._price)
        self._book: dict[str, dict[Side, list[list[float]]]] = {}
        self.history: dict[str, list[tuple[int, float]]] = {s: [] for s in self.instruments}
        self.volume: dict[str, int] = {s: 0 for s in self.instruments}  # 직전 틱 시장 거래량
        self.volume_history: dict[str, list[tuple[int, int]]] = {s: [] for s in self.instruments}
        for s in self.instruments:
            self._rebuild_book(s)
            self._record(s)

    # ----- 시세 -----
    def quote(self, symbol: str) -> Quote:
        inst = self.instruments[symbol]
        bid = self._price[symbol]
        ask = inst.round_to_tick(bid + inst.tick_size)
        return Quote(bid=bid, ask=ask, last=bid, prev_close=self._prev_close[symbol])

    def mark(self, symbol: str) -> float:
        return self.quote(symbol).mid

    def set_price(self, symbol: str, price: float) -> None:
        """테스트와 시나리오용: 기준가를 강제로 지정한다."""
        self._price[symbol] = self.instruments[symbol].round_to_tick(price)
        self._rebuild_book(symbol)

    def index_value(self) -> float | None:
        return self.index_def.value(self.mark) if self.index_def else None

    def fair_futures(self) -> float | None:
        if not self.index_def:
            return None
        return self.index_def.fair_futures(self.index_value())

    def _link_futures(self) -> None:
        fsym = self.index_def.futures_symbol
        inst = self.instruments[fsym]
        # 기준가(매수1호가) = 이론가 + 괴리 − 반 틱 → 중간가가 이론가 + 괴리에 가깝게
        self._price[fsym] = inst.round_to_tick(self.fair_futures() + self.basis_dev - inst.tick_size / 2)

    def step(self) -> None:
        self.tick_no += 1
        mkt = self.rng.normal()
        fsym = self.index_def.futures_symbol if self.index_def else None
        for s, inst in self.instruments.items():
            z = self.rng.normal()
            if inst.asset_class == "주식":
                rho = EQUITY_MARKET_CORR
                z = rho * mkt + math.sqrt(1 - rho**2) * z
            if s == fsym:
                continue
            new_price = inst.round_to_tick(self._price[s] * math.exp(z * inst.volatility))
            self._price[s] = max(new_price, inst.tick_size)
        if fsym:
            self.basis_dev = BASIS_MEAN_REVERSION * self.basis_dev + self.rng.normal(0.0, BASIS_VOL)
            self._link_futures()
        for s, inst in self.instruments.items():
            self._rebuild_book(s)
            vol = inst.base_liquidity * volume_profile(self.tick_no) * self.rng.lognormal(0.0, 0.3)
            self.volume[s] = max(int(vol), 1)
            self.volume_history[s].append((self.tick_no, self.volume[s]))
            del self.volume_history[s][:-500]
            self._record(s)

    def _record(self, symbol: str, keep: int = 500) -> None:
        hist = self.history[symbol]
        hist.append((self.tick_no, self.mark(symbol)))
        del hist[:-keep]

    # ----- 호가 -----
    def _rebuild_book(self, symbol: str) -> None:
        inst = self.instruments[symbol]
        q = self.quote(symbol)
        base = inst.base_liquidity
        sizes = self.rng.integers(base // 2, base * 2, size=2 * BOOK_LEVELS)
        self._book[symbol] = {
            # 매수 주문은 매도호가(ask)와, 매도 주문은 매수호가(bid)와 체결된다.
            Side.BUY: [
                [inst.round_to_tick(q.ask + k * inst.tick_size), int(sizes[k])]
                for k in range(BOOK_LEVELS)
            ],
            Side.SELL: [
                [inst.round_to_tick(q.bid - k * inst.tick_size), int(sizes[BOOK_LEVELS + k])]
                for k in range(BOOK_LEVELS)
            ],
        }

    def book(self, symbol: str) -> dict[str, list[tuple[float, int]]]:
        b = self._book[symbol]
        return {
            "asks": [(p, int(v)) for p, v in b[Side.BUY]],
            "bids": [(p, int(v)) for p, v in b[Side.SELL]],
        }

    def take_liquidity(
        self, symbol: str, side: Side, qty: int, price_cap: float | None
    ) -> list[tuple[float, int]]:
        """주문 측(side)에서 호가를 소진하며 체결 목록 [(가격, 수량)]을 돌려준다.

        price_cap이 있으면 매수는 그 가격 이하, 매도는 그 가격 이상에서만 체결한다.
        """
        fills: list[tuple[float, int]] = []
        remaining = qty
        for level in self._book[symbol][side]:
            if remaining <= 0:
                break
            price, avail = level
            if price_cap is not None:
                if side is Side.BUY and price > price_cap + 1e-9:
                    break
                if side is Side.SELL and price < price_cap - 1e-9:
                    break
            take = int(min(avail, remaining))
            if take <= 0:
                continue
            level[1] -= take
            remaining -= take
            fills.append((price, take))
        return fills
```

### `rfl_oms/models.py`

```python
"""RFL OMS 도메인 모델: 종목, 주문, 체결, 포지션, 이벤트, 알림."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Side(str, Enum):
    BUY = "매수"
    SELL = "매도"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    LIMIT = "지정가"
    MARKET = "시장가"


class TimeInForce(str, Enum):
    DAY = "DAY"  # 당일 유효: 미체결 잔량은 취소 전까지 대기
    IOC = "IOC"  # 즉시 체결 후 잔량 취소


class OrderStatus(str, Enum):
    CREATED = "생성"
    VALIDATED = "검증완료"
    WORKING = "접수(미체결)"
    PARTIALLY_FILLED = "부분체결"
    FILLED = "전량체결"
    CANCELED = "취소"
    REJECTED = "거부"

    @property
    def is_open(self) -> bool:
        return self in (OrderStatus.WORKING, OrderStatus.PARTIALLY_FILLED)


class AlertLevel(str, Enum):
    INFO = "정보"
    WARNING = "경고"
    CRITICAL = "위험"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    asset_class: str
    tick_size: float
    multiplier: float  # 계약승수 (현물은 1)
    margin_rate: float  # 증거금률 (현물은 1.0 = 전액)
    venue: str
    start_price: float
    volatility: float  # 틱당 수익률 표준편차 (시뮬레이션)
    base_liquidity: int  # 호가 단계별 기본 잔량 (시뮬레이션)

    @property
    def price_decimals(self) -> int:
        text = f"{self.tick_size:.10f}".rstrip("0")
        return len(text.split(".")[1]) if "." in text else 0

    def round_to_tick(self, price: float) -> float:
        return round(round(price / self.tick_size) * self.tick_size, self.price_decimals)

    def is_on_tick(self, price: float) -> bool:
        return abs(self.round_to_tick(price) - price) < self.tick_size * 1e-6


@dataclass
class OrderEvent:
    ts: datetime
    order_id: str  # 시스템 이벤트(한도 변경, 킬 스위치 등)는 "-"
    event: str
    detail: str = ""
    actor: str = ""  # 행위자 (로그인 사용자 또는 시스템)


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: float
    ts: datetime
    fee: float = 0.0  # 수수료 + 세금 (원)


@dataclass
class Order:
    order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    qty: int
    limit_price: float | None
    account: str
    tif: TimeInForce
    created_at: datetime
    status: OrderStatus = OrderStatus.CREATED
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    venue: str = ""
    est_notional: float = 0.0
    est_margin: float = 0.0
    reject_reason: str = ""
    strategy_tag: str = ""
    trader: str = ""  # 주문을 낸 사용자
    events: list[OrderEvent] = field(default_factory=list)

    @property
    def leaves_qty(self) -> int:
        if self.status.is_open:
            return self.qty - self.filled_qty
        return 0

    def apply_fill(self, qty: int, price: float) -> None:
        total = self.avg_fill_price * self.filled_qty + price * qty
        self.filled_qty += qty
        self.avg_fill_price = total / self.filled_qty
        self.status = (
            OrderStatus.FILLED if self.filled_qty >= self.qty else OrderStatus.PARTIALLY_FILLED
        )


@dataclass
class Position:
    symbol: str
    qty: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0  # 비용 차감 전
    fees: float = 0.0  # 누적 수수료 + 세금

    def apply_fill(self, side: Side, qty: int, price: float, multiplier: float) -> float:
        """평균단가 방식으로 체결을 반영하고, 이번 체결로 실현된 손익을 돌려준다."""
        signed = side.sign * qty
        realized = 0.0
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
            new_qty = self.qty + signed
            self.avg_price = (self.avg_price * abs(self.qty) + price * qty) / abs(new_qty)
            self.qty = new_qty
        else:
            closing = min(abs(signed), abs(self.qty))
            direction = 1 if self.qty > 0 else -1
            realized = (price - self.avg_price) * closing * direction * multiplier
            remaining = abs(signed) - closing
            self.qty += side.sign * closing
            if self.qty == 0:
                self.avg_price = 0.0
            if remaining:  # 포지션 방향 전환
                self.qty = side.sign * remaining
                self.avg_price = price
        self.realized_pnl += realized
        return realized


@dataclass
class Alert:
    ts: datetime
    level: AlertLevel
    category: str
    message: str


@dataclass
class PriceAlertRule:
    rule_id: str
    symbol: str
    condition: str  # "이상" 또는 "이하"
    price: float
    active: bool = True
```

### `rfl_oms/risk.py`

```python
"""사전 리스크 점검 (pre-trade risk checks).

모든 점검은 '위험을 줄이는 주문은 허용한다'는 원칙을 따른다. 한도를 넘더라도
주문 후 노출이 주문 전보다 작으면 통과시켜, 한도 초과 상태에서도 청산이 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Instrument, Order, OrderType


@dataclass
class RiskLimits:
    capital: float = 1_000_000_000  # 계좌 기본 자본 (원)
    max_order_qty: int = 10_000  # 주문당 최대 수량
    max_order_notional: float = 500_000_000  # 주문당 최대 명목금액
    price_band_pct: float = 10.0  # 지정가와 현재가의 최대 괴리율 (%)
    max_position_notional: float = 1_000_000_000  # 종목별 최대 포지션 명목금액
    max_gross_exposure: float = 3_000_000_000  # 계좌 총 노출 한도
    max_daily_loss: float = 50_000_000  # 일일 손실 한도
    warn_ratio: float = 0.8  # 한도 대비 이 비율 이상이면 경고 알림
    restricted_symbols: frozenset[str] = field(default_factory=frozenset)
    margin_offset_enabled: bool = True  # 지수선물 ↔ 구성종목 헤지 증거금 상계
    margin_offset_pct: float = 70.0  # 헤지된 선물 증거금 감면율 (%)


@dataclass
class Exposure:
    """미체결 주문이 모두 체결된다고 가정한 최악의 노출."""

    symbol_qty: dict[str, int]
    symbol_notional: dict[str, float]
    gross: float
    margin: float  # 상계 후 순증거금
    margin_gross: float = 0.0  # 상계 전 증거금
    hedge_credit: float = 0.0  # 헤지 상계액


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    usage: float | None = None  # 한도 대비 사용률 (0~1+), 해당 없으면 None


def _fmt(v: float) -> str:
    return f"{v:,.0f}"


def static_checks(order: Order, inst: Instrument | None) -> list[CheckResult]:
    """주문 자체의 형식 검증 (시장 상태와 무관)."""
    results = [
        CheckResult("종목 확인", inst is not None, "등록된 종목" if inst else "등록되지 않은 종목"),
        CheckResult(
            "수량",
            isinstance(order.qty, int) and order.qty > 0,
            f"{order.qty}" if order.qty > 0 else "수량은 1 이상의 정수여야 합니다",
        ),
    ]
    if order.order_type is OrderType.LIMIT:
        if order.limit_price is None or order.limit_price <= 0:
            results.append(CheckResult("지정가", False, "지정가 주문에는 0보다 큰 가격이 필요합니다"))
        elif inst is not None and not inst.is_on_tick(order.limit_price):
            results.append(
                CheckResult("호가단위", False, f"가격이 호가단위 {inst.tick_size}의 배수가 아닙니다")
            )
        else:
            results.append(CheckResult("지정가", True, f"{order.limit_price}"))
    return results


def pre_trade_checks(
    order: Order,
    inst: Instrument,
    mark: float,
    ref_price: float,
    limits: RiskLimits,
    before: Exposure,
    after: Exposure,
    equity: float,
    daily_pnl: float,
    kill_switch: bool,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    increases_risk = after.gross > before.gross + 1e-6

    results.append(
        CheckResult(
            "거래 중지(킬 스위치)",
            not kill_switch,
            "킬 스위치가 켜져 있어 신규 주문이 차단됩니다" if kill_switch else "정상",
        )
    )
    restricted = order.symbol in limits.restricted_symbols
    results.append(
        CheckResult("거래 제한 종목", not restricted, "거래 제한 목록에 있는 종목" if restricted else "해당 없음")
    )

    results.append(
        CheckResult(
            "주문 수량 한도",
            order.qty <= limits.max_order_qty,
            f"{order.qty:,} / {limits.max_order_qty:,}",
            order.qty / limits.max_order_qty,
        )
    )

    notional = order.qty * ref_price * inst.multiplier
    results.append(
        CheckResult(
            "주문 명목금액 한도",
            notional <= limits.max_order_notional,
            f"{_fmt(notional)} / {_fmt(limits.max_order_notional)}",
            notional / limits.max_order_notional,
        )
    )

    if order.order_type is OrderType.LIMIT and order.limit_price:
        dev = abs(order.limit_price / mark - 1) * 100
        results.append(
            CheckResult(
                "가격 괴리율",
                dev <= limits.price_band_pct,
                f"현재가 대비 {dev:.2f}% (허용 {limits.price_band_pct:.1f}%)",
                dev / limits.price_band_pct if limits.price_band_pct else None,
            )
        )

    pos_after = after.symbol_notional.get(order.symbol, 0.0)
    pos_before = before.symbol_notional.get(order.symbol, 0.0)
    results.append(
        CheckResult(
            "종목별 포지션 한도",
            pos_after <= limits.max_position_notional or pos_after <= pos_before + 1e-6,
            f"{_fmt(pos_after)} / {_fmt(limits.max_position_notional)}",
            pos_after / limits.max_position_notional,
        )
    )

    results.append(
        CheckResult(
            "총 노출 한도",
            after.gross <= limits.max_gross_exposure or not increases_risk,
            f"{_fmt(after.gross)} / {_fmt(limits.max_gross_exposure)}",
            after.gross / limits.max_gross_exposure,
        )
    )

    results.append(
        CheckResult(
            "증거금",
            after.margin <= equity or after.margin <= before.margin + 1e-6,
            f"필요 {_fmt(after.margin)} / 평가자산 {_fmt(equity)}",
            after.margin / equity if equity > 0 else float("inf"),
        )
    )

    loss = max(-daily_pnl, 0.0) + 0.0  # -0.0 방지
    breached = loss >= limits.max_daily_loss
    results.append(
        CheckResult(
            "일일 손실 한도",
            not (breached and increases_risk),
            f"손실 {_fmt(loss)} / {_fmt(limits.max_daily_loss)}"
            + (" (위험 감소 주문만 허용)" if breached else ""),
            loss / limits.max_daily_loss,
        )
    )
    return results
```

### `rfl_oms/storage.py`

```python
"""SQLite 저장소.

두 층으로 저장한다.
1) 조회용 장부 테이블: users, auth_log, orders, fills, positions, audit, alerts
   — 외부 도구(SQL)로 그대로 조회·검증할 수 있다.
2) 엔진 스냅샷(state 테이블): 시장·알고·바스켓·차익 상태까지 정확히 복원하기 위한 직렬화 데이터.

스냅샷은 pickle 형식이므로 이 프로그램이 만든 DB 파일만 사용해야 한다(외부에서 받은 DB를 열지 말 것).
"""

from __future__ import annotations

import pickle
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .auth import (
    MAX_FAILED,
    AuthError,
    Role,
    User,
    hash_password,
    lock_until,
    validate_new_password,
    validate_username,
    verify_password,
)
from .engine import OMS

STATE_VERSION = 4  # 엔진 구조가 바뀌면 올린다 (다른 버전 스냅샷은 복원하지 않음)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, username TEXT, event TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    created_at TEXT, symbol TEXT, side TEXT, order_type TEXT, tif TEXT,
    qty INTEGER, limit_price REAL, status TEXT, filled_qty INTEGER, avg_fill_price REAL,
    trader TEXT, strategy_tag TEXT, venue TEXT, reject_reason TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    seq INTEGER PRIMARY KEY,
    ts TEXT, order_id TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL, fee REAL
);
CREATE TABLE IF NOT EXISTS positions (
    symbol TEXT PRIMARY KEY,
    qty INTEGER, avg_price REAL, realized_pnl REAL, fees REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY,
    ts TEXT, order_id TEXT, event TEXT, detail TEXT, actor TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    seq INTEGER PRIMARY KEY,
    ts TEXT, level TEXT, category TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY, value BLOB, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_order ON audit(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id);
"""


def _ts(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="milliseconds") if dt else None


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")  # 브라우저(Pyodide) 등 지원하지 않는 환경에서는 기본 모드
        except sqlite3.DatabaseError:
            pass
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            cur.row_factory = sqlite3.Row
            return cur.fetchall()

    # ============================ 엔진 저장·복원 ============================
    def _count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 (내부 상수 테이블명)

    def save(self, oms: OMS) -> None:
        """장부 테이블에 새 변경분을 반영하고 엔진 스냅샷을 갱신한다 (하나의 트랜잭션)."""
        now = _ts(datetime.now())
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                dirty = [oms.orders[i] for i in sorted(oms._dirty_orders) if i in oms.orders]
                c.executemany(
                    """INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(order_id) DO UPDATE SET
                         qty=excluded.qty, limit_price=excluded.limit_price, status=excluded.status,
                         filled_qty=excluded.filled_qty, avg_fill_price=excluded.avg_fill_price,
                         venue=excluded.venue, reject_reason=excluded.reject_reason, updated_at=excluded.updated_at""",
                    [
                        (
                            o.order_id, _ts(o.created_at), o.symbol, o.side.value, o.order_type.value, o.tif.value,
                            o.qty, o.limit_price, o.status.value, o.filled_qty, o.avg_fill_price,
                            o.trader, o.strategy_tag, o.venue, o.reject_reason, now,
                        )
                        for o in dirty
                    ],
                )
                n = self._count("fills")
                c.executemany(
                    "INSERT INTO fills VALUES (?,?,?,?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(f.ts), f.order_id, f.symbol, f.side.value, f.qty, f.price, f.fee)
                        for k, f in enumerate(oms.fills[n:])
                    ],
                )
                n = self._count("audit")
                c.executemany(
                    "INSERT INTO audit VALUES (?,?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(e.ts), e.order_id, e.event, e.detail, e.actor)
                        for k, e in enumerate(oms.audit[n:])
                    ],
                )
                n = self._count("alerts")
                c.executemany(
                    "INSERT INTO alerts VALUES (?,?,?,?,?)",
                    [
                        (n + k + 1, _ts(a.ts), a.level.value, a.category, a.message)
                        for k, a in enumerate(oms.alerts[n:])
                    ],
                )
                c.execute("DELETE FROM positions")
                c.executemany(
                    "INSERT INTO positions VALUES (?,?,?,?,?,?)",
                    [
                        (p.symbol, p.qty, p.avg_price, p.realized_pnl, p.fees, now)
                        for p in oms.positions.values()
                        if p.qty or p.realized_pnl or p.fees
                    ],
                )
                oms._dirty_orders.clear()
                blob = pickle.dumps(oms, protocol=pickle.HIGHEST_PROTOCOL)
                c.execute(
                    "INSERT INTO state VALUES ('oms', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (blob, now),
                )
                c.execute(
                    "INSERT INTO state VALUES ('version', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (str(STATE_VERSION), now),
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def load(self) -> OMS | None:
        """저장된 엔진을 복원한다. 없거나 버전이 다르면 None."""
        with self._lock:
            ver = self._conn.execute("SELECT value FROM state WHERE key='version'").fetchone()
            row = self._conn.execute("SELECT value FROM state WHERE key='oms'").fetchone()
        if not row or not ver or str(ver[0]) != str(STATE_VERSION):
            return None
        return pickle.loads(row[0])  # noqa: S301 (이 프로그램이 만든 로컬 DB만 사용)

    def reset_trading(self) -> None:
        """거래 데이터만 지운다 (사용자·로그인 기록은 유지)."""
        with self._lock:
            self._conn.executescript(
                "BEGIN; DELETE FROM orders; DELETE FROM fills; DELETE FROM positions; "
                "DELETE FROM audit; DELETE FROM alerts; DELETE FROM state; COMMIT;"
            )

    # ============================ 사용자 ============================
    def has_users(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def log_auth(self, username: str | None, event: str, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO auth_log (ts, username, event, detail) VALUES (?,?,?,?)",
                (_ts(datetime.now()), username, event, detail),
            )

    def create_user(self, username: str, display_name: str, role: Role, password: str, by: str = "") -> User:
        username = username.strip()
        validate_username(username)
        validate_new_password(password)
        if not display_name.strip():
            raise AuthError("이름을 입력하세요")
        pw_hash, salt = hash_password(password)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users (username, display_name, role, pw_hash, salt, created_at) VALUES (?,?,?,?,?,?)",
                    (username, display_name.strip(), role.value, pw_hash, salt, _ts(datetime.now())),
                )
            except sqlite3.IntegrityError as e:
                raise AuthError("이미 있는 아이디입니다") from e
        self.log_auth(username, "계정 생성", f"역할 {role.value}, 생성자 {by or '초기 설정'}")
        return User(username, display_name.strip(), role)

    def _row_to_user(self, r) -> User:
        return User(r["username"], r["display_name"], Role(r["role"]), bool(r["active"]))

    def get_user(self, username: str) -> User | None:
        rows = self.query("SELECT * FROM users WHERE username=?", (username,))
        return self._row_to_user(rows[0]) if rows else None

    def list_users(self) -> list[sqlite3.Row]:
        return self.query(
            "SELECT username, display_name, role, active, failed_count, locked_until, created_at FROM users ORDER BY created_at"
        )

    def authenticate(self, username: str, password: str) -> User:
        """성공하면 User, 실패하면 AuthError. 실패 횟수와 잠금을 관리한다."""
        rows = self.query("SELECT * FROM users WHERE username=?", (username.strip(),))
        if not rows:
            self.log_auth(username, "로그인 실패", "없는 아이디")
            raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다")
        r = rows[0]
        now = datetime.now()
        if r["locked_until"] and datetime.fromisoformat(r["locked_until"]) > now:
            self.log_auth(username, "로그인 거부", "잠긴 계정")
            raise AuthError("로그인 실패가 반복되어 잠긴 계정입니다. 잠시 후 다시 시도하거나 관리자에게 문의하세요")
        if not r["active"]:
            self.log_auth(username, "로그인 거부", "비활성 계정")
            raise AuthError("비활성화된 계정입니다")
        if not verify_password(password, r["pw_hash"], r["salt"]):
            failed = r["failed_count"] + 1
            locked = _ts(lock_until(now)) if failed >= MAX_FAILED else None
            with self._lock:
                self._conn.execute(
                    "UPDATE users SET failed_count=?, locked_until=? WHERE username=?",
                    (0 if locked else failed, locked, r["username"]),
                )
            self.log_auth(username, "로그인 실패", "비밀번호 불일치" + (" → 계정 잠금" if locked else f" ({failed}/{MAX_FAILED})"))
            raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다")
        with self._lock:
            self._conn.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE username=?", (r["username"],))
        self.log_auth(r["username"], "로그인", "")
        return self._row_to_user(r)

    def update_user(self, username: str, *, role: Role | None = None, active: bool | None = None, by: str = "") -> None:
        user = self.get_user(username)
        if user is None:
            raise AuthError("없는 사용자입니다")
        new_role = role or user.role
        new_active = user.active if active is None else active
        if user.role is Role.ADMIN and (new_role is not Role.ADMIN or not new_active):
            admins = self.query("SELECT COUNT(*) AS n FROM users WHERE role=? AND active=1", (Role.ADMIN.value,))[0]["n"]
            if admins <= 1:
                raise AuthError("마지막 활성 관리자는 역할을 바꾸거나 비활성화할 수 없습니다")
        with self._lock:
            self._conn.execute(
                "UPDATE users SET role=?, active=? WHERE username=?", (new_role.value, int(new_active), username)
            )
        self.log_auth(username, "계정 변경", f"역할 {new_role.value}, {'활성' if new_active else '비활성'}, 변경자 {by}")

    def set_password(self, username: str, password: str, by: str = "") -> None:
        validate_new_password(password)
        pw_hash, salt = hash_password(password)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE users SET pw_hash=?, salt=?, failed_count=0, locked_until=NULL WHERE username=?",
                (pw_hash, salt, username),
            )
        if cur.rowcount == 0:
            raise AuthError("없는 사용자입니다")
        self.log_auth(username, "비밀번호 변경", f"변경자 {by}")

    def unlock(self, username: str, by: str = "") -> None:
        with self._lock:
            self._conn.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE username=?", (username,))
        self.log_auth(username, "잠금 해제", f"변경자 {by}")
```

### `run.sh`

```
#!/usr/bin/env bash
# RFL OMS 실행 (macOS / Linux). Python 3.10 이상 필요.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt
streamlit run app.py
```

### `run_windows.bat`

```
@echo off
REM RFL OMS 실행 (Windows). Python 3.10 이상 필요.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
streamlit run app.py
```

### `stockbasic`

(기존 파일 — 내용은 줄바꿈 1개뿐인 빈 파일입니다)

```

```

### `tests/test_engine.py`

```python
import pytest

from rfl_oms import OMS, AlertLevel, MarketSim, OrderStatus, OrderType, RiskLimits, Side, TimeInForce
from rfl_oms.models import Position


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=1))


def statuses(order):
    return [e.event for e in order.events]


def test_market_buy_fills_and_updates_position(oms):
    ask = oms.market.quote("005930").ask
    o = oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    assert o.status is OrderStatus.FILLED
    assert o.avg_fill_price == ask
    assert oms.positions["005930"].qty == 100
    assert statuses(o)[:4] == ["생성", "검증 통과", "보강", "라우팅"]


def test_passive_limit_rests_then_fills_when_market_moves(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    assert o.status is OrderStatus.WORKING
    oms.market.set_price("005930", q.bid - 1_000)  # 매도호가가 지정가 아래로 내려옴
    for order in oms.open_orders():
        oms._match(order)
    assert o.status is OrderStatus.FILLED
    assert o.avg_fill_price <= q.bid - 500


def test_partial_fill_and_ioc_remainder_canceled():
    big = 10**13
    oms = OMS(
        market=MarketSim(seed=1),
        limits=RiskLimits(capital=big, max_order_notional=big, max_position_notional=big, max_gross_exposure=big),
    )
    book = oms.market.book("K200F")["asks"]
    top_px, top_qty = book[0]
    o = oms.submit(
        "K200F", Side.BUY, OrderType.LIMIT, top_qty + 5, limit_price=top_px, tif=TimeInForce.IOC
    )
    assert o.filled_qty == top_qty
    assert o.status is OrderStatus.CANCELED
    assert "취소" in statuses(o)


def test_order_qty_limit_rejects(oms):
    o = oms.submit("005930", Side.BUY, OrderType.MARKET, 20_000)
    assert o.status is OrderStatus.REJECTED
    assert "주문 수량 한도" in o.reject_reason
    assert any(a.category == "주문 거부" for a in oms.alerts)


def test_off_tick_price_rejected(oms):
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 1, limit_price=72_050)
    assert o.status is OrderStatus.REJECTED
    assert "호가단위" in o.reject_reason


def test_price_band(oms):
    mark = oms.market.mark("005930")
    far = oms.instruments["005930"].round_to_tick(mark * 0.8)
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 1, limit_price=far)
    assert "가격 괴리율" in o.reject_reason


def test_margin_limit_and_risk_reducing_order_allowed():
    oms = OMS(market=MarketSim(seed=2), limits=RiskLimits(capital=100_000_000))
    first = oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)  # 약 7,200만원
    assert first.status is OrderStatus.FILLED
    second = oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert second.status is OrderStatus.REJECTED and "증거금" in second.reject_reason
    sell = oms.submit("005930", Side.SELL, OrderType.MARKET, 500)
    assert sell.status is OrderStatus.FILLED


def test_daily_loss_blocks_only_risk_increasing():
    oms = OMS(market=MarketSim(seed=3), limits=RiskLimits(max_daily_loss=1_000_000))
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    oms.market.set_price("005930", oms.market.quote("005930").bid - 2_000)  # 약 -200만원
    oms._evaluate_alerts()
    assert any(a.level is AlertLevel.CRITICAL and "일일 손실" in a.message for a in oms.alerts)
    more = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
    assert more.status is OrderStatus.REJECTED and "일일 손실" in more.reject_reason
    close = oms.submit("005930", Side.SELL, OrderType.MARKET, 1_000)
    assert close.status is OrderStatus.FILLED


def test_amend_and_cancel(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    ok, _ = oms.amend(o.order_id, new_qty=20, new_limit_price=q.bid - 300)
    assert ok and o.qty == 20 and o.limit_price == q.bid - 300
    ok, _ = oms.amend(o.order_id, new_qty=99_999)
    assert not ok and o.qty == 20
    assert oms.cancel(o.order_id)
    assert o.status is OrderStatus.CANCELED and o.leaves_qty == 0
    assert not oms.cancel(o.order_id)


def test_amend_to_marketable_price_fills(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    oms.amend(o.order_id, new_limit_price=q.ask)
    assert o.status is OrderStatus.FILLED


def test_kill_switch_cancels_and_blocks(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    oms.set_kill_switch(True)
    assert o.status is OrderStatus.CANCELED
    blocked = oms.submit("005930", Side.BUY, OrderType.MARKET, 1)
    assert blocked.status is OrderStatus.REJECTED
    oms.set_kill_switch(False)
    assert oms.submit("005930", Side.BUY, OrderType.MARKET, 1).status is OrderStatus.FILLED


def test_restricted_symbol():
    oms = OMS(limits=RiskLimits(restricted_symbols=frozenset({"GOLD"})))
    assert oms.submit("GOLD", Side.BUY, OrderType.MARKET, 1).status is OrderStatus.REJECTED


def test_preview_does_not_create_order(oms):
    checks = oms.preview("005930", Side.BUY, OrderType.MARKET, 10)
    assert all(c.passed for c in checks)
    assert oms.orders == {}
    assert oms.submit("005930", Side.BUY, OrderType.MARKET, 1).order_id == "O000001"


def test_position_flip_realized_pnl():
    p = Position("X")
    p.apply_fill(Side.BUY, 10, 100.0, 1)
    realized = p.apply_fill(Side.SELL, 15, 110.0, 1)
    assert realized == 100.0
    assert p.qty == -5 and p.avg_price == 110.0


def test_futures_multiplier_pnl(oms):
    o = oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    entry = o.avg_fill_price
    oms.market.set_price("K200F", entry + 1.0)
    expected = (oms.market.mark("K200F") - entry) * 250_000
    assert oms.unrealized_pnl("K200F") == pytest.approx(expected)


def test_price_alert_rule_triggers_once(oms):
    mark = oms.market.mark("USDF")
    oms.add_price_rule("USDF", "이상", mark + 0.5)
    oms.market.set_price("USDF", mark + 5)
    oms._check_price_rules()
    oms._check_price_rules()
    assert sum(a.category == "가격 알림" for a in oms.alerts) == 1


def test_warning_alert_dedup(oms):
    oms.limits.max_gross_exposure = 100_000_000
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_200)  # 약 8,640만원 → 86%
    oms.step(3)
    warnings = [a for a in oms.alerts if "총 노출" in a.message]
    assert len(warnings) >= 1
    assert len({a.level for a in warnings}) == len(warnings)  # 같은 단계 알림 중복 없음


def test_simulation_runs(oms):
    oms.submit("USDF", Side.SELL, OrderType.LIMIT, 5, limit_price=oms.market.quote("USDF").ask + 0.3)
    oms.step(200)
    assert oms.market.tick_no == 200


def test_amend_without_change_is_rejected(oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    ok, msg = oms.amend(o.order_id, new_qty=10, new_limit_price=q.bid - 500)
    assert not ok and "변경" in msg
```

### `tests/test_phase2.py`

```python
import pandas as pd
import pytest

from rfl_oms import OMS, AlgoStatus, AlgoType, ExecMode, ExecParams, MarketSim, OrderStatus, RiskLimits, Side
from rfl_oms.basket import normalize_symbol, parse_side, sample_template


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=11))


# ------------------------------ 알고리즘 ------------------------------
def test_twap_tracks_linear_schedule(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    for k in range(1, 31):
        oms.step()
        if k in (10, 20):
            assert abs(oms.algos.filled(algo) - 3_000 * k / 30) <= 1
    assert algo.status is AlgoStatus.DONE
    assert oms.positions["005930"].qty == 3_000
    assert all(oms.orders[i].strategy_tag == algo.algo_id for i in algo.child_ids)


def test_vwap_front_loads_at_session_open(oms):
    vwap = oms.algos.start("005930", Side.BUY, 6_000, AlgoType.VWAP, duration=60)
    twap = oms.algos.start("000660", Side.BUY, 1_000, AlgoType.TWAP, duration=60)
    oms.step(15)
    # 장 시작 구간은 거래량이 많으므로 VWAP 진행률이 TWAP보다 빠르다
    assert oms.algos.filled(vwap) / 6_000 > oms.algos.filled(twap) / 1_000
    oms.step(45)
    assert vwap.status is AlgoStatus.DONE


def test_pov_follows_market_volume(oms):
    big = 10**13
    oms.limits = RiskLimits(capital=big, max_order_qty=10**9, max_order_notional=big, max_position_notional=big, max_gross_exposure=big)
    algo = oms.algos.start("005930", Side.SELL, 50_000, AlgoType.POV, duration=20, participation=0.1)
    oms.step(20)
    expected = int(algo.mkt_volume * 0.1)
    assert expected > 0
    assert abs(oms.algos.filled(algo) - expected) <= 1
    assert algo.status is AlgoStatus.EXPIRED


def test_algo_limit_price_blocks_children(oms):
    ask = oms.market.quote("005930").ask
    algo = oms.algos.start("005930", Side.BUY, 1_000, AlgoType.TWAP, duration=10, limit_price=ask - 5_000)
    oms.step(10)
    assert oms.algos.filled(algo) == 0 and algo.child_ids == []


def test_algo_parent_risk_check_and_reservation():
    oms = OMS(market=MarketSim(seed=5), limits=RiskLimits(capital=100_000_000))
    big = oms.algos.start("005930", Side.BUY, 5_000, AlgoType.TWAP, duration=10)  # 약 3.6억
    assert big.status is AlgoStatus.HALTED and "증거금" in big.halt_reason
    ok = oms.algos.start("005930", Side.BUY, 1_000, AlgoType.TWAP, duration=10)
    assert ok.status is AlgoStatus.RUNNING
    # 알고 잔량은 노출에 잡히므로 같은 방향 추가 주문 여력이 줄어든다
    assert oms.exposure().symbol_qty["005930"] == 1_000


def test_algo_pause_resume_cancel(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    oms.step(5)
    oms.algos.pause(algo.algo_id)
    before = oms.algos.filled(algo)
    oms.step(5)
    assert oms.algos.filled(algo) == before
    oms.algos.resume(algo.algo_id)
    oms.step(1)
    assert oms.algos.filled(algo) > before  # 밀린 목표를 따라잡음
    oms.algos.cancel(algo.algo_id)
    oms.step(5)
    assert algo.status is AlgoStatus.CANCELED
    assert oms.exposure().symbol_qty["005930"] == oms.positions["005930"].qty


def test_kill_switch_cancels_algos(oms):
    algo = oms.algos.start("005930", Side.BUY, 3_000, AlgoType.TWAP, duration=30)
    oms.set_kill_switch(True)
    assert algo.status is AlgoStatus.CANCELED


def test_slippage_sign(oms):
    algo = oms.algos.start("005930", Side.BUY, 300, AlgoType.TWAP, duration=3)
    oms.step(3)
    slip = oms.algos.slippage_bps(algo, algo.arrival_price)
    expected = (oms.algos.avg_price(algo) / algo.arrival_price - 1) * 1e4
    assert slip == pytest.approx(expected)


# ------------------------------ 바스켓 ------------------------------
def test_parse_helpers():
    assert parse_side("buy") is Side.BUY and parse_side("매도") is Side.SELL
    assert normalize_symbol(5930) == "005930" and normalize_symbol("5930.0") == "005930"
    with pytest.raises(ValueError):
        parse_side("hold")


def test_build_by_qty_with_errors(oms):
    df = pd.DataFrame({"종목코드": ["005930", "XXXX", "000660"], "구분": ["매수", "매수", "보유"], "수량": [10, 5, 3]})
    lines, errors = oms.baskets.build_lines(df, by="수량")
    assert [ln.symbol for ln in lines] == ["005930"]
    assert len(errors) == 2


def test_build_by_weight(oms):
    lines, errors = oms.baskets.build_lines(sample_template(), by="비중", target_notional=100_000_000)
    assert not errors
    total = sum(ln.qty * oms.market.mark(ln.symbol) for ln in lines)
    assert 95_000_000 < total <= 100_000_000
    samsung = next(ln for ln in lines if ln.symbol == "005930")
    assert samsung.qty == int(30_000_000 // oms.market.mark("005930"))


def test_weight_requires_target(oms):
    lines, errors = oms.baskets.build_lines(sample_template(), by="비중")
    assert not lines and errors


def test_one_click_market_basket(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("테스트", lines, ExecParams(mode=ExecMode.MARKET))
    s = oms.baskets.summary(b)
    assert s["수량 체결률"] == 1.0 and s["완료 종목"] == 5
    assert all(oms.orders[i].strategy_tag == b.basket_id for ln in b.lines for i in ln.order_ids)


def test_basket_risk_rejection_flags_line_and_alerts():
    oms = OMS(market=MarketSim(seed=3), limits=RiskLimits(restricted_symbols=frozenset({"000660"})))
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("제한 포함", lines, ExecParams())
    bad = next(ln for ln in b.lines if ln.symbol == "000660")
    assert "거래 제한" in bad.error
    assert oms.baskets.line_status(bad) == "거부"
    assert any(a.category == "바스켓 실행" and "거부 1건" in a.message for a in oms.alerts)


def test_auto_retry_when_liquidity_short(oms):
    top = sum(v for _, v in oms.market.book("005380")["asks"])
    lines, _ = oms.baskets.build_lines(
        pd.DataFrame({"종목코드": ["005380"], "구분": ["매수"], "수량": [top + 100]}), by="수량"
    )
    big = 10**13
    oms.limits = RiskLimits(capital=big, max_order_qty=10**9, max_order_notional=big, max_position_notional=big, max_gross_exposure=big)
    b = oms.baskets.execute("유동성", lines, ExecParams(mode=ExecMode.MARKET, auto_retry=True))
    ln = b.lines[0]
    assert oms.baskets.line_filled(ln)[0] == top  # 5단계 호가 소진
    oms.step(1)
    assert ln.retries == 1 and oms.baskets.line_filled(ln)[0] == ln.qty


def test_passive_basket_cancel_reprice_retry(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("패시브", lines, ExecParams(mode=ExecMode.PASSIVE, offset_ticks=10))
    assert oms.baskets.summary(b)["진행 중 수량"] == sum(ln.qty for ln in lines)
    b.params.offset_ticks = 0
    assert oms.baskets.reprice(b.basket_id) == 5
    assert oms.baskets.cancel(b.basket_id) == 5
    assert all(oms.orders[i].status is OrderStatus.CANCELED for ln in b.lines for i in ln.order_ids)
    b.params.mode = ExecMode.MARKET
    assert oms.baskets.retry(b.basket_id) == 5
    assert oms.baskets.summary(b)["수량 체결률"] == 1.0


def test_algo_basket(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("TWAP 바스켓", lines, ExecParams(mode=ExecMode.TWAP, duration=10))
    assert all(len(ln.algo_ids) == 1 for ln in b.lines)
    oms.step(10)
    assert oms.baskets.summary(b)["수량 체결률"] == 1.0


def test_templates(oms):
    oms.baskets.save_template("코어5", sample_template())
    df = oms.baskets.load_template("코어5")
    df.loc[0, "수량"] = 1
    assert oms.baskets.load_template("코어5").loc[0, "수량"] == 500  # 원본 보존


def test_amount_fill_rate_ignores_price_moves(oms):
    lines, _ = oms.baskets.build_lines(sample_template(), by="수량")
    b = oms.baskets.execute("가격변동", lines, ExecParams(mode=ExecMode.MARKET))
    oms.market.set_price("005930", oms.market.mark("005930") * 1.05)
    assert oms.baskets.summary(b)["금액 체결률"] == pytest.approx(1.0)
```

### `tests/test_phase3.py`

```python
import pytest

from rfl_oms import OMS, ArbDirection, ArbStatus, MarketSim, RiskLimits, Side
from rfl_oms.analytics import exposure_by_asset_class, stress_test, value_at_risk
from rfl_oms.models import OrderType

BIG = 10**13


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=21))


def roomy(oms):
    oms.limits = RiskLimits(
        capital=BIG, max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG
    )


# ------------------------------ 시장·지수 ------------------------------
def test_futures_tracks_fair_value(oms):
    devs = []
    for _ in range(300):
        oms.market.step()
        devs.append(oms.market.mark("K200F") - oms.market.fair_futures())
    assert abs(sum(devs) / len(devs)) < 0.3
    assert max(abs(d) for d in devs) < 3.0


def test_index_unit_replicates_one_contract(oms):
    idx = oms.market.index_def
    basket_value = sum(q * oms.market.mark(s) for s, q in idx.constituents.items())
    futures_notional = oms.market.index_value() * oms.instruments["K200F"].multiplier
    assert basket_value == pytest.approx(futures_notional)


def test_fair_value_carry(oms):
    idx = oms.market.index_def
    assert idx.fair_futures(100.0) == pytest.approx(100 * (1 + (0.035 - 0.015) * 30 / 365))


def test_equities_are_correlated(oms):
    import numpy as np

    for _ in range(300):
        oms.market.step()
    a = np.diff(np.log([p for _, p in oms.market.history["005930"]]))
    b = np.diff(np.log([p for _, p in oms.market.history["000660"]]))
    assert np.corrcoef(a, b)[0, 1] > 0.2


# ------------------------------ 차익거래 ------------------------------
def test_snapshot_edges(oms):
    snap = oms.arb.snapshot()
    assert snap.sell_edge == pytest.approx(snap.fut_bid - snap.fair - snap.cost_pts)
    assert snap.buy_edge == pytest.approx(snap.fair - snap.fut_ask - snap.cost_pts)
    assert snap.cost_pts == pytest.approx(snap.index * oms.arb.costs.round_trip_bps() / 1e4)


def test_sell_arb_enter_is_hedged_and_close_flattens(oms):
    roomy(oms)
    pos, problems = oms.arb.enter(ArbDirection.SELL_ARB, 2)
    assert not problems and pos.status is ArbStatus.OPEN
    net = oms.arb.net_holdings(pos)
    assert net["K200F"] == -2
    assert net["005930"] == 2 * oms.market.index_def.constituents["005930"]
    fut, stock = oms.arb.hedge(pos)
    assert abs(fut + stock) / abs(fut) < 0.01  # 반올림 오차 수준
    oms.step(5)
    assert oms.arb.close(pos.arb_id)
    assert all(q == 0 for q in oms.arb.net_holdings(pos).values())
    assert pos.status is ArbStatus.CLOSED
    assert not oms.arb.close(pos.arb_id)


def test_arb_pnl_matches_positions(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.BUY_ARB, 1)
    oms.step(3)
    # 이 계좌의 유일한 거래이므로 계좌 손익과 같아야 한다
    assert oms.arb.pnl_net(pos) == pytest.approx(oms.daily_pnl())
    assert oms.arb.fees(pos) > 0


def test_arb_rejected_when_any_leg_fails_precheck(oms):
    oms.limits = RiskLimits(restricted_symbols=frozenset({"000660"}))
    pos, problems = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    assert pos is None and any("000660" in p for p in problems)
    assert oms.orders == {}  # 어느 레그도 나가지 않음


def test_auto_entry_and_exit(oms):
    roomy(oms)
    s = oms.arb.settings
    s.auto, s.entry_edge_pts, s.max_open = True, -100.0, 1  # 항상 진입 조건 충족
    oms.step(1)
    assert len(oms.arb.positions) == 1
    pos = next(iter(oms.arb.positions.values()))
    s.entry_edge_pts = 100.0  # 재진입 금지
    s.exit_mispricing_pts = 100.0  # 즉시 청산 조건
    oms.step(1)
    assert pos.status is ArbStatus.CLOSED and "자동" in pos.note


def test_leg_error_detected(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    basket = oms.baskets.baskets[pos.basket_ids[0]]
    basket.lines[0].error = "테스트 실패"
    oms.arb._check_legs(pos, False, basket)
    assert pos.status is ArbStatus.LEG_ERROR
    assert any(a.category == "차익 레그 불일치" for a in oms.alerts)


# ------------------------------ 리스크 분석 ------------------------------
def test_exposure_by_asset_class(oms):
    roomy(oms)
    oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    df = exposure_by_asset_class(oms).set_index("자산군")
    assert df.loc["주식", "매수"] > 0 and df.loc["주가지수선물", "매도"] < 0
    assert df.loc["주가지수선물", "총노출"] == pytest.approx(abs(df.loc["주가지수선물", "순노출"]))


def test_var_needs_history_then_positive(oms):
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert value_at_risk(oms).historical is None
    oms.step(60)
    v = value_at_risk(oms)
    assert v.historical > 0 and v.parametric > 0 and v.observations >= 20


def test_hedged_book_has_lower_var(oms):
    roomy(oms)
    oms.step(80)
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    naked = value_at_risk(oms).parametric
    for s, q in oms.market.index_def.constituents.items():
        oms.submit(s, Side.BUY, OrderType.MARKET, q)
    hedged = value_at_risk(oms).parametric
    assert hedged < naked * 0.8


def test_stress_test(oms):
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    df = stress_test(oms).set_index("시나리오")
    notional = 1_000 * oms.market.mark("005930")
    assert df.loc["주가 급락 (−5%)", "예상 손익"] == pytest.approx(-0.05 * notional)
    assert df.loc["금 급락 (−5%)", "예상 손익"] == 0


def test_pnl_history_recorded(oms):
    oms.step(5)
    assert len(oms.pnl_history) == 6 and oms.pnl_history[-1][0] == 5
```

### `tests/test_phase4.py`

```python
import pytest

from rfl_oms import OMS, AlgoType, ArbDirection, MarketSim, RiskLimits, Side
from rfl_oms.auth import ROLE_PERMS, AuthError, Perm, Role
from rfl_oms.fees import FeeSchedule
from rfl_oms.models import OrderType
from rfl_oms.storage import Store

BIG = 10**13


@pytest.fixture
def oms():
    return OMS(market=MarketSim(seed=31))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def roomy(oms):
    oms.limits = RiskLimits(
        capital=BIG, max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG
    )


# ------------------------------ 거래비용 ------------------------------
def test_fees_per_fill_and_net_pnl(oms):
    buy = oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
    sell = oms.submit("005930", Side.SELL, OrderType.MARKET, 100)
    f_buy, f_sell = oms.fills[0], oms.fills[1]
    assert f_buy.fee == pytest.approx(100 * buy.avg_fill_price * 1.0 / 1e4)  # 수수료 1bp
    assert f_sell.fee == pytest.approx(100 * sell.avg_fill_price * 16.0 / 1e4)  # 수수료 1bp + 매도세 15bp
    gross = oms.realized_pnl()
    assert oms.daily_pnl() == pytest.approx(gross - f_buy.fee - f_sell.fee)
    assert oms.positions["005930"].fees == pytest.approx(f_buy.fee + f_sell.fee)


def test_futures_fee_and_disable(oms):
    o = oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    assert oms.fills[-1].fee == pytest.approx(o.avg_fill_price * 250_000 * 0.3 / 1e4)
    oms.set_fees(FeeSchedule(enabled=False))
    oms.submit("K200F", Side.SELL, OrderType.MARKET, 1)
    assert oms.fills[-1].fee == 0
    assert any(e.event == "수수료 변경" for e in oms.audit)


def test_fees_count_toward_loss_limit():
    oms = OMS(market=MarketSim(seed=1), limits=RiskLimits(max_daily_loss=100_000))
    for _ in range(3):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
        oms.submit("005930", Side.SELL, OrderType.MARKET, 1_000)
    assert oms.daily_pnl() < -100_000  # 왕복 비용 + 스프레드로 손실 한도 초과
    blocked = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
    assert "일일 손실" in blocked.reject_reason


# ------------------------------ 헤지 증거금 상계 ------------------------------
def test_hedge_credit_reduces_margin(oms):
    roomy(oms)
    pos, _ = oms.arb.enter(ArbDirection.SELL_ARB, 1)
    mb = oms.margin_breakdown()
    fut_margin = abs(oms.positions["K200F"].qty) * oms.market.mark("K200F") * 250_000 * 0.10
    assert mb["헤지 상계"] == pytest.approx(min(fut_margin, mb["헤지 상계"] / 0.7 * 0.7))
    assert 0 < mb["헤지 상계"] <= fut_margin * 0.7 + 1
    assert mb["순증거금"] == pytest.approx(mb["상계 전"] - mb["헤지 상계"])
    oms.limits.margin_offset_enabled = False
    assert oms.margin_breakdown()["헤지 상계"] == 0


def test_no_credit_for_same_direction(oms):
    roomy(oms)
    oms.submit("K200F", Side.BUY, OrderType.MARKET, 1)
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1_000)
    assert oms.margin_breakdown()["헤지 상계"] == 0


def test_working_order_that_breaks_hedge_removes_credit(oms):
    roomy(oms)
    oms.arb.enter(ArbDirection.SELL_ARB, 1)
    with_credit = oms.exposure().hedge_credit
    assert with_credit > 0
    # 선물을 되사는 미체결 주문이 있으면 헤지가 깨질 수 있으므로 상계를 인정하지 않는다
    bid = oms.market.quote("K200F").bid
    oms.submit("K200F", Side.BUY, OrderType.LIMIT, 1, limit_price=round(bid - 1.0, 2))
    assert oms.exposure().hedge_credit == 0


def test_hedge_credit_frees_room_for_orders():
    lim = dict(max_order_qty=10**9, max_order_notional=BIG, max_position_notional=BIG, max_gross_exposure=BIG)
    a = OMS(market=MarketSim(seed=4), limits=RiskLimits(capital=200_000_000, **lim))
    a.arb.enter(ArbDirection.SELL_ARB, 1)
    b = OMS(market=MarketSim(seed=4), limits=RiskLimits(capital=200_000_000, margin_offset_enabled=False, **lim))
    b.arb.enter(ArbDirection.SELL_ARB, 1)
    assert a.exposure().margin < b.exposure().margin


# ------------------------------ 행위자 기록 ------------------------------
def test_actor_recorded_on_orders_algos_and_system_events(oms):
    roomy(oms)
    with oms.acting("kim"):
        o = oms.submit("005930", Side.BUY, OrderType.MARKET, 10)
        algo = oms.algos.start("000660", Side.BUY, 300, AlgoType.TWAP, duration=3)
    oms.step(3)  # 틱 처리 중의 자식 주문은 알고를 시작한 사용자로 기록
    with oms.acting("risk1"):
        oms.set_kill_switch(True)
        oms.set_kill_switch(False)
    assert o.trader == "kim" and all(e.actor == "kim" for e in o.events)
    assert all(oms.orders[i].trader == "kim" for i in algo.child_ids) and algo.child_ids
    ks = [e for e in oms.audit if e.event == "킬 스위치"]
    assert len(ks) == 2 and all(e.actor == "risk1" and e.order_id == "-" for e in ks)


def test_set_limits_is_audited(oms):
    with oms.acting("risk1"):
        oms.set_limits(RiskLimits(max_order_qty=500))
    ev = [e for e in oms.audit if e.event == "한도 변경"][-1]
    assert "max_order_qty: 10000 → 500" in ev.detail and ev.actor == "risk1"


# ------------------------------ 권한 ------------------------------
def test_segregation_of_duties():
    assert Perm.TRADE in ROLE_PERMS[Role.TRADER]
    assert Perm.TRADE not in ROLE_PERMS[Role.RISK] and Perm.TRADE not in ROLE_PERMS[Role.ADMIN]
    assert Perm.SET_LIMITS in ROLE_PERMS[Role.RISK] and Perm.SET_LIMITS not in ROLE_PERMS[Role.TRADER]
    assert Perm.MANAGE_USERS in ROLE_PERMS[Role.ADMIN] and Perm.MANAGE_USERS not in ROLE_PERMS[Role.RISK]


# ------------------------------ 사용자·로그인 ------------------------------
def test_create_and_authenticate(store):
    assert not store.has_users()
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    assert store.has_users()
    u = store.authenticate("admin", "Secret123")
    assert u.role is Role.ADMIN and u.can(Perm.MANAGE_USERS)
    row = store.query("SELECT pw_hash, salt FROM users WHERE username='admin'")[0]
    assert "Secret123" not in row["pw_hash"] and len(row["salt"]) == 32


def test_password_policy_and_duplicates(store):
    with pytest.raises(AuthError):
        store.create_user("a", "A", Role.TRADER, "short1")
    with pytest.raises(AuthError):
        store.create_user("a", "A", Role.TRADER, "onlyletters")
    with pytest.raises(AuthError):
        store.create_user("bad name", "A", Role.TRADER, "Passw0rd!")
    store.create_user("a", "A", Role.TRADER, "Passw0rd1")
    with pytest.raises(AuthError):
        store.create_user("a", "A2", Role.TRADER, "Passw0rd1")


def test_lockout_after_failures(store):
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    for _ in range(5):
        with pytest.raises(AuthError):
            store.authenticate("t1", "wrong-pass1")
    with pytest.raises(AuthError, match="잠긴"):
        store.authenticate("t1", "Passw0rd1")  # 맞는 비밀번호도 잠금 중에는 거부
    store.unlock("t1", by="admin")
    assert store.authenticate("t1", "Passw0rd1").username == "t1"
    events = [r["event"] for r in store.query("SELECT event FROM auth_log WHERE username='t1'")]
    assert events.count("로그인 실패") == 5 and "로그인 거부" in events and "잠금 해제" in events


def test_deactivate_and_last_admin_protected(store):
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    store.update_user("t1", active=False, by="admin")
    with pytest.raises(AuthError, match="비활성"):
        store.authenticate("t1", "Passw0rd1")
    with pytest.raises(AuthError, match="마지막"):
        store.update_user("admin", role=Role.TRADER)
    store.create_user("admin2", "관리자2", Role.ADMIN, "Secret123")
    store.update_user("admin", role=Role.RISK, by="admin2")
    assert store.get_user("admin").role is Role.RISK


def test_password_change(store):
    store.create_user("t1", "트레이더", Role.TRADER, "Passw0rd1")
    store.set_password("t1", "NewPass99", by="admin")
    with pytest.raises(AuthError):
        store.authenticate("t1", "Passw0rd1")
    assert store.authenticate("t1", "NewPass99")


# ------------------------------ 저장·복원 ------------------------------
def test_roundtrip_restores_full_engine(store, oms):
    roomy(oms)
    with oms.acting("kim"):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
        q = oms.market.quote("000660")
        resting = oms.submit("000660", Side.BUY, OrderType.LIMIT, 5, limit_price=q.bid - 5_000)
        algo = oms.algos.start("005380", Side.BUY, 200, AlgoType.TWAP, duration=10)
        oms.arb.enter(ArbDirection.SELL_ARB, 1)
    oms.step(3)
    store.save(oms)

    restored = store.load()
    assert restored is not None
    assert restored.market.tick_no == 3
    assert restored.orders[resting.order_id].status.is_open
    assert restored.daily_pnl() == pytest.approx(oms.daily_pnl())
    assert {s: p.qty for s, p in restored.positions.items()} == {s: p.qty for s, p in oms.positions.items()}
    # 복원 후에도 알고가 이어서 동작한다
    restored.step(7)
    assert restored.algos.filled(restored.algos.algos[algo.algo_id]) == 200


def test_ledger_tables_match_engine(store, oms):
    with oms.acting("kim"):
        oms.submit("005930", Side.BUY, OrderType.MARKET, 100)
        oms.submit("005930", Side.SELL, OrderType.MARKET, 40)
    store.save(oms)
    oms.step(2)
    with oms.acting("kim"):
        oms.submit("GOLD", Side.BUY, OrderType.MARKET, 3)
    store.save(oms)  # 두 번째 저장은 증분만 추가
    assert store.query("SELECT COUNT(*) n FROM orders")[0]["n"] == len(oms.orders)
    assert store.query("SELECT COUNT(*) n FROM fills")[0]["n"] == len(oms.fills)
    assert store.query("SELECT COUNT(*) n FROM audit")[0]["n"] == len(oms.audit)
    assert store.query("SELECT COUNT(*) n FROM alerts")[0]["n"] == len(oms.alerts)
    fee_sum = store.query("SELECT SUM(fee) s FROM fills")[0]["s"]
    assert fee_sum == pytest.approx(oms.total_fees())
    pos = {r["symbol"]: r["qty"] for r in store.query("SELECT symbol, qty FROM positions")}
    assert pos == {"005930": 60, "GOLD": 3}
    assert {r["trader"] for r in store.query("SELECT trader FROM orders")} == {"kim"}


def test_order_status_updates_are_upserted(store, oms):
    q = oms.market.quote("005930")
    o = oms.submit("005930", Side.BUY, OrderType.LIMIT, 10, limit_price=q.bid - 500)
    store.save(oms)
    oms.cancel(o.order_id)
    store.save(oms)
    row = store.query("SELECT status FROM orders WHERE order_id=?", (o.order_id,))[0]
    assert row["status"] == "취소"


def test_reset_keeps_users(store, oms):
    store.create_user("admin", "관리자", Role.ADMIN, "Secret123")
    oms.submit("005930", Side.BUY, OrderType.MARKET, 1)
    store.save(oms)
    store.reset_trading()
    assert store.load() is None and store.has_users()
    assert store.query("SELECT COUNT(*) n FROM orders")[0]["n"] == 0


def test_pure_python_pbkdf2_matches_hashlib():
    import hashlib

    from rfl_oms.auth import _pbkdf2_sha256_pure

    for pw, salt in [(b"Admin1234", b"0123456789abcdef"), (b"x" * 100, b"salt"), (b"", b"")]:
        assert _pbkdf2_sha256_pure(pw, salt, 500) == hashlib.pbkdf2_hmac("sha256", pw, salt, 500)
```

### `tools/build_record.py`

```python
"""docs/RFL_OMS_전체기록.md 생성기.

docs/_record_header.md(설명 부분) 뒤에 저장소가 추적하는 모든 파일을 원문 그대로 붙인다.
실행: python tools/build_record.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = ROOT / "docs" / "_record_header.md"
OUT = ROOT / "docs" / "RFL_OMS_전체기록.md"
LANG = {".py": "python", ".md": "markdown", ".txt": "text"}
SKIP = {"docs/RFL_OMS_전체기록.md", "docs/_record_header.md"}  # 자기 자신과 설명 원본은 제외


def tracked_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [f for f in out.decode("utf-8").split("\0") if f and f not in SKIP]


def fence_for(text: str) -> str:
    runs = [len(m) for m in re.findall(r"`+", text)] or [0]
    return "`" * max(3, max(runs) + 1)


def build() -> str:
    parts = [HEADER.read_text(encoding="utf-8"), "\n### 수록 파일 목록\n"]
    bodies = []
    for f in tracked_files():
        text = (ROOT / f).read_text(encoding="utf-8")
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        parts.append(f"- `{f}` ({lines}줄)")
        suffix = Path(f).suffix
        note = "\n(기존 파일 — 내용은 줄바꿈 1개뿐인 빈 파일입니다)\n" if not text.strip() else ""
        fence = fence_for(text)
        bodies.append(f"\n### `{f}`\n{note}\n{fence}{LANG.get(suffix, '')}\n{text.rstrip(chr(10))}\n{fence}\n")
    parts.append("")
    return "\n".join(parts) + "".join(bodies)


def verify(doc: str) -> list[str]:
    """문서에서 각 파일을 다시 추출해 원본과 비교한다."""
    appendix = doc.split("## 9. 부록: 전체 소스코드", 1)[1]
    bad = []
    for f in tracked_files():
        text = (ROOT / f).read_text(encoding="utf-8").rstrip("\n")
        if not text.strip():
            continue
        m = re.search(r"\n### `" + re.escape(f) + r"`\n\n(`{3,})[a-z]*\n(.*?)\n\1\n", appendix, re.S)
        if not m or m.group(2) != text:
            bad.append(f)
    return bad


if __name__ == "__main__":
    doc = build()
    OUT.write_text(doc, encoding="utf-8")
    bad = verify(doc)
    print(f"{OUT.relative_to(ROOT)}: {doc.count(chr(10))}줄, 파일 {len(tracked_files())}개, 불일치 {len(bad)}개")
    sys.exit(1 if bad else 0)
```

### `tools/build_web.py`

```python
"""Netlify 등 정적 호스팅용 웹 버전 생성기.

stlite(브라우저 안에서 Streamlit을 실행하는 기술)로 app.py와 엔진을 그대로 브라우저에서 실행한다.
서버가 필요 없고, 데이터는 접속한 브라우저의 IndexedDB에 사용자별로 따로 저장된다.

실행: python tools/build_web.py   →  web/ 폴더 생성 (Netlify publish 디렉터리)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web"
STLITE_VERSION = "1.12.2"  # 내장 Streamlit 1.65
REQUIREMENTS = ["pandas", "plotly", "openpyxl"]

SOURCES = ["app.py", *sorted(str(p.relative_to(ROOT)) for d in ("rfl_oms", "views") for p in (ROOT / d).glob("*.py"))]

HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
  <title>RFL OMS</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{ver}/build/stlite.css" />
  <style>
    #boot {{ font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; max-width: 560px; margin: 18vh auto; padding: 0 16px; color: #333; }}
    #boot h1 {{ font-size: 22px; margin: 0 0 8px; }}
    #boot p {{ color: #666; line-height: 1.6; }}
  </style>
</head>
<body>
  <div id="boot">
    <h1>RFL OMS 불러오는 중…</h1>
    <p>브라우저 안에서 Python을 준비하고 있습니다. 처음 접속 시 30초~1분 정도 걸릴 수 있습니다.<br/>
    모든 시세와 체결은 시뮬레이션이며, 데이터는 이 브라우저에만 저장됩니다.</p>
  </div>
  <div id="root"></div>
  <script type="module">
    import {{ mount }} from "https://cdn.jsdelivr.net/npm/@stlite/browser@{ver}/build/stlite.js";
    const files = {files};
    mount(
      {{
        entrypoint: "app.py",
        requirements: {reqs},
        files: Object.fromEntries(Object.entries(files).map(([path, url]) => [path, {{ url }}])),
        idbfsMountpoints: ["/mnt"],
        streamlitConfig: {{ "client.toolbarMode": "viewer", "browser.gatherUsageStats": false }},
      }},
      document.getElementById("root"),
    );
    document.getElementById("boot").remove();
  </script>
</body>
</html>
"""

NETLIFY_TOML = """[build]
  publish = "web"
  command = "python3 tools/build_web.py"

[[headers]]
  for = "/app/*"
  [headers.values]
    Cache-Control = "no-cache"
"""


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for src in SOURCES:
        dst = OUT / "app" / src
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, dst)
    files = {src: f"./app/{src}" for src in SOURCES}
    (OUT / "index.html").write_text(
        HTML.format(ver=STLITE_VERSION, files=json.dumps(files, indent=2), reqs=json.dumps(REQUIREMENTS)),
        encoding="utf-8",
    )
    (ROOT / "netlify.toml").write_text(NETLIFY_TOML, encoding="utf-8")
    print(f"web/ 생성: 파이썬 파일 {len(SOURCES)}개, stlite {STLITE_VERSION}")


if __name__ == "__main__":
    build()
```

### `views/__init__.py`

```python
"""RFL OMS Streamlit 화면 구성 요소."""
```

### `views/admin_view.py`

```python
"""관리 탭: 사용자 관리, 수수료 설정, 로그인 기록, 데이터베이스, 시스템 초기화."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from rfl_oms import OMS
from rfl_oms.auth import MIN_PASSWORD_LEN, ROLE_PERMS, AuthError, Perm, Role
from rfl_oms.fees import FeeSchedule

from .common import can, current_user
from .runtime import runtime


def users_section() -> None:
    store = runtime().store
    me = current_user()
    rows = store.list_users()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "아이디": r["username"],
                    "이름": r["display_name"],
                    "역할": r["role"],
                    "상태": "활성" if r["active"] else "비활성",
                    "잠금": "잠김" if r["locked_until"] else "",
                    "생성": r["created_at"][:16].replace("T", " "),
                }
                for r in rows
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**사용자 추가**")
        with st.form("new_user", clear_on_submit=True):
            username = st.text_input("아이디")
            name = st.text_input("이름")
            role = st.selectbox("역할", list(Role), format_func=lambda r: r.value)
            pw = st.text_input(f"초기 비밀번호 ({MIN_PASSWORD_LEN}자 이상, 문자+숫자)", type="password")
            if st.form_submit_button("추가", type="primary"):
                try:
                    store.create_user(username, name, role, pw, by=me.username)
                    st.toast(f"{username} 추가")
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
    with c2:
        st.markdown("**사용자 변경**")
        names = [r["username"] for r in rows]
        target = st.selectbox("대상", names, key="admin_target")
        u = store.get_user(target)
        if u:
            with st.form("edit_user"):
                role = st.selectbox("역할", list(Role), index=list(Role).index(u.role), format_func=lambda r: r.value)
                active = st.checkbox("활성", value=u.active)
                new_pw = st.text_input("비밀번호 재설정 (비우면 유지)", type="password")
                if st.form_submit_button("저장"):
                    try:
                        if target == me.username and (role is not Role.ADMIN or not active):
                            raise AuthError("자기 자신의 관리자 권한은 해제할 수 없습니다")
                        store.update_user(target, role=role, active=active, by=me.username)
                        if new_pw:
                            store.set_password(target, new_pw, by=me.username)
                        st.toast("저장했습니다")
                        st.rerun()
                    except AuthError as e:
                        st.error(str(e))
            if st.button("잠금 해제", key="unlock_btn"):
                store.unlock(target, by=me.username)
                st.toast(f"{target} 잠금 해제")
                st.rerun()

    with st.expander("역할별 권한"):
        st.dataframe(
            pd.DataFrame(
                [{"권한": p.value, **{r.value: "✅" if p in ROLE_PERMS[r] else "" for r in Role}} for p in Perm]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption("업무 분리: 주문은 트레이더만, 한도 변경은 리스크 관리자만, 사용자 관리는 관리자만 할 수 있습니다.")


def fees_section(oms: OMS) -> None:
    f = oms.fees
    with st.form("fees"):
        enabled = st.checkbox("거래비용 반영", value=f.enabled)
        c = st.columns(4)
        eq = c[0].number_input("주식 수수료(bp)", 0.0, 100.0, f.equity_commission_bps, 0.1)
        tax = c[1].number_input("주식 매도세(bp)", 0.0, 100.0, f.equity_sell_tax_bps, 0.5, help="시뮬레이션 가정값입니다. 실제 세율로 조정하세요.")
        gold = c[2].number_input("금 현물 수수료(bp)", 0.0, 100.0, f.gold_commission_bps, 0.1)
        fut = c[3].number_input("선물 수수료(bp)", 0.0, 100.0, f.futures_commission_bps, 0.05)
        if st.form_submit_button("수수료 저장"):
            oms.set_fees(FeeSchedule(enabled, eq, tax, gold, fut))
            st.success("저장했습니다 (이후 체결부터 적용)")


def db_section(oms: OMS) -> None:
    rt = runtime()
    store = rt.store
    counts = {t: store.query(f"SELECT COUNT(*) n FROM {t}")[0]["n"] for t in ("orders", "fills", "positions", "audit", "alerts", "users", "auth_log")}  # noqa: S608
    st.caption(f"DB 파일: `{store.path}` · 시작 시 {'저장된 상태를 복원함' if rt.restored else '새로 시작함'}")
    st.dataframe(pd.DataFrame([counts]), hide_index=True, width="stretch")


def auth_log_section() -> None:
    rows = runtime().store.query("SELECT ts, username, event, detail FROM auth_log ORDER BY id DESC LIMIT 300")
    st.dataframe(
        pd.DataFrame([dict(r) for r in rows]).rename(columns={"ts": "시각", "username": "아이디", "event": "이벤트", "detail": "내용"}),
        hide_index=True,
        width="stretch",
    )


def reset_section() -> None:
    st.warning("모든 주문·체결·포지션·감사 로그·알고·바스켓·차익 기록을 지우고 새 시장으로 시작합니다. 사용자 계정과 로그인 기록은 유지됩니다.")
    confirm = st.text_input("확인하려면 '초기화'를 입력하세요", key="reset_confirm")
    if st.button("거래 데이터 초기화", type="primary", disabled=confirm != "초기화"):
        rt = runtime()
        rt.reset_trading()
        rt.store.log_auth(current_user().username, "시스템 초기화", "거래 데이터 삭제")
        st.success("초기화했습니다")
        st.rerun()


def admin_view(oms: OMS) -> None:
    if can(Perm.MANAGE_USERS):
        st.markdown("#### 사용자")
        users_section()
    if can(Perm.SET_FEES):
        st.markdown("#### 거래비용")
        fees_section(oms)
    if can(Perm.MANAGE_USERS):
        st.markdown("#### 데이터베이스")
        db_section(oms)
        with st.expander("로그인 기록"):
            auth_log_section()
    if can(Perm.RESET_SYSTEM):
        with st.expander("시스템 초기화"):
            reset_section()
```

### `views/algo_view.py`

```python
"""알고리즘 주문 화면: TWAP · VWAP · POV 실행과 모니터링."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, AlgoType, Side
from rfl_oms.algo import ALGO_DESCRIPTIONS

from rfl_oms.auth import Perm

from .common import NUM, PCT, can, can_manage, fmt_price, need, symbol_label


def new_algo_form(oms: OMS) -> None:
    symbol = st.selectbox("종목", list(oms.instruments), format_func=lambda s: symbol_label(oms, s), key="algo_symbol")
    inst = oms.instruments[symbol]
    with st.form("algo_form"):
        c = st.columns(2)
        side = c[0].radio("구분", [Side.BUY, Side.SELL], format_func=lambda x: x.value, horizontal=True)
        algo_type = c[1].radio("알고리즘", list(AlgoType), format_func=lambda x: x.value, horizontal=True)
        qty = st.number_input("총 수량", min_value=1, value=3_000 if inst.multiplier == 1 else 30, step=1)
        c = st.columns(2)
        duration = c[0].number_input("기간(틱)", min_value=1, max_value=600, value=30, help="POV는 최대 실행 기간")
        participation = c[1].number_input("참여율(%) · POV", min_value=1.0, max_value=100.0, value=10.0)
        use_limit = st.checkbox("제한가 사용", help="매수는 이 가격 이하, 매도는 이 가격 이상에서만 자식 주문을 냅니다")
        limit = st.number_input(
            f"제한가 (호가단위 {inst.tick_size:g})",
            min_value=float(inst.tick_size),
            value=float(oms.market.quote(symbol).ask),
            step=float(inst.tick_size),
            format=f"%.{inst.price_decimals}f",
            key=f"algo_px_{symbol}",
        )
        st.caption(" · ".join(f"**{k.value}** {v}" for k, v in ALGO_DESCRIPTIONS.items()))
        if st.form_submit_button(
            "알고 시작", type="primary", width="stretch", disabled=not can(Perm.TRADE),
            help=None if can(Perm.TRADE) else need(Perm.TRADE),
        ):
            algo = oms.algos.start(
                symbol,
                side,
                int(qty),
                algo_type,
                duration=int(duration),
                participation=participation / 100,
                limit_price=inst.round_to_tick(limit) if use_limit else None,
            )
            st.session_state.algo_sel = algo.algo_id
            if algo.halt_reason:
                st.error(f"{algo.algo_id} 거부: {algo.halt_reason}")
            else:
                st.success(f"{algo.algo_id} 시작 — 시장을 진행하면 자식 주문이 나갑니다")


def algos_frame(oms: OMS) -> pd.DataFrame:
    ae = oms.algos
    rows = []
    for a in reversed(list(ae.algos.values())):
        filled = ae.filled(a)
        tick = oms.market.tick_no
        target = ae.target(a, tick) if a.status.is_active else None
        arr = ae.slippage_bps(a, a.arrival_price)
        vw = ae.slippage_bps(a, ae.market_vwap(a))
        rows.append(
            {
                "알고": a.algo_id,
                "유형": a.algo_type.value,
                "종목": symbol_label(oms, a.symbol),
                "구분": a.side.value,
                "총수량": a.qty,
                "체결": filled,
                "진행률": filled / a.qty,
                "현재 목표": target,
                "경과/기간": f"{min(tick - a.start_tick, a.duration)}/{a.duration}",
                "상태": a.status.value,
                "평균체결가": round(ae.avg_price(a), 4) if filled else None,
                "도착가": a.arrival_price,
                "도착가 대비(bp)": round(arr, 1) if arr is not None else None,
                "구간 VWAP 대비(bp)": round(vw, 1) if vw is not None else None,
                "자식 주문": len(a.child_ids),
                "바스켓": a.strategy_tag,
                "실행자": a.actor,
                "사유": a.halt_reason,
            }
        )
    return pd.DataFrame(rows)


def algo_detail(oms: OMS, algo_id: str) -> None:
    ae = oms.algos
    a = ae.algos[algo_id]
    c = st.columns(4)
    mine = can(Perm.TRADE) and can_manage(a.actor)
    if c[0].button("일시정지", width="stretch", disabled=a.status.value != "실행중" or not can_manage(a.actor)):
        ae.pause(algo_id)
        st.rerun()
    if c[1].button("재개", width="stretch", disabled=a.status.value != "일시정지" or not mine):
        ae.resume(algo_id)
        st.rerun()
    if c[2].button("취소", width="stretch", disabled=not a.status.is_active or not can_manage(a.actor)):
        ae.cancel(algo_id)
        st.rerun()
    info = f"제한가 **{fmt_price(oms, a.symbol, a.limit_price) if a.limit_price else '없음'}**"
    if a.algo_type is AlgoType.POV:
        info += f" · 참여율 **{a.participation:.0%}**"
    c[3].markdown(info)

    df = pd.DataFrame(a.progress, columns=["틱", "누적 체결", "목표"])
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["목표"], name="목표 스케줄", line=dict(dash="dot", width=1.6))
    fig.add_scatter(x=df["틱"], y=df["누적 체결"], name="누적 체결", line=dict(width=2.2))
    fig.add_hline(y=a.qty, line_color="gray", line_width=1, annotation_text=f"총수량 {a.qty:,}")
    fig.update_layout(
        height=300, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1), xaxis_title="틱"
    )
    st.plotly_chart(fig, width="stretch")

    kids = [o for o in ae.children(a) if o.filled_qty]
    if kids:
        st.dataframe(
            pd.DataFrame(
                [
                    {"주문번호": o.order_id, "시각": o.created_at.strftime("%H:%M:%S"), "체결": o.filled_qty, "가격": o.avg_fill_price}
                    for o in reversed(kids)
                ]
            ),
            hide_index=True,
            width="stretch",
            height=220,
            column_config={"체결": NUM, "가격": NUM},
        )


def algo_view(oms: OMS) -> None:
    left, right = st.columns([1, 2.2])
    with left:
        st.markdown("**새 알고 주문**")
        new_algo_form(oms)
    with right:
        st.markdown("**알고 주문 현황**")
        df = algos_frame(oms)
        if df.empty:
            st.info("실행한 알고 주문이 없습니다. 왼쪽에서 시작한 뒤 사이드바에서 시장을 진행하세요.")
            return
        st.dataframe(
            df,
            hide_index=True,
            width="stretch",
            column_config={
                "총수량": NUM,
                "체결": NUM,
                "현재 목표": NUM,
                "진행률": PCT,
                "평균체결가": NUM,
                "도착가": NUM,
            },
        )
        ids = df["알고"].tolist()
        default = st.session_state.get("algo_sel", ids[0])
        sel = st.selectbox("상세 보기", ids, index=ids.index(default) if default in ids else 0)
        algo_detail(oms, sel)
        st.caption("bp 값이 양수면 불리한 체결(매수는 더 비싸게, 매도는 더 싸게)입니다.")
```

### `views/arb_view.py`

```python
"""지수 차익거래 화면: 괴리 모니터, 진입·청산, 자동 매매, 포지션."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS, ArbDirection, ExecMode

from rfl_oms.auth import Perm

from .common import NUM, can, can_manage, current_user, krw, need


def settings_panel(oms: OMS) -> None:
    arb = oms.arb
    s, c = arb.settings, arb.costs
    idx = oms.market.index_def
    with st.expander("설정 · 이론가 모형 · 비용", expanded=False):
        a = st.columns(3)
        idx.rate = a[0].number_input("무위험 금리(%)", 0.0, 20.0, idx.rate * 100, 0.05) / 100
        idx.dividend_yield = a[1].number_input("배당수익률(%)", 0.0, 20.0, idx.dividend_yield * 100, 0.05) / 100
        idx.days_to_expiry = int(a[2].number_input("만기까지 일수", 1, 365, idx.days_to_expiry))
        b = st.columns(4)
        c.commission_bps = b[0].number_input("주식 수수료(bp, 편도)", 0.0, 50.0, c.commission_bps, 0.1)
        c.sell_tax_bps = b[1].number_input("주식 매도세(bp)", 0.0, 100.0, c.sell_tax_bps, 0.5, help="시뮬레이션 가정값입니다. 실제 세율에 맞게 조정하세요.")
        c.futures_bps = b[2].number_input("선물 수수료(bp, 편도)", 0.0, 20.0, c.futures_bps, 0.1)
        c.slippage_bps = b[3].number_input("슬리피지(bp, 편도)", 0.0, 50.0, c.slippage_bps, 0.5)
        d = st.columns(4)
        s.entry_edge_pts = d[0].number_input("진입 기준(비용 차감 후, pt)", -5.0, 10.0, s.entry_edge_pts, 0.05)
        s.exit_mispricing_pts = d[1].number_input("청산 기준(괴리, pt)", 0.0, 10.0, s.exit_mispricing_pts, 0.05)
        s.max_open = int(d[2].number_input("최대 동시 포지션", 1, 20, s.max_open))
        s.stock_mode = d[3].selectbox(
            "현물 레그 실행", [ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP], format_func=lambda m: m.value,
            index=[ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP].index(s.stock_mode)
            if s.stock_mode in (ExecMode.MARKET, ExecMode.TWAP, ExecMode.VWAP) else 0,
            help="TWAP/VWAP은 10틱에 걸쳐 나눠 체결하므로 그동안 헤지가 불완전합니다",
        )
        st.caption(
            f"왕복 비용 {c.round_trip_bps():.1f}bp = 수수료 2×{c.commission_bps:g} + 매도세 {c.sell_tax_bps:g} "
            f"+ 선물 2×{c.futures_bps:g} + 슬리피지 2×{c.slippage_bps:g}"
        )


def spread_chart(oms: OMS) -> None:
    arb = oms.arb
    h = arb.history
    df = pd.DataFrame(
        {
            "틱": [x.tick for x in h],
            "괴리": [x.mispricing for x in h],
            "매도차익 기준": [x.cost_pts + arb.settings.entry_edge_pts for x in h],
            "매수차익 기준": [-(x.cost_pts + arb.settings.entry_edge_pts) for x in h],
        }
    )
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["매도차익 기준"], name="매도차익 진입선", line=dict(color="#c62828", dash="dot", width=1))
    fig.add_scatter(x=df["틱"], y=df["매수차익 기준"], name="매수차익 진입선", line=dict(color="#2e7d32", dash="dot", width=1))
    fig.add_scatter(x=df["틱"], y=df["괴리"], name="괴리 (선물 − 이론가)", line=dict(width=1.8, color="#1565c0"))
    fig.add_hline(y=0, line_color="gray", line_width=1)
    for p in arb.positions.values():
        color = "#c62828" if p.direction is ArbDirection.SELL_ARB else "#2e7d32"
        fig.add_scatter(
            x=[p.opened_tick], y=[p.entry.mispricing], mode="markers", marker=dict(symbol="triangle-up", size=10, color=color),
            showlegend=False, hovertext=f"{p.arb_id} {p.direction.value} 진입",
        )
        if p.exit:
            fig.add_scatter(
                x=[p.closed_tick], y=[p.exit.mispricing], mode="markers", marker=dict(symbol="x", size=9, color=color),
                showlegend=False, hovertext=f"{p.arb_id} 청산",
            )
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.12), yaxis_title="pt", xaxis_title="틱")
    st.plotly_chart(fig, width="stretch")


def positions_table(oms: OMS) -> None:
    arb = oms.arb
    if not arb.positions:
        st.caption("차익 포지션이 없습니다.")
        return
    rows = []
    for p in reversed(list(arb.positions.values())):
        fut, stock = arb.hedge(p)
        rows.append(
            {
                "ID": p.arb_id,
                "방향": p.direction.value,
                "계약": p.contracts,
                "상태": p.status.value,
                "진입 틱": p.opened_tick,
                "진입 괴리(pt)": round(p.entry.mispricing, 3),
                "청산 괴리(pt)": round(p.exit.mispricing, 3) if p.exit else None,
                "손익(비용 전)": round(arb.pnl(p)),
                "비용": round(arb.fees(p)),
                "순손익": round(arb.pnl_net(p)),
                "선물 명목": round(fut),
                "현물 명목": round(stock),
                "헤지 잔차": round(fut + stock),
                "진입자": p.owner,
                "메모": p.note,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={k: NUM for k in ["손익(비용 전)", "비용", "순손익", "선물 명목", "현물 명목", "헤지 잔차"]},
    )
    open_ids = [p.arb_id for p in arb.open_positions() if can_manage(p.owner.removesuffix("(자동)"))]
    if open_ids:
        c = st.columns([2, 1, 1])
        sel = c[0].selectbox("청산할 포지션", open_ids, label_visibility="collapsed")
        if c[1].button("선택 청산", width="stretch"):
            arb.close(sel)
            st.rerun()
        if c[2].button("전체 청산", width="stretch"):
            for i in open_ids:
                arb.close(i)
            st.rerun()


def constituents_table(oms: OMS) -> None:
    idx = oms.market.index_def
    total = sum(q * oms.market.mark(s) for s, q in idx.constituents.items())
    rows = [
        {
            "종목": s,
            "종목명": oms.instruments[s].name,
            "계약당 주식수": q,
            "현재가": oms.market.mark(s),
            "금액": q * oms.market.mark(s),
            "비중": q * oms.market.mark(s) / total,
        }
        for s, q in idx.constituents.items()
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "계약당 주식수": NUM,
            "현재가": NUM,
            "금액": NUM,
            "비중": st.column_config.NumberColumn(format="percent"),
        },
    )
    st.caption(f"{idx.name} = Σ(주식수 × 가격) / {idx.divisor:,.0f} · 선물 1계약 = 위 바스켓 1단위 ({krw(total)})")


def arb_view(oms: OMS) -> None:
    arb = oms.arb
    if not arb.available:
        st.info("지수선물과 구성종목이 설정되지 않아 차익거래를 사용할 수 없습니다.")
        return
    snap = arb.snapshot()
    m = st.columns(6)
    m[0].metric("RFL 시뮬 지수", f"{snap.index:,.2f}")
    m[1].metric("선물 중간가", f"{snap.fut_mid:,.3f}", help=f"매수호가 {snap.fut_bid:,.2f} / 매도호가 {snap.fut_ask:,.2f}")
    m[2].metric("이론가", f"{snap.fair:,.2f}", help=f"이론 베이시스 {snap.theo_basis:+.2f}pt")
    m[3].metric("괴리", f"{snap.mispricing:+.2f}pt", delta=f"{snap.mispricing_bps:+.1f}bp", delta_color="off")
    m[4].metric("매도차익 순수익", f"{snap.sell_edge:+.2f}pt")
    m[5].metric("매수차익 순수익", f"{snap.buy_edge:+.2f}pt")

    settings_panel(oms)
    spread_chart(oms)

    s = arb.settings
    c = st.columns([1, 1.2, 1.2, 1.4])
    s.contracts = int(c[0].number_input("계약 수", 1, 100, s.contracts))
    trade_ok = can(Perm.TRADE)
    tip = None if trade_ok else need(Perm.TRADE)
    hot_sell = snap.sell_edge >= s.entry_edge_pts
    hot_buy = snap.buy_edge >= s.entry_edge_pts
    c[1].write("")
    if c[1].button("매도차익 진입" + (" 🔥" if hot_sell else ""), width="stretch", type="primary" if hot_sell else "secondary",
                   help=tip or "선물 매도 + 현물 바스켓 매수", disabled=not trade_ok):
        pos, problems = arb.enter(ArbDirection.SELL_ARB)
        (st.success(f"{pos.arb_id} 진입") if pos else st.error("진입 거부: " + "; ".join(problems[:3])))
    c[2].write("")
    if c[2].button("매수차익 진입" + (" 🔥" if hot_buy else ""), width="stretch", type="primary" if hot_buy else "secondary",
                   help=tip or "선물 매수 + 현물 바스켓 매도(대차 매도 가정)", disabled=not trade_ok):
        pos, problems = arb.enter(ArbDirection.BUY_ARB)
        (st.success(f"{pos.arb_id} 진입") if pos else st.error("진입 거부: " + "; ".join(problems[:3])))
    c[3].write("")
    auto = c[3].toggle(
        "자동 차익 (진입·청산)", value=s.auto, disabled=not trade_ok,
        help=tip or "시장이 진행될 때 기준을 넘으면 자동 진입, 괴리가 수렴하면 자동 청산. 자동 주문은 켠 사용자 이름으로 기록됩니다",
    )
    if trade_ok and auto != s.auto:
        s.auto = auto
        s.auto_owner = current_user().username
        oms.system_event("자동 차익", "켜짐" if auto else "꺼짐")
    if s.auto:
        c[3].caption(f"자동 실행자: {s.auto_owner}")

    st.markdown("#### 차익 포지션")
    positions_table(oms)
    with st.expander("지수 구성 · 선물 1계약 복제 바스켓"):
        constituents_table(oms)
    st.caption("손익은 거래비용을 빼기 전 값입니다. 매수차익의 현물 매도는 대차(공매도)가 가능하다고 가정합니다.")
```

### `views/auth_view.py`

```python
"""로그인, 첫 관리자 생성, 내 비밀번호 변경."""

from __future__ import annotations

import streamlit as st

from rfl_oms.auth import MIN_PASSWORD_LEN, AuthError, Role

from .runtime import runtime


def _setup_admin() -> None:
    st.title("RFL OMS 초기 설정")
    st.info("등록된 사용자가 없습니다. 첫 관리자 계정을 만드세요. 기본 계정이나 기본 비밀번호는 없습니다.")
    with st.form("setup_admin"):
        username = st.text_input("관리자 아이디", placeholder="예: admin")
        name = st.text_input("이름")
        pw = st.text_input(f"비밀번호 ({MIN_PASSWORD_LEN}자 이상, 문자와 숫자 포함)", type="password")
        pw2 = st.text_input("비밀번호 확인", type="password")
        if st.form_submit_button("관리자 계정 만들기", type="primary"):
            if pw != pw2:
                st.error("비밀번호 확인이 일치하지 않습니다")
                return
            try:
                user = runtime().store.create_user(username, name, Role.ADMIN, pw)
            except AuthError as e:
                st.error(str(e))
                return
            st.session_state.username = user.username
            st.rerun()


def _login() -> None:
    st.title("RFL OMS 로그인")
    st.caption("주문관리 · 사전 리스크 점검 — 시세와 체결은 모두 시뮬레이션입니다.")
    with st.form("login"):
        username = st.text_input("아이디")
        pw = st.text_input("비밀번호", type="password")
        if st.form_submit_button("로그인", type="primary"):
            try:
                user = runtime().store.authenticate(username, pw)
            except AuthError as e:
                st.error(str(e))
                return
            st.session_state.username = user.username
            st.rerun()


def require_login():
    """로그인한 User를 돌려준다. 아니면 로그인·설정 화면을 그리고 실행을 멈춘다."""
    store = runtime().store
    if not store.has_users():
        _setup_admin()
        st.stop()
    username = st.session_state.get("username")
    user = store.get_user(username) if username else None
    if user is None or not user.active:
        if user is not None:
            st.warning("계정이 비활성화되어 로그아웃되었습니다.")
        st.session_state.pop("username", None)
        st.session_state.pop("user", None)
        _login()
        st.stop()
    st.session_state.user = user
    return user


def account_sidebar(user) -> None:
    st.sidebar.markdown(f"**{user.display_name}** · {user.role.value}")
    st.sidebar.caption(f"아이디: {user.username}")
    c1, c2 = st.sidebar.columns(2)
    if c1.button("로그아웃", width="stretch"):
        runtime().store.log_auth(user.username, "로그아웃")
        st.session_state.pop("username", None)
        st.session_state.pop("user", None)
        st.rerun()
    with c2.popover("비밀번호", width="stretch"):
        with st.form("own_pw"):
            cur = st.text_input("현재 비밀번호", type="password")
            new = st.text_input("새 비밀번호", type="password")
            new2 = st.text_input("새 비밀번호 확인", type="password")
            if st.form_submit_button("변경"):
                store = runtime().store
                try:
                    store.authenticate(user.username, cur)
                    if new != new2:
                        raise AuthError("새 비밀번호 확인이 일치하지 않습니다")
                    store.set_password(user.username, new, by=user.username)
                    st.success("비밀번호를 변경했습니다")
                except AuthError as e:
                    st.error(str(e))
```

### `views/basket_view.py`

```python
"""바스켓 주문 화면: 구성 → 점검 → 원클릭 실행 → 모니터링."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from rfl_oms import OMS, ExecMode, ExecParams
from rfl_oms.basket import SIDE_ALIASES, normalize_symbol, sample_template

from rfl_oms.auth import Perm

from .common import NUM, PCT, can, can_manage, krw, need, symbol_label

COLUMNS = ["종목코드", "구분", "수량", "비중(%)"]


def _set_table(df: pd.DataFrame) -> None:
    df = df.copy()
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNS]
    df["종목코드"] = df["종목코드"].map(lambda v: normalize_symbol(v) if pd.notna(v) else None)
    df["구분"] = df["구분"].map(
        lambda v: SIDE_ALIASES.get(str(v).strip().upper()).value if str(v).strip().upper() in SIDE_ALIASES else v
    )
    st.session_state.basket_df = df.reset_index(drop=True)
    st.session_state.basket_ver = st.session_state.get("basket_ver", 0) + 1


def _read_upload(file) -> pd.DataFrame:
    if file.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(file, dtype={"종목코드": str})
    return pd.read_csv(file, dtype={"종목코드": str})


def _sample_downloads() -> None:
    sample = sample_template()
    buf = io.BytesIO()
    sample.to_excel(buf, index=False)
    c1, c2 = st.columns(2)
    c1.download_button("양식 (엑셀)", buf.getvalue(), "rfl_basket_template.xlsx", width="stretch")
    c2.download_button(
        "양식 (CSV)", sample.to_csv(index=False).encode("utf-8-sig"), "rfl_basket_template.csv", width="stretch"
    )


def build_section(oms: OMS) -> None:
    bm = oms.baskets
    if "basket_df" not in st.session_state:
        _set_table(sample_template())

    left, right = st.columns([2.2, 1])
    with right:
        st.markdown("**불러오기**")
        up = st.file_uploader("엑셀/CSV 업로드", type=["xlsx", "xls", "csv"], label_visibility="collapsed")
        if up is not None and st.session_state.get("basket_upload_id") != up.file_id:
            try:
                _set_table(_read_upload(up))
                st.session_state.basket_upload_id = up.file_id
                st.success(f"{up.name} 불러옴")
            except Exception as e:  # 파일 형식 오류를 화면에 표시
                st.error(f"파일을 읽지 못했습니다: {e}")
        st.caption("열: 종목코드, 구분(매수/매도), 수량 또는 비중(%)")
        _sample_downloads()

        st.markdown("**템플릿**")
        if bm.templates:
            tname = st.selectbox("저장된 템플릿", list(bm.templates))
            if st.button("템플릿 불러오기", width="stretch"):
                _set_table(bm.load_template(tname))
                st.rerun()
        new_name = st.text_input("현재 구성을 저장할 이름", placeholder="예: 대형주 5종")
        save_clicked = st.button("템플릿 저장", width="stretch", disabled=not new_name.strip())

    with left:
        st.markdown("**바스켓 구성** — 행을 추가·삭제하거나 값을 직접 고칠 수 있습니다")
        edited = st.data_editor(
            st.session_state.basket_df,
            key=f"basket_editor_{st.session_state.basket_ver}",
            num_rows="dynamic",
            width="stretch",
            column_config={
                "종목코드": st.column_config.SelectboxColumn(
                    options=list(oms.instruments), required=True, help="시뮬레이션 종목만 선택할 수 있습니다"
                ),
                "구분": st.column_config.SelectboxColumn(options=["매수", "매도"], required=True),
                "수량": st.column_config.NumberColumn(min_value=0, step=1, format="localized"),
                "비중(%)": st.column_config.NumberColumn(min_value=0.0, step=0.5),
            },
        )
        if save_clicked:
            bm.save_template(new_name.strip(), edited)
            st.success(f"템플릿 '{new_name.strip()}' 저장")

        c1, c2 = st.columns([1, 1.4])
        by = c1.radio("수량 결정 방식", ["수량", "비중"], horizontal=True, help="비중: 목표 금액을 비중대로 나눠 수량 계산")
        target = None
        if by == "비중":
            target = c2.number_input("목표 명목금액(원)", min_value=0.0, value=300_000_000.0, step=1e7, format="%.0f")

    lines, errors = bm.build_lines(edited, by=by, target_notional=target)
    for e in errors:
        st.warning(e)
    if not lines:
        st.info("실행할 종목이 없습니다.")
        return

    st.markdown("**실행 전 점검**")
    preview = bm.preview_frame(lines)
    st.dataframe(
        preview,
        hide_index=True,
        width="stretch",
        column_config={"수량": NUM, "기준가": NUM, "예상 명목": NUM},
    )
    buy_n = preview.loc[preview["구분"] == "매수", "예상 명목"].sum()
    sell_n = preview.loc[preview["구분"] == "매도", "예상 명목"].sum()
    fails = (preview["사전 점검"] != "통과").sum()
    m = st.columns(4)
    m[0].metric("종목 수", f"{len(lines)}")
    m[1].metric("매수 명목", krw(buy_n))
    m[2].metric("매도 명목", krw(sell_n))
    m[3].metric("점검 실패", f"{fails}건")

    st.markdown("**실행 설정**")
    c = st.columns([1.3, 1.4, 1, 1, 1])
    name = c[0].text_input("바스켓 이름", value=f"바스켓 {len(bm.baskets) + 1}")
    mode = c[1].selectbox("실행 방식", list(ExecMode), format_func=lambda m: m.value)
    params = ExecParams(mode=mode)
    if mode in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE):
        params.offset_ticks = int(c[2].number_input("호가 조정(틱)", min_value=0, max_value=50, value=0))
    if mode.algo_type is not None:
        params.duration = int(c[2].number_input("기간(틱)", min_value=1, max_value=600, value=30))
    if mode is ExecMode.POV:
        params.participation = c[3].number_input("참여율(%)", min_value=1.0, max_value=100.0, value=10.0) / 100
    if mode is ExecMode.MARKET:
        params.auto_retry = c[2].checkbox("잔량 자동 재전송", value=True, help="유동성 부족으로 남은 수량을 다음 틱에 최대 3회 재전송")
    c[4].write("")
    if c[4].button(
        "원클릭 실행", type="primary", width="stretch", disabled=not can(Perm.TRADE),
        help=None if can(Perm.TRADE) else need(Perm.TRADE),
    ):
        b = bm.execute(name, lines, params)
        st.session_state.basket_sel = b.basket_id
        s = bm.summary(b)
        msg = f"{b.basket_id} 실행: {s['종목 수']}종목, 체결률 {s['수량 체결률']:.0%}, 거부 {s['거부 종목']}건"
        (st.warning if s["거부 종목"] else st.success)(msg)


def monitor_section(oms: OMS) -> None:
    bm = oms.baskets
    if not bm.baskets:
        st.caption("실행된 바스켓이 없습니다.")
        return
    ids = list(reversed(bm.baskets))
    default = st.session_state.get("basket_sel", ids[0])
    bid = st.selectbox(
        "바스켓",
        ids,
        index=ids.index(default) if default in ids else 0,
        format_func=lambda i: f"{i} · {bm.baskets[i].name} · {bm.baskets[i].params.mode.value}",
    )
    b = bm.baskets[bid]
    s = bm.summary(b)
    m = st.columns(6)
    m[0].metric("수량 체결률", f"{s['수량 체결률']:.1%}")
    m[1].metric("금액 체결률", f"{s['금액 체결률']:.1%}")
    m[2].metric("완료 종목", f"{s['완료 종목']}/{s['종목 수']}")
    m[3].metric("체결 금액", krw(s["체결 금액"]))
    m[4].metric("잔량 (진행 중)", f"{s['잔량']:,} ({s['진행 중 수량']:,})")
    m[5].metric("평가손익", krw(s["평가손익"]))
    st.progress(min(s["수량 체결률"], 1.0))

    st.dataframe(
        bm.lines_frame(b),
        hide_index=True,
        width="stretch",
        column_config={
            "목표": NUM,
            "체결": NUM,
            "진행 중": NUM,
            "체결률": PCT,
            "평균체결가": NUM,
            "현재가": NUM,
            "평가손익": NUM,
        },
    )
    st.caption(f"실행자: {b.actor or '-'}")
    mine = can(Perm.TRADE) and can_manage(b.actor)  # 재실행·정정은 실행한 트레이더만
    c = st.columns(3)
    if c[0].button("미체결 전체 취소", width="stretch", key=f"bc_{bid}", disabled=not can_manage(b.actor)):
        st.success(f"{bm.cancel(bid)}건 취소")
    if c[1].button(
        "잔량 재실행", width="stretch", key=f"br_{bid}", disabled=not mine,
        help="거부·취소·미체결로 남은 수량을 같은 방식으로 다시 보냅니다 (바스켓을 실행한 트레이더만)",
    ):
        st.success(f"{bm.retry(bid)}종목 재전송")
    limit_mode = b.params.mode in (ExecMode.AGGRESSIVE, ExecMode.PASSIVE)
    if c[2].button("현재 호가로 정정", width="stretch", key=f"bp_{bid}", disabled=not (limit_mode and mine)):
        st.success(f"{bm.reprice(bid)}건 정정")


def basket_view(oms: OMS) -> None:
    with st.expander("바스켓 구성·실행", expanded=True):
        build_section(oms)
    st.markdown("#### 바스켓 모니터")
    monitor_section(oms)
    st.caption(
        "종목: " + ", ".join(symbol_label(oms, s) for s, i in oms.instruments.items() if i.asset_class == "주식")
    )
```

### `views/common.py`

```python
"""화면 공용 도우미."""

from __future__ import annotations

import streamlit as st

from rfl_oms import OMS

NUM = st.column_config.NumberColumn(format="localized")
PCT = st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")


def fmt_price(oms: OMS, symbol: str, price: float | None) -> str:
    if price is None:
        return "시장가"
    d = oms.instruments[symbol].price_decimals
    return f"{price:,.{d}f}"


def krw(v: float) -> str:
    """지표용 축약 표기: 1억 이상은 '억', 1만 이상은 '만' 단위."""
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.4f}억"
    if abs(v) >= 1e5:
        return f"{v / 1e4:,.1f}만"
    return f"{v:,.0f}"


def symbol_label(oms: OMS, symbol: str) -> str:
    return f"{symbol} · {oms.instruments[symbol].name}"


# ============================== 사용자·권한 ==============================
def current_user():
    """로그인한 사용자 (app.py가 매 실행마다 DB에서 다시 읽어 넣는다)."""
    return st.session_state.get("user")


def can(perm) -> bool:
    u = current_user()
    return bool(u and u.can(perm))


def can_manage(owner: str) -> bool:
    """정정·취소 권한: 리스크 관리자는 모든 것, 트레이더는 자기 것만."""
    from rfl_oms.auth import Perm

    u = current_user()
    if u is None:
        return False
    return u.can(Perm.CANCEL_ANY) or (u.can(Perm.TRADE) and owner == u.username)


def need(perm) -> str:
    """권한이 없을 때 버튼 도움말로 쓸 문구."""
    from rfl_oms.auth import ROLE_PERMS

    roles = ", ".join(r.value for r, ps in ROLE_PERMS.items() if perm in ps)
    return f"'{perm.value}' 권한이 필요합니다 ({roles})"
```

### `views/risk_view.py`

```python
"""리스크 대시보드: 한도 사용률, VaR, 손익 추이, 노출 분해, 집중도, 스트레스 테스트."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rfl_oms import OMS
from rfl_oms.analytics import concentration, equity_beta_exposure, exposure_by_asset_class, stress_test, value_at_risk

from .common import NUM, krw


def limits_panel(oms: OMS) -> None:
    warn = oms.limits.warn_ratio
    for row in oms.utilization():
        ratio = row["사용률"]
        icon = "🔴" if ratio >= 1 else "🟠" if ratio >= warn else "🟢"
        st.markdown(f"{icon} **{row['항목']}** — {krw(row['사용'])} / {krw(row['한도'])} ({ratio:.1%})")
        st.progress(min(max(ratio, 0.0), 1.0))
    st.caption("노출·증거금은 미체결 주문과 알고 잔량이 모두 체결된다고 가정한 최악의 경우입니다.")


def limits_table(oms: OMS) -> None:
    lim = oms.limits
    st.dataframe(
        pd.DataFrame(
            [
                ("계좌 자본", f"{lim.capital:,.0f}"),
                ("주문당 최대 수량", f"{lim.max_order_qty:,}"),
                ("주문당 최대 명목", f"{lim.max_order_notional:,.0f}"),
                ("가격 괴리 허용", f"{lim.price_band_pct:.1f}%"),
                ("종목별 포지션 한도", f"{lim.max_position_notional:,.0f}"),
                ("총 노출 한도", f"{lim.max_gross_exposure:,.0f}"),
                ("일일 손실 한도", f"{lim.max_daily_loss:,.0f}"),
                ("경고 기준", f"{lim.warn_ratio:.0%}"),
                ("거래 제한 종목", ", ".join(sorted(lim.restricted_symbols)) or "없음"),
                ("헤지 증거금 상계", f"{'사용' if lim.margin_offset_enabled else '미사용'} · 감면율 {lim.margin_offset_pct:.0f}%"),
            ],
            columns=["항목", "값"],
        ),
        hide_index=True,
        width="stretch",
    )


def pnl_chart(oms: OMS) -> None:
    df = pd.DataFrame(oms.pnl_history, columns=["틱", "실현", "미실현", "평가자산", "총노출"])
    df["일일 손익"] = df["실현"] + df["미실현"]
    fig = go.Figure()
    fig.add_scatter(x=df["틱"], y=df["일일 손익"], name="일일 손익", line=dict(width=2))
    fig.add_scatter(x=df["틱"], y=df["실현"], name="실현", line=dict(width=1.2, dash="dot"))
    fig.add_hline(y=-oms.limits.max_daily_loss, line_color="#c62828", line_dash="dash", annotation_text="손실 한도")
    fig.add_hline(y=0, line_color="gray", line_width=1)
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.12), xaxis_title="틱")
    st.plotly_chart(fig, width="stretch")


def exposure_chart(oms: OMS) -> None:
    df = exposure_by_asset_class(oms)
    if df.empty:
        st.caption("보유 포지션이 없습니다.")
        return
    fig = go.Figure()
    fig.add_bar(y=df["자산군"], x=df["매수"], name="매수", orientation="h", marker_color="#2e7d32")
    fig.add_bar(y=df["자산군"], x=df["매도"], name="매도", orientation="h", marker_color="#c62828")
    fig.add_scatter(y=df["자산군"], x=df["순노출"], name="순노출", mode="markers", marker=dict(size=11, color="#1565c0", symbol="diamond"))
    fig.update_layout(barmode="relative", height=260, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, width="stretch")


def risk_view(oms: OMS) -> None:
    var99 = value_at_risk(oms, 0.99)
    var95 = value_at_risk(oms, 0.95)
    beta = equity_beta_exposure(oms)
    m = st.columns(5)
    if var99.historical is None:
        m[0].metric("VaR 99% (1일, 과거)", "데이터 부족", help=f"수익률 관측치 {var99.observations}/20 — 시장을 더 진행하세요")
        m[1].metric("VaR 99% (1일, 모수)", "—")
        m[2].metric("VaR 95% (1일, 과거)", "—")
    else:
        m[0].metric("VaR 99% (1일, 과거)", krw(var99.historical), help=f"최근 {var99.observations}틱 수익률, √120로 1일 환산")
        m[1].metric("VaR 99% (1일, 모수)", krw(var99.parametric))
        m[2].metric("VaR 95% (1일, 과거)", krw(var95.historical))
    m[3].metric("주가 방향 순노출", krw(beta), help="주식 + 지수선물 순명목 (차익 포지션은 서로 상쇄)")
    loss_room = oms.limits.max_daily_loss + min(oms.daily_pnl(), 0)
    m[4].metric("남은 손실 여력", krw(loss_room))
    mb = oms.margin_breakdown()
    exp = oms.exposure()
    m2 = st.columns(5)
    m2[0].metric("증거금 (상계 전)", krw(mb["상계 전"]))
    m2[1].metric("헤지 상계", krw(mb["헤지 상계"]), help="지수선물과 구성종목이 반대 방향일 때 헤지된 선물 증거금 감면")
    m2[2].metric("순증거금", krw(mb["순증거금"]))
    m2[3].metric("미체결 포함 순증거금", krw(exp.margin), help="미체결이 헤지를 깨는 경우까지 고려한 보수적 상계")
    m2[4].metric("누적 수수료·세금", krw(oms.total_fees()))
    if var99.historical and var99.historical > loss_room:
        st.warning("1일 VaR 99%가 남은 손실 여력보다 큽니다. 포지션 축소를 검토하세요.", icon="⚠️")

    left, right = st.columns([1.2, 1])
    with left:
        st.markdown("**손익 추이**")
        pnl_chart(oms)
        st.markdown("**자산군별 노출**")
        exposure_chart(oms)
    with right:
        st.markdown("**한도 사용률**")
        limits_panel(oms)

    st.markdown("#### 스트레스 테스트")
    st.dataframe(
        stress_test(oms),
        hide_index=True,
        width="stretch",
        column_config={
            "예상 손익": NUM,
            "평가자산 대비": st.column_config.NumberColumn(format="percent"),
            "손실한도 대비": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent"),
        },
    )
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown("#### 상위 집중 포지션")
        conc = concentration(oms)
        if conc.empty:
            st.caption("보유 포지션이 없습니다.")
        else:
            st.dataframe(
                conc,
                hide_index=True,
                width="stretch",
                column_config={"수량": NUM, "순명목": NUM, "비중": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")},
            )
    with c2:
        st.markdown("#### 적용 중인 한도")
        limits_table(oms)
```

### `views/runtime.py`

```python
"""공유 런타임: 모든 브라우저 세션이 하나의 엔진과 DB를 함께 쓴다."""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager

import streamlit as st

from rfl_oms import OMS, MarketSim
from rfl_oms.storage import Store

# 브라우저 실행(stlite/Pyodide)에서는 IndexedDB에 연결된 /mnt에 저장해 새로고침 후에도 유지한다
IN_BROWSER = sys.platform == "emscripten"
DEFAULT_DB = os.environ.get("RFL_OMS_DB", "/mnt/rfl_oms.db" if IN_BROWSER else "data/rfl_oms.db")


class Runtime:
    def __init__(self, db_path: str = DEFAULT_DB):
        self.store = Store(db_path)
        self.lock = threading.RLock()  # 여러 세션의 동시 수정을 직렬화
        restored = self.store.load()
        self.restored = restored is not None
        self.oms = restored or OMS(market=MarketSim(seed=None))
        self.last_auto_step = time.time()

    def reset_trading(self) -> None:
        with self.lock:
            self.store.reset_trading()
            self.oms = OMS(market=MarketSim(seed=None))
            self.store.save(self.oms)


@st.cache_resource
def runtime() -> Runtime:
    return Runtime()


@contextmanager
def engine(actor: str):
    """잠금 → 행위자 지정 → 작업 → 저장. 화면의 모든 엔진 접근은 이 안에서 한다."""
    rt = runtime()
    with rt.lock:
        try:
            with rt.oms.acting(actor):
                yield rt.oms
        finally:
            # st.rerun()도 예외로 문맥을 빠져나오므로, 메모리의 변경을 항상 저장한다
            rt.store.save(rt.oms)
```
