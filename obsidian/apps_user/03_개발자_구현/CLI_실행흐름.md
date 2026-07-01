---
title: CLI 실행흐름
created: 2026-06-30
source_basis: code_only
tags:
  - user
  - developer
  - cli
---

# CLI 실행흐름

근거 코드: `apps/user/__main__.py`

## 진입점

```text
python -m apps.user register
python -m apps.user list
```

`main()`은 `_parse_args()`에서 `command`를 읽고 두 함수 중 하나로 분기한다.

| command | 함수 | 역할 |
|---|---|---|
| `register` | `run_register()` | 사용자 생성/확인 후 주식/선물 자격증명 저장 |
| `list` | `run_list()` | 사용자와 자격증명 목록 조회 |

## 인자 파서

`_parse_args()`의 command choices는 다음 두 개뿐이다.

```text
register
list
```

추가 옵션은 현재 없다. 환경 파일은 CLI 옵션이 아니라 `QUANTPILOT_ENV_FILE` 환경 변수로 바꾼다.

## register 상세 흐름

```text
run_register
  -> load_config
  -> PostgreDB(build_db_config)
  -> fetch_user_by_email(db, cfg.email)
      -> 있으면 기존 id 사용
      -> 없으면 create_user(db, cfg.email, cfg.display_name)
  -> save_broker_credential(... account_type=STOCK ...)
  -> futures_account_number와 futures_account_product_code가 모두 있으면
       save_broker_credential(... account_type=FUTURES ...)
  -> db.close
```

주식 계좌는 필수이며 항상 저장된다. 선물 계좌는 계좌번호와 상품코드가 모두 있을 때만 저장된다.

저장 시 `extra`에 들어가는 값:

| 계좌 | `extra.account_type` | `extra.account_product_code` |
|---|---|---|
| 주식 | `STOCK` | `KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE` |
| 선물 | `FUTURES` | `KIS_DOMESTIC_FUTURES_ACCOUNT_PRODUCT_CODE` |

## list 상세 흐름

```text
run_list
  -> load_config
  -> PostgreDB(build_db_config)
  -> fetch_user_by_email(db, cfg.email)
      -> 없으면 안내 출력 후 return
  -> fetch_credentials_by_user(db, user["id"])
  -> 각 credential의 extra.account_type 읽기
  -> account_number 마스킹 출력
  -> db.close
```

`fetch_credentials_by_user()`는 API 키와 시크릿을 복호화해서 dict로 반환한다. 하지만 `run_list()`는 그 값을 출력하지 않는다.

## 마스킹 정책

`apps/user`의 `_mask()`는 계좌번호 끝 4자리만 보여준다.

```text
1234567890 -> ****7890
```

Trader의 `_mask_account()`는 앞 2자리와 뒤 2자리를 보여준다.

```text
1234567890 -> 12****90
```

운영 로그 형식이 앱마다 약간 다르므로, 문서나 캡처에서는 원계좌번호가 노출되지 않았는지만 확인한다.

## DB 연결 수명

`run_register()`와 `run_list()` 모두 `try/finally`로 `db.close()`를 호출한다.

```text
db = PostgreDB(build_db_config())
try:
    ...
finally:
    db.close()
```

`PostgreDB`는 Singleton metaclass를 사용한다. 같은 프로세스에서 여러 번 생성하면 첫 번째 인스턴스를 재사용할 수 있으므로, 장기 프로세스에서 서로 다른 DB config를 섞는 설계는 피하는 편이 안전하다.

## 구현상 주의점

- `register`는 사용자 생성과 자격증명 저장을 하나의 DB transaction으로 묶지 않는다. 자격증명 저장 중 실패하면 사용자 행만 남을 수 있다.
- `list`도 `load_config()`를 공유하므로 조회에 필요하지 않은 등록용 KIS 필수 변수까지 요구한다.
- `_save_credential()` 헬퍼는 현재 호출되지 않는다. 내부에서 `cfg._user_id`를 참조하지만 `UserRegisterConfig`에는 해당 필드가 없으므로, 그대로 재사용하면 실패한다.
- 기존 사용자 조회 시 `is_active`를 확인해 차단하지 않는다. 비활성 사용자 정책이 필요하면 `run_register()` 또는 repository 계층에 명시해야 한다.

## Trader 연결 지점

Trader 초기화는 `apps/trader/__main__.py`의 `_init()`에서 다음 순서로 등록 데이터를 사용한다.

```text
load trader config
  -> fetch_user_by_email(USER_EMAIL)
  -> fetch_credential_by_account_type(account_type="STOCK", environment_code=cfg.environment_code)
  -> KisBroker.from_db_credential(credential)
```

따라서 `apps/user`가 저장하는 `extra.account_type`, `environment_code`, `broker_code`는 Trader 시작 가능 여부에 직접 영향을 준다.
