# DeepSearch Frontend

Modern Next.js frontend for DeepSearch with shadcn/ui components, Radix UI primitives, and Tailwind CSS.

## Features

- **Real-time streaming** - SSE-based streaming of DeepSearch results
- **Progress updates** - Live feedback during search → scrape → synthesis pipeline
- **Clean UI** - Modern, responsive design with dark mode support
- **Type-safe** - TypeScript throughout
- **Component library** - shadcn/ui + Radix UI primitives

## Tech Stack

- Next.js 15 (App Router)
- React 19
- TypeScript
- Tailwind CSS
- Radix UI
- Lucide Icons

## Development

```bash
# Install dependencies
npm install

# Run dev server
npm run dev

# Build for production
npm run build

# Start production server
npm start
```

## Environment Variables

```env
DEEPSEARCH_API_URL=http://deepsearch:8001
```

## Docker

```bash
# Build
docker build -t deepsearch-frontend .

# Run
docker run -p 3000:3000 -e DEEPSEARCH_API_URL=http://deepsearch:8001 deepsearch-frontend
```

## Architecture

```
Frontend (Next.js)
  ↓
API Routes (/api/deepsearch)
  ↓
DeepSearch Service
  ↓
Search Pipeline
```

The frontend acts as a thin proxy, with API routes forwarding requests to the DeepSearch service and streaming responses back to the client.

## Features Implemented

✅ Real-time streaming search
✅ Progress indicators
✅ Source display
✅ Responsive design
✅ Dark mode support

## TODO

- [ ] Session management UI
- [ ] Search history
- [ ] Advanced search options panel
- [ ] Result bookmarking
- [ ] Multi-query comparison
- [ ] Export results

## License

MIT
