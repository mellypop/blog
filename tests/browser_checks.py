import argparse
import functools
import hashlib
import json
import sys
import tempfile
import threading
import tomllib
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".cache/browser-checks"
AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.11.0/axe.min.js"
AXE_SHA256 = "e9e5863c33a874f09bc01acd9234b7e3c871479f5eef8802fa582544465e6d01"
OPTIONS = argparse.Namespace(browser_executable=None)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class BrowserChecks(unittest.TestCase):
    engine = "chromium"

    @classmethod
    def setUpClass(cls):
        cls.output = OUTPUT / cls.engine
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.reports = []
        cls.site = ROOT / "site"
        if not (cls.site / "index.html").is_file():
            raise RuntimeError("Build the site with zensical build --clean --strict first")
        config = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]
        cls.prefix = urlsplit(config["site_url"]).path.strip("/")
        cls.pages = sorted(
            file.relative_to(cls.site).as_posix()
            for file in cls.site.rglob("*.html")
            if file.name != "404.html"
        )
        cls.axe = OUTPUT / "axe.min.js"
        if not cls.axe.exists():
            with urlopen(AXE_URL, timeout=30) as response:
                cls.axe.write_bytes(response.read())
        if hashlib.sha256(cls.axe.read_bytes()).hexdigest() != AXE_SHA256:
            raise RuntimeError(f"Accessibility library checksum mismatch: {cls.axe}")
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        served = Path(directory.name)
        if cls.prefix:
            target = served / cls.prefix
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(cls.site, target_is_directory=True)
        else:
            served = cls.site
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=served)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            thread.join()

        cls.addClassCleanup(stop_server)
        cls.base = f"http://127.0.0.1:{server.server_port}/"
        if cls.prefix:
            cls.base += quote(cls.prefix, safe="/") + "/"
        with urlopen(cls.base, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Browser test server is not ready")
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        launch = {"headless": True}
        if OPTIONS.browser_executable and cls.engine == "chromium":
            launch["executable_path"] = OPTIONS.browser_executable
        cls.browser = getattr(cls.playwright, cls.engine).launch(**launch)
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def tearDownClass(cls):
        (cls.output / "accessibility.json").write_text(json.dumps(cls.reports, indent=2))

    def audit(self, page, label):
        report = page.evaluate(
            """async () => {
              const result = await axe.run(document, {
                runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']},
                resultTypes: ['violations', 'incomplete']
              });
              return {
                violations: result.violations.map(v => ({
                  id: v.id, impact: v.impact,
                  nodes: v.nodes.map(n => ({
                    target: n.target, summary: n.failureSummary
                  }))
                })),
                incomplete: result.incomplete.map(v => ({
                  id: v.id, targets: v.nodes.map(n => n.target)
                }))
              };
            }"""
        )
        self.reports.append({"label": label, **report})
        self.assertEqual(report["violations"], [], json.dumps(report, indent=2))

    def test_pages(self):
        for scheme in ("light", "dark"):
            for width in (1440, 390, 320):
                with self.browser.new_context(
                    color_scheme=scheme, viewport={"width": width, "height": 900}
                ) as context:
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "response",
                        lambda response: errors.append(f"{response.status} {response.url}")
                        if response.status >= 400 else None,
                    )
                    page.on(
                        "requestfailed",
                        lambda request: errors.append(f"{request.failure} {request.url}"),
                    )
                    for index, path in enumerate(self.pages):
                        with self.subTest(scheme=scheme, width=width, path=path):
                            errors.clear()
                            response = page.goto(self.base + path, wait_until="networkidle")
                            self.assertEqual(response.status, 200)
                            page.screenshot(
                                path=str(self.output / f"{scheme}-{width}-{index}.png"),
                                full_page=True,
                            )
                            self.assertEqual(
                                page.locator("body").get_attribute("data-md-color-scheme"),
                                "default" if scheme == "light" else "slate",
                            )
                            self.assertTrue(page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            ), "Horizontal overflow")
                            self.assertTrue(page.locator("img").evaluate_all(
                                "(es) => es.every(e => e.complete && e.naturalWidth > 0)"
                            ), "Broken image")
                            page.add_script_tag(path=str(self.axe))
                            label = f"{scheme}/{width}/{path}"
                            self.audit(page, label)
                            # Dots and gradients need isolated surface checks for axe contrast analysis.
                            page.add_style_tag(content="body { background-image: none !important; }")
                            for surface in (
                                ("soft", "warm", "cool") if path == "index.html" else ("soft",)
                            ):
                                page.add_style_tag(content=(
                                    ".diary-hero { background: var(--diary-"
                                    + surface + ") !important; }"
                                ))
                                self.audit(page, label + "/" + surface)
                                unresolved = [
                                    item for item in self.reports[-1]["incomplete"]
                                    if item["id"] == "color-contrast"
                                ]
                                self.assertEqual(unresolved, [], "Unresolved text contrast")
                            self.assertEqual(errors, [], "Browser or asset errors")

    def test_appearance_switching(self):
        with self.browser.new_context(color_scheme="light") as context:
            page = context.new_page()
            page.goto(self.base, wait_until="networkidle")

            def expect(scheme):
                page.wait_for_function(
                    "scheme => document.body.dataset.mdColorScheme === scheme",
                    arg=scheme,
                )

            expect("default")
            page.emulate_media(color_scheme="dark")
            expect("slate")
            toggle = page.locator('[data-md-component="palette"] label:visible')
            toggle.click()
            expect("default")
            page.reload(wait_until="networkidle")
            expect("default")
            page.emulate_media(color_scheme="light")
            toggle.click()
            expect("slate")
            page.reload(wait_until="networkidle")
            expect("slate")
            toggle.click()
            expect("default")
            page.emulate_media(color_scheme="dark")
            expect("slate")

    def test_theme_accents_and_search(self):
        for scheme in ("light", "dark"):
            with self.subTest(scheme=scheme):
                with self.browser.new_context(color_scheme=scheme) as context:
                    page = context.new_page()
                    page.goto(self.base, wait_until="networkidle")
                    fonts = page.evaluate(
                        """async () => {
                          const styles = ['400 16px', '700 16px', 'italic 400 16px', 'italic 700 16px'];
                          const faces = await Promise.all(styles.map(
                            style => document.fonts.load(style + ' "Maple Mono"')
                          ));
                          await document.fonts.ready;
                          return faces.map(list => list.map(face => ({
                            family: face.family, status: face.status
                          })));
                        }"""
                    )
                    self.assertTrue(all(
                        faces and all(
                            face["family"].strip('"') == "Maple Mono" and face["status"] == "loaded"
                            for face in faces
                        ) for faces in fonts
                    ), f"Maple Mono faces failed to load: {fonts}")
                    self.assertIn("Maple Mono", page.locator("body").evaluate(
                        "(e) => getComputedStyle(e).fontFamily"
                    ))
                    shadow = page.locator(".md-header").evaluate(
                        "(e) => getComputedStyle(e).boxShadow"
                    )
                    self.assertIn(
                        "rgb(199, 231, 250)" if scheme == "light" else "rgb(240, 196, 32)",
                        shadow,
                    )
                    self.assertEqual(page.locator(".md-button--primary").evaluate(
                        "(e) => getComputedStyle(e).backgroundColor"
                    ), "rgb(240, 196, 32)")
                    self.assertIn("assets/images/moon.svg", page.locator("h1").evaluate(
                        '(e) => getComputedStyle(e, "::before").backgroundImage'
                    ))
                    for name in ("moon.svg", "favicon.svg"):
                        self.assertEqual(
                            context.request.get(self.base + "assets/images/" + name).status,
                            200,
                        )
                    page.locator(".md-search__button").click()
                    search = page.get_by_role("combobox", name="Search")
                    search.fill("diary")
                    page.get_by_role("option").first.wait_for()
                    page.keyboard.press("ArrowDown")
                    self.assertTrue(search.get_attribute("aria-activedescendant"))
                    page.keyboard.press("Enter")
                    page.wait_for_function(
                        "() => !document.querySelector('dialog[open]')"
                    )
                    self.assertTrue(page.url.startswith(self.base), page.url)
                    page.emulate_media(reduced_motion="reduce")
                    self.assertEqual(page.locator("body").evaluate(
                        "(e) => getComputedStyle(e).animationName"
                    ), "none")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check the built diary before deployment")
    parser.add_argument(
        "--browser", choices=("all", "chromium", "firefox", "webkit"), default="all",
        help="Browser engine to test (default: all; WebKit covers Safari's engine)",
    )
    parser.add_argument("--browser-executable", help="Use an existing Chromium/Chrome binary")
    OPTIONS = parser.parse_args()
    if OPTIONS.browser_executable and OPTIONS.browser != "chromium":
        parser.error("--browser-executable requires --browser chromium")
    engines = ("chromium", "firefox", "webkit") if OPTIONS.browser == "all" else (OPTIONS.browser,)
    suite = unittest.TestSuite()
    for engine in engines:
        checks = type(
            engine.capitalize() + "Checks", (BrowserChecks,),
            {"engine": engine, "__module__": __name__},
        )
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(checks))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
