const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const publicDir = path.join(__dirname, "..", "public");
const templatePath = path.join(publicDir, "preview-terminal-v2.html");
const cssPath = path.join(publicDir, "preview-terminal.css");
const jsPath = path.join(publicDir, "preview-terminal.js");
const fixturePath = path.join(publicDir, "fixtures", "chuhe-xiong-qea.json");
const inlineOutputPath = path.join(publicDir, "preview-terminal-inline.html");
const staticOutputPath = path.join(publicDir, "preview-terminal-static.html");

function inlineAssets(html, css, js) {
  return html
    .replace(/<link rel="stylesheet" href="\/preview-terminal\.css[^"]*" \/>/, `<style>\n${css}\n</style>`)
    .replace(/<script src="\/preview-terminal\.js[^"]*"><\/script>/, `<script>\n${js}\n</script>`);
}

function createJsonResponse(data) {
  return {
    ok: true,
    status: 200,
    async json() {
      return JSON.parse(JSON.stringify(data));
    },
    async text() {
      return JSON.stringify(data);
    },
  };
}

async function waitForRender(dom) {
  const started = Date.now();
  while (Date.now() - started < 5000) {
    const doc = dom.window.document;
    const app = doc.getElementById("previewApp");
    const loading = doc.getElementById("previewLoading");
    const error = doc.getElementById("previewError");
    if (error && !error.hidden) {
      throw new Error(error.textContent.trim() || "Static render failed");
    }
    if (app && !app.hidden && loading && loading.hidden) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("Timed out waiting for preview render");
}

async function main() {
  const html = fs.readFileSync(templatePath, "utf8");
  const css = fs.readFileSync(cssPath, "utf8");
  const js = fs.readFileSync(jsPath, "utf8");
  const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
  const inlineHtml = inlineAssets(html, css, js);

  fs.writeFileSync(inlineOutputPath, inlineHtml);

  const dom = new JSDOM(inlineHtml, {
    pretendToBeVisual: true,
    runScripts: "dangerously",
    resources: "usable",
    url: "http://localhost:8787/preview-terminal-v2.html?fixture=/fixtures/chuhe-xiong-qea.json",
    beforeParse(window) {
      window.fetch = async (url) => {
        const target = String(url);
        if (target.includes("/fixtures/chuhe-xiong-qea.json")) {
          return createJsonResponse(fixture);
        }
        return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
      };
    },
  });

  await waitForRender(dom);

  const doc = dom.window.document;
  doc.querySelectorAll("script").forEach((node) => node.remove());
  doc.getElementById("previewLoading")?.remove();
  doc.getElementById("previewError")?.remove();
  doc.getElementById("noticeModal")?.remove();

  fs.writeFileSync(staticOutputPath, dom.serialize());
  dom.window.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
