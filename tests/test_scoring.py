from app.scoring import residual_score, score_assessment, tier_for


def test_weak_controls_keep_residual_high():
    scores = score_assessment(
        {
            "data_sensitivity": 5,
            "data_volume": 5,
            "system_access": 5,
            "business_criticality": 5,
            "fourth_party": 5,
            "soc2_iso": 0,
            "encryption": 0,
            "identity": 0,
            "incident_response": 0,
            "privacy": 0,
            "bcp": 0,
        }
    )
    assert scores["tier"] == "Critical"
    assert scores["residual"] >= 4.0


def test_strong_controls_reduce_residual():
    high_inherent = {
        "data_sensitivity": 5,
        "data_volume": 4,
        "system_access": 4,
        "business_criticality": 4,
        "fourth_party": 2,
    }
    strong = {
        **high_inherent,
        "soc2_iso": 5,
        "encryption": 5,
        "identity": 5,
        "incident_response": 5,
        "privacy": 5,
        "bcp": 5,
    }
    weak = {**high_inherent, "soc2_iso": 0, "encryption": 0, "identity": 0, "incident_response": 0, "privacy": 0, "bcp": 0}
    assert score_assessment(strong)["residual"] < score_assessment(weak)["residual"]


def test_tier_bands():
    assert tier_for(4.2) == "Critical"
    assert tier_for(3.1) == "High"
    assert tier_for(2.2) == "Moderate"
    assert tier_for(0.5) == "Low"


def test_residual_formula():
    assert residual_score(5.0, 0.0) == 5.0
    assert residual_score(5.0, 5.0) == 1.25
