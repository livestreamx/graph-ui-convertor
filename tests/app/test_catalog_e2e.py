from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.config import AppSettings
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_open_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "excalidraw_base_url": "/excalidraw",
            "excalidraw_proxy_upstream": "http://excalidraw.local",
            "excalidraw_proxy_prefix": "/excalidraw",
        },
    ) as context:
        assert context.expected_element_count is not None
        open_html = context.client.get(f"/catalog/{context.scene_id}/open").text
        scene_json = context.client.get(f"/api/scenes/{context.scene_id}").json()

        excalidraw_html = (
            "<html><body>"
            "<div id='status'>loading</div>"
            '<script src="/assets/app.js"></script>'
            "</body></html>"
        )
        excalidraw_js = (
            "const raw = localStorage.getItem('excalidraw') || '[]';"
            "const elements = JSON.parse(raw);"
            "document.getElementById('status').textContent = 'elements:' + elements.length;"
        )

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except PlaywrightError as exc:
                pytest.skip(f"Playwright browser not available: {exc}")
            page = browser.new_page()

            page.route(
                "**/api/scenes/**",
                lambda route: route.fulfill(
                    status=200,
                    body=json.dumps(scene_json),
                    headers={"Content-Type": "application/json"},
                ),
            )
            page.route(
                "**/excalidraw**",
                lambda route: route.fulfill(
                    status=200,
                    body=excalidraw_html,
                    headers={"Content-Type": "text/html"},
                ),
            )
            page.route(
                "**/assets/app.js",
                lambda route: route.fulfill(
                    status=200,
                    body=excalidraw_js,
                    headers={"Content-Type": "application/javascript"},
                ),
            )
            page.route(
                "**/manifest.webmanifest",
                lambda route: route.fulfill(
                    status=200,
                    body="{}",
                    headers={"Content-Type": "application/manifest+json"},
                ),
            )

            page.route(
                "**/catalog/**/open",
                lambda route: route.fulfill(
                    status=200,
                    body=open_html,
                    headers={"Content-Type": "text/html"},
                ),
            )
            page.goto(f"http://catalog.local/catalog/{context.scene_id}/open")
            page.wait_for_url(re.compile(r".*/excalidraw/?(?:\\?.*)?$"), timeout=10000)
            page.wait_for_selector("#status", timeout=10000)
            text = page.text_content("#status")
            browser.close()

    assert text == f"elements:{context.expected_element_count}"


def test_catalog_detail_render_graph_modal_e2e(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        detail_html = context.client.get(f"/catalog/{context.scene_id}").text
        graph_json = context.client.get(f"/api/scenes/{context.scene_id}/block-graph").json()
        vis_stub_js = """
window.vis = {
  DataSet: class {
    constructor(items) { this.items = Array.isArray(items) ? items : []; }
    get() { return this.items; }
  },
  Network: class {
    constructor(container, data) {
      const nodes = data.nodes && typeof data.nodes.get === "function" ? data.nodes.get() : [];
      const edges = data.edges && typeof data.edges.get === "function" ? data.edges.get() : [];
      window.__visRender = { nodes: nodes.length, edges: edges.length };
      container.innerHTML = "<div id='vis-ready'>ready</div>";
    }
    once(_event, callback) {
      if (typeof callback === "function") { callback(); }
    }
    fit() {}
    destroy() {}
  }
};
"""

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except PlaywrightError as exc:
                pytest.skip(f"Playwright browser not available: {exc}")
            page = browser.new_page()

            page.route(
                f"http://catalog.local/catalog/{context.scene_id}",
                lambda route: route.fulfill(
                    status=200,
                    body=detail_html,
                    headers={"Content-Type": "text/html"},
                ),
            )
            page.route(
                "**/api/scenes/**/block-graph",
                lambda route: route.fulfill(
                    status=200,
                    body=json.dumps(graph_json),
                    headers={"Content-Type": "application/json"},
                ),
            )
            page.route(
                "**/vis-network.min.js",
                lambda route: route.fulfill(
                    status=200,
                    body=vis_stub_js,
                    headers={"Content-Type": "application/javascript"},
                ),
            )
            page.goto(f"http://catalog.local/catalog/{context.scene_id}")
            page.click("#render-service-graph")
            page.wait_for_selector("#service-graph-modal:not([hidden])", timeout=10000)
            page.wait_for_selector("#vis-ready", timeout=10000)
            rendered = page.evaluate("window.__serviceGraphLastRender")
            browser.close()

        assert isinstance(rendered, dict)
        assert rendered["nodes"] == graph_json["meta"]["node_count"]
        assert rendered["edges"] == graph_json["meta"]["edge_count"]
