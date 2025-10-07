export async function POST(request: Request) {
  const body = await request.json()
  
  const DEEPSEARCH_URL = process.env.DEEPSEARCH_API_URL || 'http://deepsearch:8001'
  
  const response = await fetch(`${DEEPSEARCH_URL}/deepsearch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  })

  return new Response(response.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  })
}
