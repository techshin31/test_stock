-- ============================================================
-- 전략 초기 데이터 (users, strategies 테이블 seed)
-- 04_trader_schema.sql 실행 후 한 번만 실행
-- ============================================================

INSERT INTO users (email, display_name, is_active) VALUES
('admin@quantpilot.local', 'Admin', TRUE)
ON CONFLICT (email) DO NOTHING;

INSERT INTO strategies (user_id, name, description, params, is_active)
SELECT u.id, s.name, s.description, s.params::jsonb, s.is_active
FROM (VALUES
    (
        'risk_neutral',
        '위험중립형 전략 — 하락장 현금 대피 + 단기채 ETF 주차',
        '{
            "entry1_size":        0.40,
            "entry2_size":        0.70,
            "entry2_window":      60,
            "sideways_size":      0.30,
            "deadcross_keep":     0.10,
            "transition_keep":    0.40,
            "downtrend_position": 0.0,
            "use_ma10_trigger":   false,
            "benchmark":          "단기채 100%",
            "target_cagr":        0.08,
            "warning_cagr":       0.05,
            "target_mdd":        -0.30,
            "warning_mdd":       -0.40,
            "target_mdd_duration":  24,
            "warning_mdd_duration": 36,
            "atr_period":  14,
            "bb_window":   20,
            "bb_std":       2.0,
            "ma10_window": 10
        }',
        TRUE
    ),
    (
        'aggressive',
        '적극투자형 전략 — MA10 빠른 진입 + 하락장 인버스 ETF',
        '{
            "entry1_size":        0.40,
            "entry2_size":        0.70,
            "entry2_window":      60,
            "sideways_size":      0.30,
            "deadcross_keep":     0.10,
            "transition_keep":    0.40,
            "downtrend_position": -1.0,
            "use_ma10_trigger":   true,
            "benchmark":          "B&H 5종목 균등",
            "target_cagr":        0.15,
            "warning_cagr":       0.10,
            "target_mdd":        -0.35,
            "warning_mdd":       -0.50,
            "target_mdd_duration":  24,
            "warning_mdd_duration": 36,
            "atr_period":  14,
            "bb_window":   20,
            "bb_std":       2.0,
            "ma10_window": 10
        }',
        TRUE
    )
) AS s(name, description, params, is_active)
CROSS JOIN (SELECT id FROM users WHERE email = 'admin@quantpilot.local') AS u
ON CONFLICT (user_id, name) DO NOTHING;
