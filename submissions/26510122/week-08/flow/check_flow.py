"""Exercise the editable flow in Chrome, including import and responsive layout.

Run: uv run --with playwright python flow/check_flow.py
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright


def main() -> None:
    root = Path(__file__).resolve().parent
    screenshots = Path(tempfile.gettempdir()) / "ax-r3-flow-qa"
    screenshots.mkdir(exist_ok=True)
    checks = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1100, "height": 1000}, color_scheme="light")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((root / "agent-flow-standalone.html").as_uri())
        frame = page.frame_locator("iframe")
        frame.locator('#r3-flow-editor[data-ready="true"]').wait_for()
        frame.locator('[data-node-id="I04"] button').click()
        assert "모델이 대안 선택" in frame.locator("#flow-inspector").inner_text()
        checks.append("planned inventory includes model choice after tool calculation")

        frame.get_by_role("button", name="이 단계·조건 수정", exact=True).click()
        frame.locator("#edit-label").fill("모델 대안 비교 테스트")
        frame.locator("#edge-condition-i5").fill("계산한 기대이익과 위험을 비교해 모델이 수량을 승인했다.")
        frame.locator("#edge-to-i5").select_option("I06")
        frame.get_by_role("button", name="도식에 반영", exact=True).click()
        assert "모델 대안 비교 테스트" in frame.locator("#flow-inspector").inner_text()
        frame.get_by_role("button", name="JSON 내보내기", exact=True).click()
        exported = json.loads(frame.locator("#flow-json-text").input_value())
        inventory = next(f for f in exported["flows"] if f["id"] == "inventory")
        assert next(n for n in inventory["nodes"] if n["id"] == "I04")["label"] == "모델 대안 비교 테스트"
        assert "수량을 승인" in next(e for e in inventory["edges"] if e["id"] == "i5")["condition"]
        assert next(e for e in inventory["edges"] if e["id"] == "i5")["to"] == "I06"
        checks.append("node edits and edge conditions export as JSON")

        # The standalone shell persists widgetState through its host bridge.
        page.wait_for_timeout(250)
        page.reload()
        frame.locator('#r3-flow-editor[data-ready="true"]').wait_for()
        frame.locator('[data-node-id="I04"] button').click()
        assert "모델 대안 비교 테스트" in frame.locator("#flow-inspector").inner_text()
        checks.append("edited design survives reload")
        frame.get_by_role("button", name="구매 선택 → I06 중앙 공급처 매입", exact=True).click()
        assert "I06" in frame.locator("#flow-inspector").inner_text()
        checks.append("edited edge destinations can be followed")

        frame.locator('[data-node-id="I01"] button').click()
        frame.get_by_role("button", name="이 단계·조건 수정", exact=True).click()
        frame.locator("#edit-label").fill("목표 설계에만 반영한 관측 이름")
        frame.get_by_role("button", name="도식에 반영", exact=True).click()

        frame.locator("#flow-mode").select_option("current")
        assert "재고·판매 관측" in frame.locator('[data-node-id="I01"] button').inner_text()
        assert frame.locator('[data-node-id="I04"]').count() == 0
        frame.locator('[data-node-id="I03"] button').click()
        assert "Q 자동 적용" in frame.locator("#flow-inspector").inner_text()
        checks.append("current implementation stays separate from proposed model loop")

        for scope in ("inventory", "seller", "buyer", "overview"):
            frame.locator("#flow-scope").select_option(scope)
            for mode in ("current", "planned"):
                frame.locator("#flow-mode").select_option(mode)
                assert frame.locator(".flow-node").count() >= 8
                assert frame.locator(".flow-arrows path").count() >= 8
                for button in frame.locator(".flow-node button").all():
                    button.click()
                    collisions = frame.locator("#flow-canvas").evaluate("""canvas => {
                      const nodes=[...canvas.querySelectorAll('.flow-node button')].map(n=>n.getBoundingClientRect());
                      return [...canvas.querySelectorAll('.flow-arrows text')].filter(t=>{
                        const r=t.getBoundingClientRect();
                        return nodes.some(n=>r.left<n.right && r.right>n.left && r.top<n.bottom && r.bottom>n.top);
                      }).map(t=>t.textContent);
                    }""")
                    assert not collisions, (scope, mode, collisions)
        checks.append("all eight scope and basis combinations render")
        checks.append("selected arrow labels do not overlap node buttons")

        frame.get_by_role("button", name="JSON 내보내기", exact=True).click()
        broken = json.loads(frame.locator("#flow-json-text").input_value())
        broken["flows"][0]["edges"][0]["to"] = "MISSING"
        frame.locator("#flow-json-text").fill(json.dumps(broken, ensure_ascii=False))
        frame.get_by_role("button", name="붙여 넣은 JSON 반영", exact=True).click()
        assert "불러오기 실패" in frame.locator("#flow-error").inner_text()
        checks.append("invalid edge destination is rejected without changing the graph")

        malicious = json.loads((root / "flow-spec.json").read_text())
        malicious["flows"][0]["nodes"][0]["label"] = '<img src=x onerror="window.flowXss=true">'
        frame.locator("#flow-json-text").fill(json.dumps(malicious, ensure_ascii=False))
        frame.get_by_role("button", name="붙여 넣은 JSON 반영", exact=True).click()
        frame.locator("#flow-scope").select_option("inventory")
        assert frame.locator("#flow-canvas img").count() == 0
        checks.append("imported labels render as text, not executable markup")

        # Return to the actual design before capturing its appearance.
        frame.locator("#flow-file").set_input_files(str(root / "flow-spec.json"))
        assert "실제 거래 코드에는 적용되지 않습니다" in frame.locator("#flow-message").inner_text()
        checks.append("a saved JSON file can be imported")
        frame.locator("#flow-mode").select_option("planned")
        frame.locator('[data-node-id="I04"] button').click()
        frame.locator("#flow-json-panel").evaluate("element => element.open = false")

        for width in (1100, 768, 390, 352, 320):
            page.set_viewport_size({"width": width, "height": 1000})
            page.wait_for_timeout(100)
            overflow = frame.locator("#r3-flow-editor").evaluate("""root => {
              const width = document.documentElement.clientWidth;
              const bad = [...root.querySelectorAll('button, input, select, textarea, .flow-node')]
                .filter(e => e.getClientRects().length && !e.closest('details:not([open])'))
                .filter(e => {const r=e.getBoundingClientRect();return r.left < -1 || r.right > width+1;})
                .map(e=>e.id || e.textContent);
              return bad;
            }""")
            assert not overflow, (width, overflow)
        checks.append("controls and nodes fit desktop, tablet and narrow mobile widths")

        page.set_viewport_size({"width": 1100, "height": 1100})
        page.wait_for_timeout(150)
        page.screenshot(path=str(screenshots / "desktop-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")
        page.wait_for_timeout(150)
        page.screenshot(path=str(screenshots / "desktop-dark.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 1000})
        page.wait_for_timeout(150)
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(screenshots / "mobile-dark-top.png"))
        frame.locator("#flow-inspector").scroll_into_view_if_needed()
        page.wait_for_timeout(100)
        page.screenshot(path=str(screenshots / "mobile-dark-detail.png"))
        assert not errors, errors
        checks.append("no uncaught browser errors")
        browser.close()
    print(json.dumps({"checks": checks, "screenshots": str(screenshots), "browser_errors": errors},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
