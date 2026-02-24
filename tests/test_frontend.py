"""Frontend and static file serving tests."""

import pytest


class TestStaticFiles:
    """Verify static files are served correctly."""

    def test_index_html_served_at_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Chess Coach" in resp.text or "Dobbles" in resp.text

    def test_css_served(self, client):
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]

    def test_js_served(self, client):
        resp = client.get("/static/js/app.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    def test_css_has_design_system(self, client):
        resp = client.get("/static/css/style.css")
        text = resp.text
        # Verify Dobbles.AI design system vars exist
        assert "--color-bg" in text or "#1D1D1D" in text

    def test_js_has_navigation(self, client):
        resp = client.get("/static/js/app.js")
        text = resp.text
        assert "navigateTo" in text

    def test_html_has_all_nav_views(self, client):
        resp = client.get("/")
        text = resp.text
        views = ["dashboard", "games", "review", "patterns", "drills", "sessions"]
        for view in views:
            assert view in text.lower(), f"Missing nav view: {view}"

    def test_static_404(self, client):
        resp = client.get("/static/nonexistent.js")
        assert resp.status_code == 404
