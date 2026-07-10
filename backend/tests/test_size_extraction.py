from app.services.ocr import _map_schema


def test_size_extraction():
    # Test cases mapping raw input item dictionaries to expected modified dictionaries
    test_cases = [
        {
            "input": {"name": "Coke 12 oz"},
            "expected": {"name": "Coke", "weight": 12.0, "unit_type": "oz"},
        },
        {
            "input": {"name": "Almonds 1.5lb"},
            "expected": {"name": "Almonds", "weight": 1.5, "unit_type": "lb"},
        },
        {
            "input": {"name": "Flour 500 g"},
            "expected": {"name": "Flour", "weight": 500.0, "unit_type": "g"},
        },
        {
            "input": {"name": "Milk 1 gal"},
            "expected": {"name": "Milk", "weight": 1.0, "unit_type": "gal"},
        },
        {
            "input": {"name": "Soda 12 pk"},
            "expected": {"name": "Soda", "weight": 12.0, "unit_type": "pk"},
        },
        {
            "input": {"name": "Eggs 12ct"},
            "expected": {"name": "Eggs", "weight": 12.0, "unit_type": "ct"},
        },
        {
            "input": {"name": "Oranges 3.5 lb bag"},
            "expected": {"name": "Oranges bag", "weight": 3.5, "unit_type": "lb"},
        },
        {
            "input": {"name": "Just an item"},
            "expected": {"name": "Just an item"},  # No size, no change
        },
        {
            "input": {"name": "Apples 2 lb", "weight": 3.0, "unit_type": "kg"},
            "expected": {
                "name": "Apples 2 lb",
                "weight": 3.0,
                "unit_type": "kg",
            },  # Already has weight/unit, no change
        },
    ]

    for case in test_cases:
        input_data = {"items": [case["input"]]}
        result = _map_schema(input_data)

        extracted_item = result["items"][0]
        assert extracted_item["name"] == case["expected"]["name"]

        if "weight" in case["expected"]:
            assert extracted_item["weight"] == case["expected"]["weight"]
            assert extracted_item["unit_type"] == case["expected"]["unit_type"]
        else:
            assert "weight" not in extracted_item or not extracted_item["weight"]
