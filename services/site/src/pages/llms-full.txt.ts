import type { APIRoute } from "astro";
import { SITE, AUTHOR } from "../site.config";

export const GET: APIRoute = async () => {
  // Gather all MDX posts
  const modules = import.meta.glob<any>("/src/content/posts/*.mdx", { eager: true });
  const entries = Object.entries(modules).sort((a, b) => {
    const da = new Date(a[1].frontmatter.date).getTime();
    const db = new Date(b[1].frontmatter.date).getTime();
    return db - da;
  });

  const lines: string[] = [];

  // ── Header ──
  lines.push(`# ${SITE.title}`);
  lines.push("");
  lines.push(`> ${SITE.description}`);
  lines.push(`> URL: ${SITE.url}`);
  lines.push(`> Author: ${AUTHOR.name} — ${AUTHOR.description}`);
  lines.push(`> ${entries.length} posts · Updated ${new Date().toISOString().slice(0, 10)}`);
  lines.push("");

  // ── About ──
  lines.push("## About");
  lines.push("");
  lines.push(`${SITE.title} is a FOSS-first AI publication by ${AUTHOR.name}.`);
  lines.push(`${AUTHOR.description}`);
  lines.push("Content is hand-written MDX or generated via DeepSearchStack (SearXNG → crawl → embed → DeepSeek synthesis), human-reviewed before publish.");
  lines.push("");

  // ── Categories ──
  lines.push("## Categories");
  const categories = ["news", "guides", "benchmarks", "research", "opinion"];
  for (const cat of categories) {
    const count = entries.filter(([_, mod]) => mod.frontmatter.category === cat).length;
    lines.push(`- ${cat}: ${count} posts · ${SITE.url}/${cat === "guide" ? "guides" : cat + "s"}`);
  }
  lines.push("");

  // ── All Posts ──
  lines.push("## Posts");
  lines.push("");
  for (const [path, mod] of entries) {
    const fm = mod.frontmatter;
    const date = new Date(fm.date).toISOString().slice(0, 10);
    const slug = path.split("/").pop()?.replace(".mdx", "") ?? "";
    const url = `${SITE.url}/posts/${slug}/`;
    const excerpt = fm.excerpt || "";

    lines.push(`### ${fm.title}`);
    lines.push(`- URL: ${url}`);
    lines.push(`- Date: ${date}`);
    lines.push(`- Category: ${fm.category}`);
    if (fm.tags?.length) lines.push(`- Tags: ${fm.tags.join(", ")}`);
    lines.push(`- Modified: ${fm.modified ? new Date(fm.modified).toISOString().slice(0, 10) : date}`);
    if (fm.generated) {
      lines.push(`- Generated: yes (model: ${fm.model ?? "unknown"}, tokens: ${fm.tokens ?? "?"})`);
    }
    if (excerpt) lines.push(`- Excerpt: ${excerpt}`);
    lines.push("");
  }

  // ── Tech Stack ──
  lines.push("## Tech Stack");
  lines.push("- Frontend: Astro + MDX + nginx — static, zero client JS");
  lines.push("- Inference: DeepSeek via self-hosted gateway");
  lines.push("- Research: DeepSearchStack (SearXNG → crawl → embed → synthesize)");
  lines.push("- Infra: Docker Compose, bare metal, FOSS all the way down");
  lines.push("");

  // ── Key Pages ──
  lines.push("## Key Pages");
  const pages = [
    { label: "Home", url: SITE.url },
    { label: "News", url: `${SITE.url}/news` },
    { label: "Guides", url: `${SITE.url}/guides` },
    { label: "Benchmarks", url: `${SITE.url}/benchmarks` },
    { label: "Research", url: `${SITE.url}/research` },
    { label: "About", url: `${SITE.url}/about` },
    { label: "Generate", url: `${SITE.url}/generate` },
    { label: "RSS Feed", url: `${SITE.url}/rss.xml` },
    { label: "llms.txt (compact)", url: `${SITE.url}/llms.txt` },
  ];
  for (const p of pages) {
    lines.push(`- [${p.label}](${p.url})`);
  }
  lines.push("");

  // ── Footer ──
  lines.push("---");
  lines.push("This file is auto-generated from site content. For the compact version, see /llms.txt.");
  lines.push(`Repository: ${AUTHOR.sameAs.find((s) => s.includes("github.com/cleverlord/substrate")) ?? "https://github.com/cleverlord/substrate"}`);

  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
