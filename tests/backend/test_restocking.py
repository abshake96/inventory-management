"""
Tests for restocking recommendation and order endpoints.
"""
import pytest


class TestRestockingRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_returns_list(self, client):
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_default_budget_filters_results(self, client):
        """Default budget ($25,000) should return at least one recommendation."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()
        assert len(data) > 0

    def test_recommendation_schema(self, client):
        response = client.get("/api/restocking/recommendations")
        data = response.json()
        assert len(data) > 0
        rec = data[0]
        required_fields = [
            "item_sku", "item_name", "trend", "current_demand", "forecasted_demand",
            "gap", "unit_cost", "restock_quantity", "restock_cost",
            "lead_time_days", "lead_time_range", "category_type",
        ]
        for field in required_fields:
            assert field in rec, f"Missing field: {field}"

    def test_only_positive_gap_items(self, client):
        """All returned items must have gap > 0 (forecasted > current demand)."""
        response = client.get("/api/restocking/recommendations")
        for rec in response.json():
            assert rec["gap"] > 0
            assert rec["forecasted_demand"] > rec["current_demand"]

    def test_increasing_trend_sorted_first(self, client):
        """Increasing trend items should appear before stable/decreasing."""
        response = client.get("/api/restocking/recommendations?budget=50000")
        data = response.json()
        trends = [r["trend"] for r in data]
        # Find last increasing and first non-increasing index
        last_increasing = max((i for i, t in enumerate(trends) if t == "increasing"), default=-1)
        first_non_increasing = next((i for i, t in enumerate(trends) if t != "increasing"), len(trends))
        assert last_increasing < first_non_increasing

    def test_results_fit_within_budget(self, client):
        """Sum of restock_cost for all returned items must not exceed budget."""
        budget = 10000
        response = client.get(f"/api/restocking/recommendations?budget={budget}")
        total = sum(r["restock_cost"] for r in response.json())
        assert total <= budget

    def test_zero_budget_returns_empty(self, client):
        response = client.get("/api/restocking/recommendations?budget=0")
        assert response.json() == []

    def test_large_budget_returns_all_positive_gap_items(self, client):
        """With a very large budget, all items with positive gap should be returned."""
        response = client.get("/api/restocking/recommendations?budget=9999999")
        data = response.json()
        assert len(data) > 0
        for rec in data:
            assert rec["gap"] > 0

    def test_psu501_unit_cost(self, client):
        """PSU-501 should have unit_cost of 32.50 (inventory match)."""
        response = client.get("/api/restocking/recommendations?budget=9999999")
        psu = next((r for r in response.json() if r["item_sku"] == "PSU-501"), None)
        if psu:
            assert psu["unit_cost"] == 32.50

    def test_default_unit_cost_for_others(self, client):
        """Non-PSU-501 items should have unit_cost of 50.0."""
        response = client.get("/api/restocking/recommendations?budget=9999999")
        for rec in response.json():
            if rec["item_sku"] != "PSU-501":
                assert rec["unit_cost"] == 50.0

    def test_restock_cost_equals_qty_times_unit_cost(self, client):
        response = client.get("/api/restocking/recommendations?budget=9999999")
        for rec in response.json():
            expected = round(rec["restock_quantity"] * rec["unit_cost"], 2)
            assert abs(rec["restock_cost"] - expected) < 0.01

    def test_lead_time_by_category(self, client):
        """Electronics should have 6-day lead time, motors 12-day, general 8-day."""
        expected = {"electronics": 6, "motors": 12, "general": 8}
        response = client.get("/api/restocking/recommendations?budget=9999999")
        for rec in response.json():
            assert rec["lead_time_days"] == expected[rec["category_type"]]


class TestRestockingOrders:
    """Test suite for POST /api/restocking/orders and GET /api/restocking/orders."""

    def _sample_payload(self):
        return {
            "items": [
                {"sku": "WDG-001", "name": "Industrial Widget Type A", "quantity": 150, "unit_cost": 50.0},
                {"sku": "FLT-405", "name": "Oil Filter Cartridge", "quantity": 150, "unit_cost": 50.0},
            ],
            "total_budget": 25000.0,
        }

    def test_create_order_returns_201_or_200(self, client):
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        assert response.status_code in (200, 201)

    def test_create_order_schema(self, client):
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        order = response.json()
        required_fields = ["id", "order_number", "items", "status", "order_date", "expected_delivery", "total_value", "lead_time_days"]
        for field in required_fields:
            assert field in order, f"Missing field: {field}"

    def test_create_order_status_is_submitted(self, client):
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        assert response.json()["status"] == "Submitted"

    def test_create_order_number_prefix(self, client):
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        assert response.json()["order_number"].startswith("RST-")

    def test_create_order_total_value(self, client):
        payload = self._sample_payload()
        response = client.post("/api/restocking/orders", json=payload)
        expected_total = sum(i["quantity"] * i["unit_cost"] for i in payload["items"])
        assert abs(response.json()["total_value"] - expected_total) < 0.01

    def test_create_order_empty_items_returns_400(self, client):
        response = client.post("/api/restocking/orders", json={"items": [], "total_budget": 25000})
        assert response.status_code == 400

    def test_get_orders_returns_list(self, client):
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_submitted_order_appears_in_list(self, client):
        # Create an order then verify it appears in the list
        client.post("/api/restocking/orders", json=self._sample_payload())
        response = client.get("/api/restocking/orders")
        orders = response.json()
        assert any(o["order_number"].startswith("RST-") for o in orders)

    def test_motors_lead_time(self, client):
        """Orders containing a motor SKU should use 12-day lead time."""
        payload = {
            "items": [{"sku": "MTR-304", "name": "Electric Motor 5HP", "quantity": 5, "unit_cost": 50.0}],
            "total_budget": 5000.0,
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.json()["lead_time_days"] == 12

    def test_electronics_lead_time(self, client):
        """Orders with only electronics SKUs should use 6-day lead time."""
        payload = {
            "items": [{"sku": "PSU-501", "name": "5V 10A Switching Power Supply", "quantity": 10, "unit_cost": 32.50}],
            "total_budget": 5000.0,
        }
        response = client.post("/api/restocking/orders", json=payload)
        assert response.json()["lead_time_days"] == 6
