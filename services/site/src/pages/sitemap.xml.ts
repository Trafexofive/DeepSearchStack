import { SITE } from "../site.config";

const posts = Object.entries(import.meta.glob("/src/content/posts/*.mdx", { eager: true }))
  .map(([path, mod]: [string, any]) => ({
    slug: path.split("/").pop()?.replace(".mdx", "") || "",
    date: mod.frontmatter.date,
    modified: mod.frontmatter.modified ?? mod.frontmatter.date,
  }));

const staticPages = ["", "news", "guides", "benchmarks", "research", "opinion", "generate", "admin", "archive"];

export async function GET() {
  const urls = [
    ...staticPages.map(p => `  <url><loc>${SITE.url}/${p}</loc><changefreq>${p === "" ? "daily" : "weekly"}</changefreq><priority>${p === "" ? "1.0" : "0.7"}</priority></url>`),
    ...posts.map(p => `  <url><loc>${SITE.url}/posts/${p.slug}/</loc><lastmod>${new Date(p.modified).toISOString().slice(0, 10)}</lastmod><changefreq>monthly</changefreq><priority>0.9</priority></url>`),
  ];

  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join("\n")}\n</urlset>\n`,
    { headers: { "Content-Type": "application/xml" } }
  );
}
