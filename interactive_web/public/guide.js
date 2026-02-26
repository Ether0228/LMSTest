(async function () {
  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function inlineFormat(s) {
    // Very small subset: **bold**, `code`, [text](url)
    let out = escapeHtml(s);
    out = out.replaceAll(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>");
    out = out.replaceAll(/`([^`]+?)`/g, "<code>$1</code>");
    out = out.replaceAll(/\[([^\]]+?)\]\(([^)]+?)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    return out;
  }

  function slugFromHeading(text) {
    // Keep unicode, just trim and collapse whitespace.
    return text.trim().replaceAll(/\s+/g, " ");
  }

  function parseTables(lines, i) {
    // Detect a markdown table block:
    // | a | b |
    // |---|---|
    // | 1 | 2 |
    if (i + 1 >= lines.length) return null;
    const head = lines[i];
    const sep = lines[i + 1];
    if (!head.includes("|")) return null;
    if (!/^\s*\|?\s*[-:]+\s*\|/.test(sep)) return null;

    const rows = [];
    let j = i;
    while (j < lines.length && lines[j].includes("|") && lines[j].trim() !== "") {
      rows.push(lines[j]);
      j++;
    }
    if (rows.length < 2) return null;

    function splitRow(r) {
      const trimmed = r.trim().replace(/^\|/, "").replace(/\|$/, "");
      return trimmed.split("|").map((c) => c.trim());
    }

    const headerCells = splitRow(rows[0]);
    const bodyRows = rows.slice(2).map(splitRow);

    const html =
      "<table><thead><tr>" +
      headerCells.map((c) => `<th>${inlineFormat(c)}</th>`).join("") +
      "</tr></thead><tbody>" +
      bodyRows
        .map((cells) => "<tr>" + cells.map((c) => `<td>${inlineFormat(c)}</td>`).join("") + "</tr>")
        .join("") +
      "</tbody></table>";

    return { html, nextIndex: j };
  }

  function renderMarkdown(md) {
    const lines = md.split(/\r?\n/);
    const out = [];
    const toc = [];

    let inUl = false;
    let inQuote = false;

    function closeBlocks() {
      if (inUl) {
        out.push("</ul>");
        inUl = false;
      }
      if (inQuote) {
        out.push("</blockquote>");
        inQuote = false;
      }
    }

    for (let i = 0; i < lines.length; ) {
      const line = lines[i];

      const table = parseTables(lines, i);
      if (table) {
        closeBlocks();
        out.push(table.html);
        i = table.nextIndex;
        continue;
      }

      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeBlocks();
        const level = h[1].length;
        const text = h[2].trim();
        const id = slugFromHeading(text);
        out.push(`<h${Math.min(level, 3)} id="${escapeHtml(id)}">${inlineFormat(text)}</h${Math.min(level, 3)}>`); // cap at h3 for style
        if (level <= 2) toc.push({ level, text, id });
        i++;
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        if (!inQuote) {
          closeBlocks();
          out.push("<blockquote>");
          inQuote = true;
        }
        out.push(`<p>${inlineFormat(line.replace(/^\s*>\s?/, ""))}</p>`);
        i++;
        continue;
      }

      const li = line.match(/^\s*-\s+(.*)$/);
      if (li) {
        if (!inUl) {
          closeBlocks();
          out.push("<ul>");
          inUl = true;
        }
        out.push(`<li>${inlineFormat(li[1])}</li>`);
        i++;
        continue;
      }

      if (line.trim() === "") {
        closeBlocks();
        i++;
        continue;
      }

      closeBlocks();
      out.push(`<p>${inlineFormat(line)}</p>`);
      i++;
    }
    closeBlocks();

    return { html: out.join("\n"), toc };
  }

  function renderToc(toc) {
    const root = document.getElementById("toc");
    if (!root) return;
    root.innerHTML = toc
      .map((t) => {
        const cls = t.level === 1 ? "toc__h1" : "toc__h2";
        return `<a class="${cls}" href="#${encodeURIComponent(t.id)}">${escapeHtml(t.text)}</a>`;
      })
      .join("");
  }

  try {
    // Keep tenant/student query params when going back to the dashboard.
    const back = document.getElementById("backLink");
    if (back) back.href = `/${window.location.search}`;

    const resp = await fetch("/api/guide.md", { credentials: "include" });
    const md = await resp.text();
    const { html, toc } = renderMarkdown(md);
    const el = document.getElementById("guideContent");
    if (el) el.innerHTML = html;
    renderToc(toc);

    // If URL hash is URL-encoded, decode and scroll to the heading id.
    if (window.location.hash) {
      const target = decodeURIComponent(window.location.hash.slice(1));
      let node = document.getElementById(target);
      if (!node) {
        // Fuzzy match: allow partial anchorText from recommendations.
        const headings = Array.from(document.querySelectorAll(".md h1, .md h2, .md h3"));
        node =
          headings.find((h) => (h.id || "").startsWith(target)) ||
          headings.find((h) => target.startsWith(h.id || "")) ||
          headings.find((h) => (h.id || "").includes(target));
      }
      if (node) node.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  } catch (e) {
    const el = document.getElementById("guideContent");
    if (el) el.textContent = String(e.message || e);
  }
})();
