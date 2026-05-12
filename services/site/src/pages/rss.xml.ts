import rss from "@astrojs/rss";
import { SITE } from "../site.config";

const posts = Object.entries(import.meta.glob("/src/content/posts/*.mdx", { eager: true }))
  .map(([path, mod]: [string, any]) => ({
    slug: path.split("/").pop()?.replace(".mdx", "") || "",
    ...mod.frontmatter,
  }))
  .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
  .slice(0, 30);

export async function GET() {
  return rss({
    title: SITE.title,
    description: SITE.description,
    site: SITE.url,
    items: posts.map((p: any) => ({
      title: p.title,
      pubDate: new Date(p.date),
      description: p.excerpt || "",
      link: `/posts/${p.slug}`,
      categories: [p.category, ...(p.tags || [])],
    })),
    customData: "<language>en-us</language>",
  });
}
