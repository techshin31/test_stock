- https://www.wiseindex.com/About/WICS

## WICS 분류 JSON 파일

WICS Methodology.pdf 기준으로 대·중·소·세분류별 JSON 파일을 제공합니다.

| 파일명 | 설명 | 코드 자릿수 |
|--------|------|-------------|
| `wics_major.json` | 대분류 (Sector) | 2자리 |
| `wics_medium.json` | 중분류 (Industry Group) | 4자리 |
| `wics_minor.json` | 소분류 (Industry) | 6자리 |
| `wics_detailed.json` | 세분류 (Sub-Industry) | 8자리, 설명 포함 |

- 중분류·소분류·세분류 JSON에는 상위 분류 코드(`major_code`, `medium_code`, `minor_code`)가 포함되어 계층 조회가 가능합니다.
- 세분류 항목에는 각 업종 정의 `description`이 포함되어 있습니다.

## WI26 분류 JSON 파일

WI26-WICS섹터매핑.pdf 기준으로 WI26 대·소분류 및 WICS 소분류 매핑을 제공합니다. WI26은 WICS 소분류를 기준으로 26개 대분류, 48개 소분류로 재구성한 산업분류입니다.

| 파일명 | 설명 |
|--------|------|
| `wi26_major.json` | WI26 대분류 (26개) |
| `wi26_minor.json` | WI26 소분류 (48개), `major_code`로 대분류 연결 |
| `wi26_wics_mapping.json` | WICS 소분류 코드별 WI26 매핑 (`wics_minor.json` 코드만 사용) |

- `wi26_wics_mapping.json`의 `wics_minor_code`는 `wics_minor.json`에 정의된 6자리 코드와 동일합니다. 각 항목에 `wi26_major_code`, `wi26_minor_code`, `wi26_minor_name`이 포함되어 WICS 소분류 → WI26 조회가 가능합니다.
