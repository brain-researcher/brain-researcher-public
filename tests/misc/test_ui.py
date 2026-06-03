#!/usr/bin/env python3
"""Test Brain Researcher UI and capture screenshots"""


from playwright.sync_api import sync_playwright


def test_brain_researcher_ui():
    with sync_playwright() as p:
        # Launch browser
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Testing Brain Researcher UI...")

        # Try to navigate to the home page
        try:
            # First try the root URL
            print("Navigating to http://localhost:3001/")
            response = page.goto(
                "http://localhost:3001/", wait_until="networkidle", timeout=10000
            )
            print(f"Response status: {response.status if response else 'No response'}")

            # Take a screenshot
            page.screenshot(path="ui_screenshot_home.png")
            print("Screenshot saved as ui_screenshot_home.png")

            # Get page title and content
            title = page.title()
            print(f"Page title: {title}")

            # Check for main content
            content = page.content()

            # Look for key UI elements
            if "Brain Researcher" in content:
                print("✓ Found Brain Researcher branding")

            if "90-second demo" in content or "Run the demo" in content:
                print("✓ Found demo CTA")

            if "Google" in content or "Microsoft" in content or "GitHub" in content:
                print("✓ Found OAuth providers")

            if "GLM" in content or "DMN" in content or "connectivity" in content:
                print("✓ Found example cards")

            # Try to find and click on elements
            try:
                # Look for the main demo button
                demo_button = page.locator(
                    'button:has-text("demo")',
                ).first
                if demo_button.is_visible():
                    print("✓ Demo button is visible")
            except:
                pass

            # Check for responsive design
            # Mobile view
            page.set_viewport_size({"width": 375, "height": 667})
            page.screenshot(path="ui_screenshot_mobile.png")
            print("Mobile screenshot saved as ui_screenshot_mobile.png")

            # Desktop view
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.screenshot(path="ui_screenshot_desktop.png")
            print("Desktop screenshot saved as ui_screenshot_desktop.png")

        except Exception as e:
            print(f"Error accessing main page: {e}")

            # Try alternative paths
            for path in ["/", "/auth/signin", "/dashboard", "/chat"]:
                try:
                    print(f"\nTrying path: {path}")
                    page.goto(
                        f"http://localhost:3001{path}",
                        wait_until="domcontentloaded",
                        timeout=5000,
                    )
                    page.screenshot(path=f"ui_screenshot_{path.replace('/', '_')}.png")
                    print(f"Screenshot saved for {path}")
                except Exception as e2:
                    print(f"Failed to access {path}: {e2}")

        finally:
            browser.close()
            print("\nTest complete!")


if __name__ == "__main__":
    test_brain_researcher_ui()
